/*
 * TrackPoint HID over I2C Driver (Zephyr Input Subsystem)
 * Interrupt-driven version (minimal modification)
 * Copyright (c) 2025 ZitaoTech
 * SPDX-License-Identifier: MIT
 */

#define DT_DRV_COMPAT zmk_trackpoint

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <stdlib.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/i2c.h>
#include <math.h>
#include <zmk/event_manager.h>
#include <zmk/events/position_state_changed.h>

#include <zephyr/input/input.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/dt-bindings/input/input-event-codes.h>

#include "motion_shaping.h"
#include "custom_led.h"

LOG_MODULE_REGISTER(trackpoint, LOG_LEVEL_DBG);

/* ========= ⭐ TrackPoint 专用 Work Queue ========= */
#define TP_WORKQ_STACK_SIZE 2048
#define TP_WORKQ_PRIORITY 5

/* ========= ⭐ NEW: I2C Mutex ========= */
static struct k_mutex trackpoint_i2c_mutex;

K_THREAD_STACK_DEFINE(tp_workq_stack, TP_WORKQ_STACK_SIZE);
static struct k_work_q tp_workq;

/* ========================================================================= */
/* Mouse and scroll setting              */
/* ========================================================================= */

#define DOMINANT_NUMERATOR CONFIG_TRACKPOINT_DOMINANT_NUMERATOR
#define DOMINANT_DENOMINATOR CONFIG_TRACKPOINT_DOMINANT_DENOMINATOR

#define SLOW_KEY_MULTIPLIER 0.5f

/* ========= Motion shaping (the pure math lives in motion_shaping.c) ========= */

static const struct motion_arrow_config trackpoint_arrow = {
    .deadzone = CONFIG_TRACKPOINT_ARROW_DEADZONE,
    .divisor_slow = CONFIG_TRACKPOINT_ARROW_DIVISOR_SLOW,
    .divisor_fast = CONFIG_TRACKPOINT_ARROW_DIVISOR_FAST,
};

/* The TrackPoint scales in floats throughout, so it takes no integer
 * pre-scale: 1/1 leaves the raw delta alone. */
static const struct motion_cursor_config trackpoint_cursor = {
    .prescale_num = 1,
    .prescale_den = 1,
    .base_speed = CONFIG_TRACKPOINT_MOUSE_BASE_SPEED_PERCENT / 100.0f,
    .sens_base = CONFIG_TRACKPOINT_MOUSE_SENS_BASE_PERCENT / 100.0f,
    .sens_step = CONFIG_TRACKPOINT_MOUSE_SENS_STEP_PERCENT / 100.0f,
    .slow_multiplier = SLOW_KEY_MULTIPLIER,
};

/* ========= Motion GPIO ========= */

#define MOTION_GPIO_NODE DT_NODELABEL(gpio0)
#define MOTION_GPIO_PIN 7
#define MOTION_GPIO_FLAGS (GPIO_ACTIVE_LOW | GPIO_PULL_UP)

/* ========= TrackPoint 常量 ========= */
#define TRACKPOINT_I2C_ADDR 0x15
#define TRACKPOINT_PACKET_LEN 7
#define TRACKPOINT_MAGIC_BYTE0 0x50

/* ========= Watch Dog ========= */
static uint32_t last_activity_time = 0;
#define TRACKPOINT_WDT_TIMEOUT 200
/* ========= 全局状态 ========= */
static bool scroll_key_pressed = false;
static bool arrow_key_pressed = false;
static bool slow_key_pressed = false;
static bool last_arrow_key_pressed = false;

/* ========= Space + Slow key listener ========= */
static int special_key_listener_cb(const zmk_event_t *eh) {
    const struct zmk_position_state_changed *ev = as_zmk_position_state_changed(eh);
    if (!ev)
        return 0;
    if (ev->position == 20) {
        arrow_key_pressed = ev->state;
        LOG_INF("arrow key position=20 %s", arrow_key_pressed ? "PRESSED" : "RELEASED");
    }

    // Scroll key (right-thumb TAB, &mt RSHFT TAB at key position 50). Holding
    // it switches trackpoint motion from cursor to scroll. Note: this position
    // is a mod-tap, so holding also engages Right-Shift (host-visible).
    if (ev->position == 50) {
        scroll_key_pressed = ev->state;
        LOG_INF("scroll key position=50 %s", scroll_key_pressed ? "PRESSED" : "RELEASED");
    }

    // ★ NEW: Slow key
    if (ev->position == 22) {
        slow_key_pressed = ev->state;
        LOG_INF("slow key position=22 %s", slow_key_pressed ? "PRESSED" : "RELEASED");
    }

    return 0;
}
ZMK_LISTENER(trackpoint_special_key_listener, special_key_listener_cb);
ZMK_SUBSCRIPTION(trackpoint_special_key_listener, zmk_position_state_changed);

