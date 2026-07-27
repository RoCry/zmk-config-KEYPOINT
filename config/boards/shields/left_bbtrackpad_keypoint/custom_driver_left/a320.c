/*
 * A320 trackpad HID over I2C Driver (Zephyr Input Subsystem)
 * Interrupt-driven version (minimal modification)
 * Copyright (c) 2025 ZitaoTech
 * SPDX-License-Identifier: MIT
 */

#define DT_DRV_COMPAT avago_a320

#include <stdint.h>
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/sys/util.h>
#include <zmk/event_manager.h>
#include <zmk/events/position_state_changed.h>

#include <zephyr/input/input.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/dt-bindings/input/input-event-codes.h>

#include "motion_shaping.h"
#include "trackpad_led.h"
#include "a320.h"

LOG_MODULE_REGISTER(a320, CONFIG_A320_LOG_LEVEL);

/* ========= ⭐ A320  Work Queue ========= */
#define A320_WORKQ_STACK_SIZE 2048
#define A320_WORKQ_PRIORITY 5

/* ========= ⭐ NEW: I2C Mutex ========= */
static struct k_mutex a320_i2c_mutex;

K_THREAD_STACK_DEFINE(a320_workq_stack, A320_WORKQ_STACK_SIZE);
static struct k_work_q a320_workq;


#define DOMINANT_NUMERATOR CONFIG_A320_DOMINANT_NUMERATOR
#define DOMINANT_DENOMINATOR CONFIG_A320_DOMINANT_DENOMINATOR

#define SLOW_KEY_MULTIPLIER 0.5f

/* ========= Motion shaping (the pure math lives in motion_shaping.c) ========= */

static const struct motion_arrow_config a320_arrow = {
    .deadzone = CONFIG_A320_ARROW_DEADZONE,
    .divisor_slow = CONFIG_A320_ARROW_DIVISOR_SLOW,
    .divisor_fast = CONFIG_A320_ARROW_DIVISOR_FAST,
};

/* The 3/4 integer pre-scale is the A320's own coarse gain; it truncates, and
 * that truncation is the trackpad's shipped feel. */
static const struct motion_cursor_config a320_cursor = {
    .prescale_num = 3,
    .prescale_den = 4,
    .base_speed = 1.0f,
    .sens_base = CONFIG_A320_MOUSE_SENS_BASE_PERCENT / 100.0f,
    .sens_step = CONFIG_A320_MOUSE_SENS_STEP_PERCENT / 100.0f,
    .slow_multiplier = SLOW_KEY_MULTIPLIER,
};

/* ========= Motion GPIO ========= */

#define MOTION_GPIO_NODE DT_NODELABEL(gpio0)
#define MOTION_GPIO_PIN 8
#define MOTION_GPIO_FLAGS (GPIO_ACTIVE_LOW | GPIO_PULL_UP)

/* ========= A320 parameter ========= */
#define A320_I2C_ADDR 0x3B
#define A320_PACKET_LEN 3

#define TOUCH_IDLE_TIMEOUT 50 // 30~80ms 看手感
/* ========= Watch Dog ========= */
static uint32_t last_activity_time = 0;
#define A320_WDT_TIMEOUT 200
/* ========= global ========= */
static bool scroll_key_pressed = false;
static bool arrow_key_pressed = false;
static bool slow_key_pressed = false;
static bool last_arrow_key_pressed = false;
static uint32_t last_touch_time = 0;

/* ========= Space + Slow Key listener ========= */
static int special_key_listener_cb(const zmk_event_t *eh) {
    const struct zmk_position_state_changed *ev = as_zmk_position_state_changed(eh);
    if (!ev)
        return 0;
    if (ev->position == 20) {
        arrow_key_pressed = ev->state;
        LOG_INF("arrow key position=20 %s", arrow_key_pressed ? "PRESSED" : "RELEASED");
    }

    if (ev->position == 48 || ev->position == 49) {
        scroll_key_pressed = ev->state;
        LOG_INF("scroll key position=%d %s", ev->position,
                scroll_key_pressed ? "PRESSED" : "RELEASED");
    }

    if (ev->position == 22) {
        slow_key_pressed = ev->state;
        LOG_INF("slow key position=22 %s", slow_key_pressed ? "PRESSED" : "RELEASED");
    }

    return 0;
}
ZMK_LISTENER(a320_special_key_listener, special_key_listener_cb);
ZMK_SUBSCRIPTION(a320_special_key_listener, zmk_position_state_changed);

