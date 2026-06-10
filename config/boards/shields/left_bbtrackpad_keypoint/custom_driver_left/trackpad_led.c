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
#include <zephyr/sys/util.h>

#include <zmk/activity.h>
#include <zmk/backlight.h>
#include <zmk/endpoints.h>

#include "trackpad_led.h"
#include "a320.h"
#include "../../lpm_view/widgets/live_data.h"

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
#define AUTO_OFF_DELAY_MS 5000

#define USB_CONFIRM_MS 650
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
static int64_t next_live_refresh_ms;
static struct keypoint_live_data_snapshot live_snapshot;

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

static uint8_t live_data_level_at(int64_t now_ms) {
    if (!live_snapshot.has_data) {
        return burst_active(now_ms, 60000, 60, 1) ? BRT_MIN : 0;
    }

    if (live_snapshot.stale) {
        return burst_active(now_ms, 30000, 80, 3) ? BRT_WARNING : 0;
    }

    switch (live_snapshot.led_hint) {
    case KEYPOINT_LIVE_DATA_LED_HINT_ERROR:
        return burst_active(now_ms, 1800, 100, 3) ? BRT_MAX : 0;
    case KEYPOINT_LIVE_DATA_LED_HINT_WARNING:
        return burst_active(now_ms, 3000, 100, 2) ? BRT_WARNING : 0;
    case KEYPOINT_LIVE_DATA_LED_HINT_ATTENTION:
        return burst_active(now_ms, 2500, 120, 1) ? BRT_ATTENTION : 0;
    case KEYPOINT_LIVE_DATA_LED_HINT_ACTIVE:
        return burst_active(now_ms, 5000, 80, 1) ? BRT_STATUS : 0;
    case KEYPOINT_LIVE_DATA_LED_HINT_NONE:
        break;
    }

    switch (live_snapshot.icon) {
    case KEYPOINT_LIVE_DATA_ICON_CLAUDE:
        return burst_active(now_ms, 9000, 80, 1) ? BRT_STATUS : 0;
    case KEYPOINT_LIVE_DATA_ICON_CODEX:
        return burst_active(now_ms, 9000, 70, 2) ? BRT_STATUS : 0;
    case KEYPOINT_LIVE_DATA_ICON_WARN:
        return burst_active(now_ms, 4000, 100, 2) ? BRT_WARNING : 0;
    default:
        return 0;
    }
}

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

static void refresh_live_snapshot_if_due(int64_t now_ms) {
    if (now_ms < next_live_refresh_ms) {
        return;
    }

    live_snapshot = keypoint_live_data_snapshot_get();
    next_live_refresh_ms = now_ms + LIVE_REFRESH_MS;
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
    refresh_live_snapshot_if_due(now_ms);

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
    next_live_refresh_ms = 0;
    live_snapshot = keypoint_live_data_snapshot_get();

    if (selected_transport == ZMK_TRANSPORT_USB) {
        usb_confirm_start_ms = k_uptime_get();
    }

    set_led_brightness(0);

    k_work_init_delayable(&polling_work, polling_work_handler);
    k_work_reschedule(&polling_work, K_NO_WAIT);
    return 0;
}

SYS_INIT(indicator_tp_init, APPLICATION, CONFIG_APPLICATION_INIT_PRIORITY);
