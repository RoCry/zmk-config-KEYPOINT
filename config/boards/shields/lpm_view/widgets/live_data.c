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
#include <zephyr/sys/util.h>

#include <zmk/display.h>
#include <zmk/keymap.h>
#include <zmk/event_manager.h>
#include <zmk/events/position_state_changed.h>

#include "live_data.h"

LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

// Service UUID: f5d40000-6d2f-4f4b-9b2a-2f4a8e8c0001
// Characteristic UUID: f5d40001-6d2f-4f4b-9b2a-2f4a8e8c0001
#define KEYPOINT_LIVE_DATA_BT_UUID(num) BT_UUID_128_ENCODE(num, 0x6d2f, 0x4f4b, 0x9b2a, 0x2f4a8e8c0001)
#define KEYPOINT_LIVE_DATA_BT_SERVICE_UUID KEYPOINT_LIVE_DATA_BT_UUID(0xf5d40000)
#define KEYPOINT_LIVE_DATA_BT_CHRC_UUID KEYPOINT_LIVE_DATA_BT_UUID(0xf5d40001)

K_MUTEX_DEFINE(live_data_mutex);

/* Page navigation: left key (pos 32) = NEXT, right key (pos 33) = PREV. Defer
 * only on the FN layer, where these keys are &msc SCRL_*; page on every other
 * layer so the 700ms POINTING temp-layer and held LOWER/SYMBOL don't dead-zone. */
#define KEYPOINT_LIVE_PAGE_NEXT_POS 32
#define KEYPOINT_LIVE_PAGE_PREV_POS 33
#define KEYPOINT_FN_LAYER 3 /* matches FN in config/keypoint.keymap */

struct live_data_slot {
    enum keypoint_live_data_icon icon;
    enum keypoint_live_data_led_hint led_hint;
    char lines[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1];
    bool has_data;
    int64_t update_ms;
};

static struct live_data_slot deck[KEYPOINT_LIVE_DATA_PAGE_MAX];
static struct live_data_slot pending_deck[KEYPOINT_LIVE_DATA_PAGE_MAX];
static uint8_t deck_total; /* number of valid pages; 0 until first frame */
static uint8_t view_index; /* page currently shown */
static uint8_t deck_generation;
static uint8_t pending_generation;
static uint8_t pending_total;
static uint8_t pending_mask;
static bool pending_active;

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

static int hex_nibble(uint8_t ch) {
    if (ch >= '0' && ch <= '9') {
        return ch - '0';
    }
    if (ch >= 'A' && ch <= 'F') {
        return 10 + ch - 'A';
    }
    return -EINVAL;
}

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

static int led_hint_from_field(const char *field, enum keypoint_live_data_led_hint *led_hint) {
    if (strcmp(field, "0") == 0) {
        *led_hint = KEYPOINT_LIVE_DATA_LED_HINT_NONE;
    } else if (strcmp(field, "1") == 0) {
        *led_hint = KEYPOINT_LIVE_DATA_LED_HINT_ACTIVE;
    } else if (strcmp(field, "2") == 0) {
        *led_hint = KEYPOINT_LIVE_DATA_LED_HINT_ATTENTION;
    } else if (strcmp(field, "3") == 0) {
        *led_hint = KEYPOINT_LIVE_DATA_LED_HINT_WARNING;
    } else if (strcmp(field, "4") == 0) {
        *led_hint = KEYPOINT_LIVE_DATA_LED_HINT_ERROR;
    } else {
        return -EINVAL;
    }

    return 0;
}

static uint8_t received_mask_for_total(uint8_t total) { return (uint8_t)((1U << total) - 1U); }

