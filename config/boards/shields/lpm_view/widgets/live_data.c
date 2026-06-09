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

static char latest_lines[KEYPOINT_LIVE_DATA_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1];
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

int keypoint_live_data_parse(const uint8_t *data, uint16_t len,
                             char out[KEYPOINT_LIVE_DATA_LINE_COUNT]
                                     [KEYPOINT_LIVE_DATA_LINE_MAX + 1]) {
    if (data == NULL || out == NULL || len > KEYPOINT_LIVE_DATA_FRAME_MAX) {
        return -EINVAL;
    }

    const size_t prefix_len = sizeof(KEYPOINT_LIVE_DATA_PREFIX) - 1;
    if (len < prefix_len || memcmp(data, KEYPOINT_LIVE_DATA_PREFIX, prefix_len) != 0) {
        return -EINVAL;
    }

    memset(out, 0, KEYPOINT_LIVE_DATA_LINE_COUNT * (KEYPOINT_LIVE_DATA_LINE_MAX + 1));

    size_t line = 0;
    size_t column = 0;

    for (size_t i = prefix_len; i < len; i++) {
        const uint8_t ch = data[i];

        if (ch == '|') {
            if (line >= KEYPOINT_LIVE_DATA_LINE_COUNT - 1) {
                return -EINVAL;
            }

            line++;
            column = 0;
            continue;
        }

        if (!is_printable_ascii(ch) || column >= KEYPOINT_LIVE_DATA_LINE_MAX) {
            return -EINVAL;
        }

        out[line][column++] = (char)ch;
    }

    if (line != KEYPOINT_LIVE_DATA_LINE_COUNT - 1) {
        return -EINVAL;
    }

    return 0;
}

struct keypoint_live_data_snapshot keypoint_live_data_snapshot_get(void) {
    struct keypoint_live_data_snapshot snapshot = {};

    k_mutex_lock(&live_data_mutex, K_FOREVER);

    snapshot.has_data = latest_has_data;
    const int64_t age_ms = k_uptime_get() - latest_update_ms;
    snapshot.stale = latest_has_data && age_ms >= KEYPOINT_LIVE_DATA_STALE_MS;

    if (latest_has_data) {
        for (int i = 0; i < KEYPOINT_LIVE_DATA_LINE_COUNT; i++) {
            strncpy(snapshot.lines[i], latest_lines[i], KEYPOINT_LIVE_DATA_LINE_MAX);
            snapshot.lines[i][KEYPOINT_LIVE_DATA_LINE_MAX] = '\0';
        }
    }

    k_mutex_unlock(&live_data_mutex);

    if (!snapshot.has_data) {
        strcpy(snapshot.lines[0], "NO DATA");
        strcpy(snapshot.lines[1], "WAITING");
    } else if (snapshot.stale) {
        char previous[KEYPOINT_LIVE_DATA_LINE_COUNT - 1][KEYPOINT_LIVE_DATA_LINE_MAX + 1] = {};

        for (int i = 0; i < KEYPOINT_LIVE_DATA_LINE_COUNT - 1; i++) {
            strncpy(previous[i], snapshot.lines[i], KEYPOINT_LIVE_DATA_LINE_MAX);
        }

        memset(snapshot.lines, 0, sizeof(snapshot.lines));
        strcpy(snapshot.lines[0], "STALE");
        for (int i = 0; i < KEYPOINT_LIVE_DATA_LINE_COUNT - 1; i++) {
            strncpy(snapshot.lines[i + 1], previous[i], KEYPOINT_LIVE_DATA_LINE_MAX);
        }
    }

    return snapshot;
}

static void store_live_data(char lines[KEYPOINT_LIVE_DATA_LINE_COUNT]
                                      [KEYPOINT_LIVE_DATA_LINE_MAX + 1]) {
    k_mutex_lock(&live_data_mutex, K_FOREVER);

    for (int i = 0; i < KEYPOINT_LIVE_DATA_LINE_COUNT; i++) {
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

    char parsed[KEYPOINT_LIVE_DATA_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1];
    int ret = keypoint_live_data_parse((const uint8_t *)buf, len, parsed);
    if (ret < 0) {
        LOG_WRN("Rejected live-data payload len=%u", len);
        return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
    }

    store_live_data(parsed);
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
