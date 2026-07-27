/*
 * Copyright (c) 2023 ZitaoTech
 *
 * SPDX-License-Identifier: MIT
 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/led.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/util.h>

#include <zmk/activity.h>
#include <zmk/backlight.h>
#include <zmk/endpoints.h>

#include "trackpad_led.h"
#include "a320.h"
#include "live_data.h"

LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

BUILD_ASSERT(DT_HAS_CHOSEN(zmk_trackpad_led),
             "CONFIG_ZMK_TRACKPAD_LED enabled but no zmk,trackpad_led chosen node found");

static const struct device *const led_dev = DEVICE_DT_GET(DT_CHOSEN(zmk_trackpad_led));

#define CHILD_COUNT(...) +1
#define DT_NUM_CHILD(node_id) (DT_FOREACH_CHILD(node_id, CHILD_COUNT))
#define INDICATOR_LED_NUM_LEDS (DT_NUM_CHILD(DT_CHOSEN(zmk_trackpad_led)))

#define BRT_MIN 10
#define BRT_MAX 100
#define BRT_STATUS 35
#define BRT_ATTENTION 75
#define BRT_WARNING 90

#define POLLING_INTERVAL_MS 20
#define LIVE_REFRESH_MS 250
#define AUTO_OFF_DELAY_MS 1000

#define USB_CONFIRM_MS 650
#define LIVE_CONFIRM_MS 500
#define PULSE_GAP_MS 140

static struct k_work_delayable polling_work;

static bool touch_active;
static bool keyboard_active;
static enum zmk_transport selected_transport;

/* Trackpad speed still follows the user's backlight-derived setting. Status
 * LED patterns use separate brightness constants and never mutate this value. */
static uint8_t last_valid_brt = BRT_MAX;
static uint8_t last_backlight_brt;
static uint8_t current_led_brt;

static int64_t preview_until_ms;
static int64_t usb_confirm_start_ms = -USB_CONFIRM_MS;

static void set_led_brightness(uint8_t level) {
    level = MIN(level, BRT_MAX);
    if (current_led_brt == level) {
        return;
    }

    if (!device_is_ready(led_dev)) {
        LOG_ERR("LED device not ready");
        return;
    }

    for (int i = 0; i < INDICATOR_LED_NUM_LEDS; i++) {
        int err = led_set_brightness(led_dev, i, level);
        if (err < 0) {
            LOG_ERR("Failed to set LED[%d] brightness: %d", i, err);
        }
    }

    current_led_brt = level;
}

static bool burst_active(int64_t elapsed_ms, int32_t period_ms, int32_t duration_ms,
                         uint8_t count) {
    int64_t phase = elapsed_ms % period_ms;

    for (uint8_t i = 0; i < count; i++) {
        int32_t start_ms = i * (duration_ms + PULSE_GAP_MS);
        if (phase >= start_ms && phase < start_ms + duration_ms) {
            return true;
        }
    }

    return false;
}

/*
 * Live data. LiveData publishes; this module subscribes and renders. All it
 * knows is attention level -> blink pattern: no icons, no staleness, no
 * generation arithmetic. Adding an icon never touches this file.
 *
 * CONFIG_KEYPOINT_LIVE_DATA (see lpm_view/Kconfig.defconfig) states once
 * whether live data is compiled in at all; this is the file's only #if.
 */
#if IS_ENABLED(CONFIG_KEYPOINT_LIVE_DATA)

static enum keypoint_live_data_attention live_attention;
static int64_t next_live_refresh_ms;
static int64_t live_confirm_start_ms = -LIVE_CONFIRM_MS;
/* Raised on the display work queue, consumed by the polling handler, so the
 * int64 timestamps above stay single-threaded. */
static atomic_t live_confirm_pending;

static void live_data_changed(enum keypoint_live_data_change change) {
    if (change == KEYPOINT_LIVE_DATA_CHANGE_GENERATION) {
        atomic_set(&live_confirm_pending, 1);
    }
}

static void live_data_poll(int64_t now_ms) {
    if (atomic_cas(&live_confirm_pending, 1, 0)) {
        live_confirm_start_ms = now_ms;
        next_live_refresh_ms = now_ms; /* blink the new deck's level, not the old one */
    }

    if (now_ms < next_live_refresh_ms) {
        return;
    }

    live_attention = keypoint_live_data_snapshot_get().attention;
    next_live_refresh_ms = now_ms + LIVE_REFRESH_MS;
}

static uint8_t live_data_level_at(int64_t now_ms) {
    /* A freshly arrived deck confirms itself before the steady pattern resumes. */
    int64_t confirm_elapsed_ms = now_ms - live_confirm_start_ms;
    if (confirm_elapsed_ms >= 0 && confirm_elapsed_ms < LIVE_CONFIRM_MS) {
        return burst_active(confirm_elapsed_ms, LIVE_CONFIRM_MS, 70, 1) ? BRT_ATTENTION : 0;
    }

    switch (live_attention) {
    case KEYPOINT_LIVE_DATA_ATTENTION_ERROR:
        return burst_active(now_ms, 1800, 100, 3) ? BRT_MAX : 0;
    case KEYPOINT_LIVE_DATA_ATTENTION_STALE:
        return burst_active(now_ms, 30000, 80, 3) ? BRT_WARNING : 0;
    case KEYPOINT_LIVE_DATA_ATTENTION_WARNING:
        return burst_active(now_ms, 3000, 100, 2) ? BRT_WARNING : 0;
    case KEYPOINT_LIVE_DATA_ATTENTION_CAUTION:
        return burst_active(now_ms, 4000, 100, 2) ? BRT_WARNING : 0;
    case KEYPOINT_LIVE_DATA_ATTENTION_ATTENTION:
        return burst_active(now_ms, 2500, 120, 1) ? BRT_ATTENTION : 0;
    case KEYPOINT_LIVE_DATA_ATTENTION_ACTIVE:
        return burst_active(now_ms, 5000, 80, 1) ? BRT_STATUS : 0;
    case KEYPOINT_LIVE_DATA_ATTENTION_HEARTBEAT_SINGLE:
        return burst_active(now_ms, 9000, 80, 1) ? BRT_STATUS : 0;
    case KEYPOINT_LIVE_DATA_ATTENTION_HEARTBEAT_DOUBLE:
        return burst_active(now_ms, 9000, 70, 2) ? BRT_STATUS : 0;
    case KEYPOINT_LIVE_DATA_ATTENTION_NO_DATA:
        return burst_active(now_ms, 60000, 60, 1) ? BRT_MIN : 0;
    case KEYPOINT_LIVE_DATA_ATTENTION_IDLE:
        break;
    }

    return 0;
}