int keypoint_live_data_parse(const uint8_t *data, uint16_t len, uint8_t *generation,
                             uint8_t *idx, uint8_t *total, enum keypoint_live_data_icon *icon,
                             enum keypoint_live_data_led_hint *led_hint,
                             char out[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT]
                                     [KEYPOINT_LIVE_DATA_LINE_MAX + 1]) {
    if (data == NULL || generation == NULL || idx == NULL || total == NULL || icon == NULL ||
        led_hint == NULL || out == NULL || len > KEYPOINT_LIVE_DATA_FRAME_MAX) {
        return -EINVAL;
    }

    const size_t prefix_len = sizeof(KEYPOINT_LIVE_DATA_PREFIX) - 1;
    if (len < prefix_len || memcmp(data, KEYPOINT_LIVE_DATA_PREFIX, prefix_len) != 0) {
        return -EINVAL;
    }

    uint16_t generation_val = 0;
    char icon_field[KEYPOINT_LIVE_DATA_ICON_MAX + 1] = {};
    char led_hint_field[KEYPOINT_LIVE_DATA_LED_HINT_FIELD_MAX + 1] = {};
    memset(out, 0, KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT * (KEYPOINT_LIVE_DATA_LINE_MAX + 1));

    /* Field layout after the prefix:
     * 0=GEN, 1=IDX, 2=TOTAL, 3=ICON, 4=LED, 5..10=lines. */
    uint16_t idx_val = 0, total_val = 0;
    size_t field = 0;
    size_t column = 0;

    for (size_t i = prefix_len; i < len; i++) {
        const uint8_t ch = data[i];

        if (ch == '|') {
            if (field >= 4 + KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT) {
                return -EINVAL;
            }
            if (field == 0 && column != KEYPOINT_LIVE_DATA_GENERATION_FIELD_MAX) {
                return -EINVAL; /* GEN is exactly two uppercase hex digits */
            }
            if ((field == 1 || field == 2) && column == 0) {
                return -EINVAL; /* empty IDX/TOTAL field */
            }
            if (field == 4 && column != KEYPOINT_LIVE_DATA_LED_HINT_FIELD_MAX) {
                return -EINVAL; /* LED hint is exactly one digit */
            }
            field++;
            column = 0;
            continue;
        }

        if (field == 0) {
            int nibble = hex_nibble(ch);
            if (nibble < 0 || column >= KEYPOINT_LIVE_DATA_GENERATION_FIELD_MAX) {
                return -EINVAL;
            }
            generation_val = (uint16_t)((generation_val << 4) | (uint8_t)nibble);
            column++;
            continue;
        }

        if (field == 1 || field == 2) {
            if (ch < '0' || ch > '9' || column >= KEYPOINT_LIVE_DATA_PAGE_FIELD_MAX) {
                return -EINVAL;
            }
            uint16_t *acc = (field == 1) ? &idx_val : &total_val;
            *acc = (uint16_t)(*acc * 10 + (ch - '0'));
            column++;
            continue;
        }

        const size_t field_max = (field == 3)   ? KEYPOINT_LIVE_DATA_ICON_MAX
                                 : (field == 4) ? KEYPOINT_LIVE_DATA_LED_HINT_FIELD_MAX
                                                : KEYPOINT_LIVE_DATA_LINE_MAX;
        if (!is_printable_ascii(ch) || column >= field_max) {
            return -EINVAL;
        }
        if (field == 3) {
            icon_field[column++] = (char)ch;
        } else if (field == 4) {
            led_hint_field[column++] = (char)ch;
        } else {
            out[field - 5][column++] = (char)ch;
        }
    }

    if (field != 4 + KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT) {
        return -EINVAL;
    }
    if (total_val < 1 || total_val > KEYPOINT_LIVE_DATA_PAGE_MAX || idx_val >= total_val) {
        return -EINVAL;
    }

    *generation = (uint8_t)generation_val;
    *idx = (uint8_t)idx_val;
    *total = (uint8_t)total_val;
    int ret = icon_from_field(icon_field, icon);
    if (ret < 0) {
        return ret;
    }
    return led_hint_from_field(led_hint_field, led_hint);
}

struct keypoint_live_data_snapshot keypoint_live_data_snapshot_get(void) {
    struct keypoint_live_data_snapshot snapshot = {};

    k_mutex_lock(&live_data_mutex, K_FOREVER);

    snapshot.total_pages = deck_total > 0 ? deck_total : 1;
    snapshot.view_index = view_index;
    snapshot.generation = deck_generation;
    const struct live_data_slot *slot = (deck_total > 0) ? &deck[view_index] : NULL;