struct trackpoint_config {
    struct i2c_dt_spec i2c;
    struct gpio_dt_spec motion_gpio;
};

struct trackpoint_data {
    const struct device *dev;
    struct k_work work;
    struct gpio_callback motion_cb_data;
    struct k_work_delayable enable_irq_work;
    uint32_t last_packet_time;
    struct motion_scroll_residue scroll_residue;
    int16_t arrow_residue_x;
    int16_t arrow_residue_y;
};

/* ========= EXPONENTIAL caculate ========= */
#ifdef CONFIG_TRACKPOINT_EXPONENTIAL
#define TP_MAX_MULT 2.0f
static inline float trackpoint_exponential_factor(int8_t dx, int8_t dy, uint32_t delta_ms) {
    if (delta_ms == 0)
        delta_ms = 1;

    int dist = abs(dx) + abs(dy);
    if (dist < 1)
        return 1.0f;

    float speed = (float)dist / (float)delta_ms;
    float mult = expf(speed * 1.307357f);

    return (mult > TP_MAX_MULT) ? TP_MAX_MULT : mult;
}
#endif

/* ========= Read data ========= */
static int trackpoint_read_packet(const struct device *dev, int8_t *dx, int8_t *dy) {
    const struct trackpoint_config *cfg = dev->config;
    uint8_t buf[TRACKPOINT_PACKET_LEN] = {0};

    int ret;

    k_mutex_lock(&trackpoint_i2c_mutex, K_FOREVER);

    ret = i2c_read_dt(&cfg->i2c, buf, TRACKPOINT_PACKET_LEN);

    k_mutex_unlock(&trackpoint_i2c_mutex);

    if (ret < 0)
        return ret;

    if (buf[0] != TRACKPOINT_MAGIC_BYTE0)
        return -EIO;

    *dx = (int8_t)buf[2];
    *dy = (int8_t)buf[3];
    return 0;
}

/* Shape one axis of arrow motion, then emit whatever it decided. */
static void report_arrow_axis(const struct device *dev, int8_t delta, int16_t *residue,
                              uint16_t key_neg, uint16_t key_pos) {
    const struct motion_arrow_pulse pulse = motion_arrow_step(&trackpoint_arrow, delta, residue);
    const uint16_t key = (pulse.direction > 0) ? key_pos : key_neg;

    for (uint8_t i = 0; i < pulse.pulses; i++) {
        // 触发 key press + release（脉冲）
        input_report_key(dev, key, 1, true, K_FOREVER);
        input_report_key(dev, key, 0, true, K_FOREVER);
    }
}

static void trackpoint_work_cb(struct k_work *work) {
    struct trackpoint_data *data = CONTAINER_OF(work, struct trackpoint_data, work);
    const struct device *dev = data->dev;

    uint32_t now = k_uptime_get_32();

    /* ========= WATCHDOG ========= */
    if (now - last_activity_time > TRACKPOINT_WDT_TIMEOUT) {
        LOG_WRN("TrackPoint watchdog recovery");

        data->arrow_residue_x = 0;
        data->arrow_residue_y = 0;
        return;
    }

    int8_t dx = 0, dy = 0;

    /* ========= single read ========= */
    int ret = trackpoint_read_packet(dev, &dx, &dy);

    if (ret != 0) {
        LOG_WRN("TrackPoint I2C read failed (soft recover)");

        /* ⚠️ 不 break，不 sleep，不卡住 */
        return;
    }

    last_activity_time = now;

    /* ========= arrow mode detect ========= */
    bool just_enter_arrow = arrow_key_pressed && !last_arrow_key_pressed;

    if (arrow_key_pressed) {

        if (just_enter_arrow) {
            data->arrow_residue_x = dx;
            data->arrow_residue_y = dy;
        }

        motion_dominant_axis(&dx, &dy, DOMINANT_NUMERATOR, DOMINANT_DENOMINATOR);

        report_arrow_axis(dev, dx, &data->arrow_residue_x,
                          INPUT_BTN_0,  // 左
                          INPUT_BTN_1); // 右

        report_arrow_axis(dev, dy, &data->arrow_residue_y,
                          INPUT_BTN_2,  // 上
                          INPUT_BTN_3); // 下
        k_msleep(16);
    } else if (scroll_key_pressed) {

        const struct motion_scroll_ticks ticks =
            motion_scroll_accumulate(&data->scroll_residue, dx, dy);

        input_report_rel(dev, INPUT_REL_HWHEEL, -ticks.x, false, K_FOREVER);
        input_report_rel(dev, INPUT_REL_WHEEL, ticks.y, true, K_FOREVER);
        k_msleep(25);

    } else {

        /* Speed preference. On this keyboard it rides in on the LED brightness
         * -- one physical knob drives both. Odd, but shipped. */
        const uint8_t speed_preference = custom_led_get_last_valid_brightness();

#ifdef CONFIG_TRACKPOINT_EXPONENTIAL
        uint32_t delta = now - data->last_packet_time;
        float exp_mult = trackpoint_exponential_factor(dx, dy, delta);
#else
        float exp_mult = 1.0f;
#endif

        const float fx = motion_cursor_scale(&trackpoint_cursor, dx, speed_preference,
                                             slow_key_pressed, exp_mult);
        const float fy = motion_cursor_scale(&trackpoint_cursor, dy, speed_preference,
                                             slow_key_pressed, exp_mult);

        input_report_rel(dev, INPUT_REL_X, -(int)fx, false, K_NO_WAIT);
        input_report_rel(dev, INPUT_REL_Y, -(int)fy, true, K_NO_WAIT);
    }

    last_arrow_key_pressed = arrow_key_pressed;
    data->last_packet_time = now;
    k_msleep(5);
}