struct a320_config {
    struct i2c_dt_spec i2c;
    struct gpio_dt_spec motion_gpio;
};

struct a320_data {
    const struct device *dev;
    struct k_work work;
    struct gpio_callback motion_cb_data;
    struct k_work_delayable enable_irq_work; // ⭐ 新增
    uint32_t last_packet_time;
    struct motion_scroll_residue scroll_residue;
    int16_t arrow_residue_x;
    int16_t arrow_residue_y;
};

static int a320_read_packet(const struct device *dev, int8_t *dx, int8_t *dy) {
    const struct a320_config *cfg = dev->config;
    uint8_t buf[A320_PACKET_LEN] = {0};
    uint8_t reg = 0x82;

    int ret;

    k_mutex_lock(&a320_i2c_mutex, K_FOREVER);

    ret = i2c_write_dt(&cfg->i2c, &reg, 1);
    if (ret < 0) {
        goto out;
    }

    ret = i2c_burst_read_dt(&cfg->i2c, 0x82, buf, sizeof(buf));
    if (ret < 0) {
        goto out;
    }

    *dx = (int8_t)buf[1];
    *dy = -(int8_t)buf[2];
    ret = 0;

out:
    k_mutex_unlock(&a320_i2c_mutex);
    return ret;
}

/* Shape one axis of arrow motion, then emit whatever it decided. */
static void report_arrow_axis(const struct device *dev, int8_t delta, int16_t *residue,
                              uint16_t key_neg, uint16_t key_pos) {
    const struct motion_arrow_pulse pulse = motion_arrow_step(&a320_arrow, delta, residue);
    const uint16_t key = (pulse.direction > 0) ? key_pos : key_neg;

    for (uint8_t i = 0; i < pulse.pulses; i++) {
        // 触发 key press + release（脉冲）
        input_report_key(dev, key, 1, true, K_FOREVER);
        input_report_key(dev, key, 0, true, K_FOREVER);
    }
}

static void a320_work_cb(struct k_work *work) {
    struct a320_data *data = CONTAINER_OF(work, struct a320_data, work);
    const struct device *dev = data->dev;

    uint32_t now = k_uptime_get_32();

    /* ========= WATCHDOG ========= */
    if (now - last_activity_time > A320_WDT_TIMEOUT) {
        LOG_WRN("A320 watchdog recovery");

        data->arrow_residue_x = 0;
        data->arrow_residue_y = 0;
        last_arrow_key_pressed = arrow_key_pressed;

        return;
    }

    int8_t dx = 0, dy = 0;

    /* ========= ⭐ NEW: DRAIN MODE ========= */
    int16_t total_dx = 0;
    int16_t total_dy = 0;
    bool got_data = false;

    while (1) {
        int ret = a320_read_packet(dev, &dx, &dy);

        if (ret != 0) {
            break;
        }

        /* 防止异常空包 */
        if (dx == 0 && dy == 0) {
            break;
        }

        total_dx += dx;
        total_dy += dy;
        got_data = true;
    }

    if (got_data) {
        last_touch_time = now;
    }

    /* ========= ⭐ TOUCH RELEASE  ========= */
    if (!got_data) {
        return;
    }

    dx = CLAMP(total_dx, INT8_MIN, INT8_MAX);
    dy = CLAMP(total_dy, INT8_MIN, INT8_MAX);

    /* ========= scroll / arrow mode 切换检测 ========= */
    bool scroll_mode_active =
        IS_ENABLED(CONFIG_A320_START_IN_SCROLL_MODE) ? !scroll_key_pressed : scroll_key_pressed;
    bool just_enter_arrow = arrow_key_pressed && !last_arrow_key_pressed;

    if (arrow_key_pressed) {

        if (just_enter_arrow) {
            data->arrow_residue_x = dx;
            data->arrow_residue_y = dy;
        }

        motion_dominant_axis(&dx, &dy, DOMINANT_NUMERATOR, DOMINANT_DENOMINATOR);

        report_arrow_axis(dev, dx, &data->arrow_residue_x, INPUT_BTN_1, INPUT_BTN_0);

        report_arrow_axis(dev, dy, &data->arrow_residue_y, INPUT_BTN_3, INPUT_BTN_2);
    } else if (scroll_mode_active) {

        const struct motion_scroll_ticks ticks =
            motion_scroll_accumulate(&data->scroll_residue, dx, dy);

        input_report_rel(dev, INPUT_REL_HWHEEL, ticks.x, false, K_FOREVER);
        input_report_rel(dev, INPUT_REL_WHEEL, -ticks.y, true, K_FOREVER);
        k_msleep(25);
    } else {

        /* Speed preference. On this keyboard it rides in on the indicator LED
         * brightness -- one physical knob drives both. Odd, but shipped. */
        const uint8_t speed_preference = indicator_tp_get_last_valid_brightness();

        const float fx =
            motion_cursor_scale(&a320_cursor, dx, speed_preference, slow_key_pressed, 1.0f);
        const float fy =
            motion_cursor_scale(&a320_cursor, dy, speed_preference, slow_key_pressed, 1.0f);

        input_report_rel(dev, INPUT_REL_X, (int)fx, false, K_NO_WAIT);
        input_report_rel(dev, INPUT_REL_Y, (int)fy, true, K_NO_WAIT);
    }

    last_arrow_key_pressed = arrow_key_pressed;
    data->last_packet_time = now;
    k_msleep(4);
}