static void live_data_init(void) {
    next_live_refresh_ms = 0;
    live_confirm_start_ms = -LIVE_CONFIRM_MS;
    atomic_clear(&live_confirm_pending);
    live_attention = keypoint_live_data_snapshot_get().attention;
    keypoint_live_data_subscribe(live_data_changed);
}

#else

static void live_data_poll(int64_t now_ms) { ARG_UNUSED(now_ms); }

static uint8_t live_data_level_at(int64_t now_ms) {
    ARG_UNUSED(now_ms);
    return 0;
}

static void live_data_init(void) {}

#endif /* CONFIG_KEYPOINT_LIVE_DATA */

static uint8_t led_level_at(int64_t now_ms) {
    if (touch_active || now_ms < preview_until_ms) {
        return last_valid_brt;
    }

    int64_t usb_elapsed_ms = now_ms - usb_confirm_start_ms;
    if (usb_elapsed_ms >= 0 && usb_elapsed_ms < USB_CONFIRM_MS) {
        return burst_active(usb_elapsed_ms, USB_CONFIRM_MS, 90, 2) ? BRT_MAX : 0;
    }

    return live_data_level_at(now_ms);
}

static void update_transport(enum zmk_transport transport, int64_t now_ms) {
    if (transport == selected_transport) {
        return;
    }

    selected_transport = transport;
    if (transport == ZMK_TRANSPORT_USB) {
        usb_confirm_start_ms = now_ms;
        LOG_INF("Trackpad LED USB confirm pulse");
    }
}

static void update_activity(bool current_active, uint8_t current_brt) {
    if (current_active == keyboard_active) {
        return;
    }

    keyboard_active = current_active;
    if (keyboard_active) {
        last_backlight_brt = current_brt;
    }
}

static void update_touch(bool current_touch, uint8_t current_brt, int64_t now_ms) {
    if (current_touch == touch_active) {
        return;
    }

    touch_active = current_touch;
    if (touch_active) {
        if (keyboard_active) {
            last_valid_brt = MAX(BRT_MIN, current_brt);
        }
        preview_until_ms = 0;
    } else {
        preview_until_ms = now_ms + AUTO_OFF_DELAY_MS;
    }
}

static void update_backlight(uint8_t current_brt, int64_t now_ms) {
    if (touch_active || !keyboard_active || current_brt == last_backlight_brt) {
        return;
    }

    last_backlight_brt = current_brt;
    if (current_brt > 0) {
        last_valid_brt = MAX(BRT_MIN, current_brt);
        preview_until_ms = now_ms + AUTO_OFF_DELAY_MS;
    } else {
        preview_until_ms = 0;
    }
}

static void polling_work_handler(struct k_work *work) {
    ARG_UNUSED(work);

    int64_t now_ms = k_uptime_get();
    enum zmk_transport transport = zmk_endpoints_selected().transport;
    uint8_t current_brt = zmk_backlight_get_brt();
    bool current_active = (zmk_activity_get_state() == ZMK_ACTIVITY_ACTIVE);
    bool current_touch = tp_is_touched();

    update_transport(transport, now_ms);
    update_activity(current_active, current_brt);
    update_touch(current_touch, current_brt, now_ms);
    update_backlight(current_brt, now_ms);
    live_data_poll(now_ms);

    set_led_brightness(led_level_at(now_ms));

    k_work_reschedule(&polling_work, K_MSEC(POLLING_INTERVAL_MS));
}

uint8_t indicator_tp_get_last_valid_brightness(void) { return last_valid_brt; }

static int indicator_tp_init(void) {
    if (!device_is_ready(led_dev)) {
        LOG_ERR("LED indicator_tp device not ready");
        return -ENODEV;
    }

    last_backlight_brt = zmk_backlight_get_brt();
    if (last_backlight_brt > 0) {
        last_valid_brt = MAX(BRT_MIN, last_backlight_brt);
    }

    current_led_brt = UINT8_MAX;
    selected_transport = zmk_endpoints_selected().transport;
    touch_active = false;
    keyboard_active = false;
    preview_until_ms = 0;

    live_data_init();

    if (selected_transport == ZMK_TRANSPORT_USB) {
        usb_confirm_start_ms = k_uptime_get();
    }

    set_led_brightness(0);

    k_work_init_delayable(&polling_work, polling_work_handler);
    k_work_reschedule(&polling_work, K_NO_WAIT);
    return 0;
}

SYS_INIT(indicator_tp_init, APPLICATION, CONFIG_APPLICATION_INIT_PRIORITY);