    if (slot != NULL && slot->has_data) {
        snapshot.icon = slot->icon;
        snapshot.led_hint = slot->led_hint;
        snapshot.has_data = true;
        const int64_t age_ms = k_uptime_get() - slot->update_ms;
        snapshot.stale = age_ms >= KEYPOINT_LIVE_DATA_STALE_MS;
        for (int i = 0; i < KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT; i++) {
            strncpy(snapshot.lines[i], slot->lines[i], KEYPOINT_LIVE_DATA_LINE_MAX);
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

static bool store_live_data(uint8_t generation, uint8_t idx, uint8_t total,
                            enum keypoint_live_data_icon icon,
                            enum keypoint_live_data_led_hint led_hint,
                            char lines[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT]
                                      [KEYPOINT_LIVE_DATA_LINE_MAX + 1]) {
    bool committed = false;

    k_mutex_lock(&live_data_mutex, K_FOREVER);

    if (!pending_active || generation != pending_generation || total != pending_total) {
        memset(pending_deck, 0, sizeof(pending_deck));
        pending_generation = generation;
        pending_total = total;
        pending_mask = 0;
        pending_active = true;
    }

    struct live_data_slot *slot = &pending_deck[idx];
    slot->icon = icon;
    slot->led_hint = led_hint;
    for (int i = 0; i < KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT; i++) {
        strncpy(slot->lines[i], lines[i], KEYPOINT_LIVE_DATA_LINE_MAX);
        slot->lines[i][KEYPOINT_LIVE_DATA_LINE_MAX] = '\0';
    }
    slot->has_data = true;
    slot->update_ms = k_uptime_get();
    pending_mask |= BIT(idx);

    if (pending_mask == received_mask_for_total(pending_total)) {
        memcpy(deck, pending_deck, sizeof(deck));
        deck_generation = pending_generation;
        deck_total = pending_total;
        pending_active = false;
        pending_mask = 0;

        if (view_index >= deck_total) {
            view_index = deck_total - 1;
        }

        committed = true;
    }

    k_mutex_unlock(&live_data_mutex);

    return committed;
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
    enum keypoint_live_data_led_hint led_hint;
    uint8_t generation, idx, total;
    char parsed[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1];
    int ret = keypoint_live_data_parse((const uint8_t *)buf, len, &generation, &idx, &total,
                                       &icon, &led_hint, parsed);
    if (ret < 0) {
        LOG_WRN("Rejected live-data payload len=%u", len);
        return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
    }

    bool committed = store_live_data(generation, idx, total, icon, led_hint, parsed);
    if (!committed) {
        return len;
    }

    k_work_reschedule(&live_data_stale_work, K_MSEC(KEYPOINT_LIVE_DATA_STALE_MS + 1));
    submit_live_data_display_refresh();

    return len;
}

static void live_data_page_advance(int delta) {
    bool changed = false;

    k_mutex_lock(&live_data_mutex, K_FOREVER);
    if (deck_total > 1) {
        view_index = (uint8_t)((view_index + deck_total + delta) % deck_total);
        changed = true;
    }
    k_mutex_unlock(&live_data_mutex);

    if (changed) {
        submit_live_data_display_refresh();
    }
}

static int live_data_page_key_listener(const zmk_event_t *eh) {
    const struct zmk_position_state_changed *ev = as_zmk_position_state_changed(eh);
    if (ev == NULL || !ev->state) {
        return ZMK_EV_EVENT_BUBBLE; /* act on press only */
    }
    if (ev->position != KEYPOINT_LIVE_PAGE_NEXT_POS && ev->position != KEYPOINT_LIVE_PAGE_PREV_POS) {
        return ZMK_EV_EVENT_BUBBLE;
    }
    if (zmk_keymap_highest_layer_active() == KEYPOINT_FN_LAYER) {
        return ZMK_EV_EVENT_BUBBLE; /* FN maps these to &msc SCRL_*; defer */
    }

    live_data_page_advance(ev->position == KEYPOINT_LIVE_PAGE_NEXT_POS ? +1 : -1);
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(keypoint_live_data_page_keys, live_data_page_key_listener);
ZMK_SUBSCRIPTION(keypoint_live_data_page_keys, zmk_position_state_changed);

BT_GATT_SERVICE_DEFINE(
    keypoint_live_data_svc,
    BT_GATT_PRIMARY_SERVICE(BT_UUID_DECLARE_128(KEYPOINT_LIVE_DATA_BT_SERVICE_UUID)),
    BT_GATT_CHARACTERISTIC(BT_UUID_DECLARE_128(KEYPOINT_LIVE_DATA_BT_CHRC_UUID),
                           BT_GATT_CHRC_WRITE | BT_GATT_CHRC_WRITE_WITHOUT_RESP,
                           BT_GATT_PERM_WRITE_ENCRYPT, NULL, write_live_data, NULL), );
