/*
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 */

#include <errno.h>
#include <stddef.h>
#include <string.h>

#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include <zmk/display.h>

#include "live_data.h"

LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

// Service UUID: f5d40000-6d2f-4f4b-9b2a-2f4a8e8c0001
// Characteristic UUID: f5d40001-6d2f-4f4b-9b2a-2f4a8e8c0001
#define KEYPOINT_LIVE_DATA_BT_UUID(num) BT_UUID_128_ENCODE(num, 0x6d2f, 0x4f4b, 0x9b2a, 0x2f4a8e8c0001)
#define KEYPOINT_LIVE_DATA_BT_SERVICE_UUID KEYPOINT_LIVE_DATA_BT_UUID(0xf5d40000)
#define KEYPOINT_LIVE_DATA_BT_CHRC_UUID KEYPOINT_LIVE_DATA_BT_UUID(0xf5d40001)

K_MUTEX_DEFINE(live_data_mutex);

static enum keypoint_live_data_icon latest_icon = KEYPOINT_LIVE_DATA_ICON_NONE;
static char latest_lines[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1];
static bool latest_has_data;
static int64_t latest_update_ms;

static void live_data_display_work_cb(struct k_work *work) {
    ARG_UNUSED(work);
    keypoint_live_data_refresh_displays();
}

static K_WORK_DEFINE(live_data_display_work, live_data_display_work_cb);

static void submit_live_data_display_refresh(void) {
    if (zmk_display_is_initialized()) {
        k_work_submit_to_queue(zmk_display_work_q(), &live_data_display_work);
    }
}

static void live_data_stale_work_cb(struct k_work *work) {
    ARG_UNUSED(work);
    submit_live_data_display_refresh();
}

static K_WORK_DELAYABLE_DEFINE(live_data_stale_work, live_data_stale_work_cb);

static bool is_printable_ascii(uint8_t ch) { return ch >= 0x20 && ch <= 0x7e; }

static int icon_from_field(const char *field, enum keypoint_live_data_icon *icon) {
    if (strcmp(field, "NONE") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_NONE;
    } else if (strcmp(field, "SUN") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_SUN;
    } else if (strcmp(field, "CLOUD") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_CLOUD;
    } else if (strcmp(field, "RAIN") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_RAIN;
    } else if (strcmp(field, "TEMP") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_TEMP;
    } else if (strcmp(field, "WARN") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_WARN;
    } else if (strcmp(field, "CODE") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_CODE;
    } else if (strcmp(field, "TIME") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_TIME;
    } else if (strcmp(field, "CODEX") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_CODEX;
    } else if (strcmp(field, "CLAUDE") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_CLAUDE;
    } else {
        return -EINVAL;
    }

    return 0;
}

int keypoint_live_data_parse(const uint8_t *data, uint16_t len,
                             enum keypoint_live_data_icon *icon,
                             char out[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT]
                                     [KEYPOINT_LIVE_DATA_LINE_MAX + 1]) {
    if (data == NULL || icon == NULL || out == NULL || len > KEYPOINT_LIVE_DATA_FRAME_MAX) {
        return -EINVAL;
    }

    const size_t prefix_len = sizeof(KEYPOINT_LIVE_DATA_PREFIX) - 1;
    if (len < prefix_len || memcmp(data, KEYPOINT_LIVE_DATA_PREFIX, prefix_len) != 0) {
        return -EINVAL;
    }

    char icon_field[KEYPOINT_LIVE_DATA_ICON_MAX + 1] = {};
    memset(out, 0, KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT * (KEYPOINT_LIVE_DATA_LINE_MAX + 1));

    size_t field = 0;
    size_t column = 0;

    for (size_t i = prefix_len; i < len; i++) {
        const uint8_t ch = data[i];

        if (ch == '|') {
            if (field >= KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT) {
                return -EINVAL;
            }

            field++;
            column = 0;
            continue;
        }

        const size_t field_max =
            (field == 0) ? KEYPOINT_LIVE_DATA_ICON_MAX : KEYPOINT_LIVE_DATA_LINE_MAX;
        if (!is_printable_ascii(ch) || column >= field_max) {
            return -EINVAL;
        }

        if (field == 0) {
            icon_field[column++] = (char)ch;
        } else {
            out[field - 1][column++] = (char)ch;
        }
    }

    if (field != KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT) {
        return -EINVAL;
    }

    return icon_from_field(icon_field, icon);
}