/* ========= GPIO ISR ========= */
static void motion_isr(const struct device *port, struct gpio_callback *cb, uint32_t pins) {
    struct a320_data *data = CONTAINER_OF(cb, struct a320_data, motion_cb_data);

    last_activity_time = k_uptime_get_32();

    k_work_submit_to_queue(&a320_workq, &data->work);
}

bool tp_is_touched(void) {
    if (last_touch_time == 0) {
        return false;
    }

    return (k_uptime_get_32() - last_touch_time) <= TOUCH_IDLE_TIMEOUT;
}

static void a320_enable_irq_work_cb(struct k_work *work) {
    struct k_work_delayable *dwork = CONTAINER_OF(work, struct k_work_delayable, work);
    struct a320_data *data = CONTAINER_OF(dwork, struct a320_data, enable_irq_work);
    const struct device *dev = data->dev;
    const struct a320_config *cfg = dev->config;

    gpio_pin_interrupt_configure_dt(&cfg->motion_gpio, GPIO_INT_EDGE_TO_ACTIVE);

    LOG_INF("A320 IRQ enabled (delayed)");
}
/* ========= Inital ========= */
static int a320_init(const struct device *dev) {
    const struct a320_config *cfg = dev->config;
    struct a320_data *data = dev->data;

    if (!i2c_is_ready_dt(&cfg->i2c))
        return -ENODEV;
    if (!gpio_is_ready_dt(&cfg->motion_gpio))
        return -ENODEV;

    /* ⭐ Init mutex */
    k_mutex_init(&a320_i2c_mutex);

    data->dev = dev;

    k_work_init(&data->work, a320_work_cb);

    /* ⭐ Init workqueue */
    k_work_queue_start(&a320_workq, a320_workq_stack, K_THREAD_STACK_SIZEOF(a320_workq_stack),
                       A320_WORKQ_PRIORITY, NULL);

    gpio_pin_configure_dt(&cfg->motion_gpio, GPIO_INPUT);

    gpio_init_callback(&data->motion_cb_data, motion_isr, BIT(cfg->motion_gpio.pin));
    gpio_add_callback(cfg->motion_gpio.port, &data->motion_cb_data);

    gpio_pin_interrupt_configure_dt(&cfg->motion_gpio, GPIO_INT_EDGE_TO_ACTIVE);

    k_work_init_delayable(&data->enable_irq_work, a320_enable_irq_work_cb);
    k_work_schedule(&data->enable_irq_work, K_MSEC(5));

    LOG_INF("A320 Driver Initialized (I2C mutex enabled)");
    return 0;
}

#define A320_DEFINE(inst)                                                                          \
    static struct a320_data a320_data_##inst;                                                      \
    static const struct a320_config a320_config_##inst = {                                         \
        .i2c = I2C_DT_SPEC_INST_GET(inst),                                                         \
        .motion_gpio = {.port = DEVICE_DT_GET(MOTION_GPIO_NODE),                                   \
                        .pin = MOTION_GPIO_PIN,                                                    \
                        .dt_flags = MOTION_GPIO_FLAGS},                                            \
    };                                                                                             \
    DEVICE_DT_INST_DEFINE(inst, a320_init, NULL, &a320_data_##inst, &a320_config_##inst,           \
                          POST_KERNEL, 70, NULL);

DT_INST_FOREACH_STATUS_OKAY(A320_DEFINE);