/* ========= ★ GPIO Interrupt ========= */
static void motion_isr(const struct device *port, struct gpio_callback *cb, uint32_t pins) {
    struct trackpoint_data *data = CONTAINER_OF(cb, struct trackpoint_data, motion_cb_data);

    last_activity_time = k_uptime_get_32();

    k_work_submit_to_queue(&tp_workq, &data->work);
}

static void trackpoint_enable_irq_work_cb(struct k_work *work) {
    struct k_work_delayable *dwork = CONTAINER_OF(work, struct k_work_delayable, work);
    struct trackpoint_data *data = CONTAINER_OF(dwork, struct trackpoint_data, enable_irq_work);
    const struct device *dev = data->dev;
    const struct trackpoint_config *cfg = dev->config;

    gpio_pin_interrupt_configure_dt(&cfg->motion_gpio, GPIO_INT_EDGE_TO_ACTIVE);

    LOG_INF("TrackPoint IRQ enabled (delayed)");
}
/* ========= Inital ========= */
static int trackpoint_init(const struct device *dev) {
    const struct trackpoint_config *cfg = dev->config;
    struct trackpoint_data *data = dev->data;
    if (!i2c_is_ready_dt(&cfg->i2c))
        return -ENODEV;
    if (!gpio_is_ready_dt(&cfg->motion_gpio))
        return -ENODEV;

    k_mutex_init(&trackpoint_i2c_mutex);

    data->dev = dev;
    data->scroll_residue = (struct motion_scroll_residue){0};
    data->arrow_residue_x = 0;
    data->arrow_residue_y = 0;
    data->last_packet_time = k_uptime_get_32();

    k_work_init(&data->work, trackpoint_work_cb);

    /* ========= ⭐  Work Queue ========= */
    k_work_queue_start(&tp_workq, tp_workq_stack, K_THREAD_STACK_SIZEOF(tp_workq_stack),
                       TP_WORKQ_PRIORITY, NULL);

    gpio_pin_configure_dt(&cfg->motion_gpio, GPIO_INPUT);

    gpio_init_callback(&data->motion_cb_data, motion_isr, BIT(cfg->motion_gpio.pin));
    gpio_add_callback(cfg->motion_gpio.port, &data->motion_cb_data);

    k_work_init_delayable(&data->enable_irq_work, trackpoint_enable_irq_work_cb);
    k_work_schedule(&data->enable_irq_work, K_MSEC(5));

    LOG_INF("TrackPoint Driver Initialized (IRQ delayed)");
    return 0;
}

#define TRACKPOINT_DEFINE(inst)                                                                    \
    static struct trackpoint_data trackpoint_data_##inst;                                          \
    static const struct trackpoint_config trackpoint_config_##inst = {                             \
        .i2c = I2C_DT_SPEC_INST_GET(inst),                                                         \
        .motion_gpio = {.port = DEVICE_DT_GET(MOTION_GPIO_NODE),                                   \
                        .pin = MOTION_GPIO_PIN,                                                    \
                        .dt_flags = MOTION_GPIO_FLAGS},                                            \
    };                                                                                             \
    DEVICE_DT_INST_DEFINE(inst, trackpoint_init, NULL, &trackpoint_data_##inst,                    \
                          &trackpoint_config_##inst, POST_KERNEL, 90, NULL);

DT_INST_FOREACH_STATUS_OKAY(TRACKPOINT_DEFINE);