struct keypoint_live_data_snapshot keypoint_live_data_snapshot_get(void) {
    struct keypoint_live_data_snapshot snapshot = {};

    k_mutex_lock(&live_data_mutex, K_FOREVER);

    snapshot.icon = latest_icon;
    snapshot.has_data = latest_has_data;
    const int64_t age_ms = k_uptime_get() - latest_update_ms;
    snapshot.stale = latest_has_data && age_ms >= KEYPOINT_LIVE_DATA_STALE_MS;

    if (latest_has_data) {
        for (int i = 0; i < KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT; i++) {
            strncpy(snapshot.lines[i], latest_lines[i], KEYPOINT_LIVE_DATA_LINE_MAX);
            snapshot.lines[i][KEYPOINT_LIVE_DATA_LINE_MAX] = '\0';
        }
    }

    k_mutex_unlock(&live_data_mutex);

    if (!snapshot.has_data) {
        snapshot.icon = KEYPOINT_LIVE_DATA_ICON_WARN;
        strcpy(snapshot.lines[0], "NO DATA");
        strcpy(snapshot.lines[1], "WAITING");
    }

    return snapshot;
}

static void store_live_data(enum keypoint_live_data_icon icon,
                            char lines[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT]
                                      [KEYPOINT_LIVE_DATA_LINE_MAX + 1]) {
    k_mutex_lock(&live_data_mutex, K_FOREVER);

    latest_icon = icon;
    for (int i = 0; i < KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT; i++) {
        strncpy(latest_lines[i], lines[i], KEYPOINT_LIVE_DATA_LINE_MAX);
        latest_lines[i][KEYPOINT_LIVE_DATA_LINE_MAX] = '\0';
    }
    latest_has_data = true;
    latest_update_ms = k_uptime_get();

    k_mutex_unlock(&live_data_mutex);
}

static ssize_t write_live_data(struct bt_conn *conn, const struct bt_gatt_attr *attr,
                               const void *buf, uint16_t len, uint16_t offset, uint8_t flags) {
    ARG_UNUSED(conn);
    ARG_UNUSED(attr);
    ARG_UNUSED(flags);

    if (offset != 0) {
        return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
    }

    enum keypoint_live_data_icon icon;
    char parsed[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1];
    int ret = keypoint_live_data_parse((const uint8_t *)buf, len, &icon, parsed);
    if (ret < 0) {
        LOG_WRN("Rejected live-data payload len=%u", len);
        return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
    }

    store_live_data(icon, parsed);
    k_work_reschedule(&live_data_stale_work, K_MSEC(KEYPOINT_LIVE_DATA_STALE_MS + 1));

    submit_live_data_display_refresh();

    return len;
}

BT_GATT_SERVICE_DEFINE(
    keypoint_live_data_svc,
    BT_GATT_PRIMARY_SERVICE(BT_UUID_DECLARE_128(KEYPOINT_LIVE_DATA_BT_SERVICE_UUID)),
    BT_GATT_CHARACTERISTIC(BT_UUID_DECLARE_128(KEYPOINT_LIVE_DATA_BT_CHRC_UUID),
                           BT_GATT_CHRC_WRITE | BT_GATT_CHRC_WRITE_WITHOUT_RESP,
                           BT_GATT_PERM_WRITE_ENCRYPT, NULL, write_live_data, NULL), );
