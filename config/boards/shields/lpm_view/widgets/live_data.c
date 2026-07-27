/*
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 */

#include <stddef.h>

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
#include "live_data_core.h"

LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

// Service UUID: f5d40000-6d2f-4f4b-9b2a-2f4a8e8c0001
// Characteristic UUID: f5d40001-6d2f-4f4b-9b2a-2f4a8e8c0001
#define KEYPOINT_LIVE_DATA_BT_UUID(num) BT_UUID_128_ENCODE(num, 0x6d2f, 0x4f4b, 0x9b2a, 0x2f4a8e8c0001)
#define KEYPOINT_LIVE_DATA_BT_SERVICE_UUID KEYPOINT_LIVE_DATA_BT_UUID(0xf5d40000)
#define KEYPOINT_LIVE_DATA_BT_CHRC_UUID KEYPOINT_LIVE_DATA_BT_UUID(0xf5d40001)

/* Page navigation: left key (pos 32) = NEXT, right key (pos 33) = PREV. Defer
 * only on the FN layer, where these keys are &msc SCRL_*; page on every other
 * layer so the 700ms POINTING temp-layer and held LOWER/SYMBOL don't dead-zone. */
#define KEYPOINT_LIVE_PAGE_NEXT_POS 32
#define KEYPOINT_LIVE_PAGE_PREV_POS 33
#define KEYPOINT_FN_LAYER 3 /* matches FN in config/keypoint.keymap */

/* Consumers of the snapshot, at most this many. The seam is one-way: this
 * module never names them, so the bound is the only thing it knows. */
#define KEYPOINT_LIVE_DATA_LISTENER_MAX 4

K_MUTEX_DEFINE(live_data_mutex);

/* Deck state lives here; live_data_core.c owns the logic that mutates it and is
 * not thread-aware, so every call below is made under live_data_mutex. */
static struct keypoint_live_data_deck live_deck;

/* Bumped when a commit installs a *different* generation than the one already
 * on the glass -- a new deck rather than an in-place page update. Written under
 * live_data_mutex; the notify work below turns it into the change edge. */
static uint8_t deck_epoch;

static keypoint_live_data_listener_t listeners[KEYPOINT_LIVE_DATA_LISTENER_MAX];
static uint8_t listener_count;

void keypoint_live_data_subscribe(keypoint_live_data_listener_t listener) {
    __ASSERT_NO_MSG(listener != NULL);
    __ASSERT(listener_count < ARRAY_SIZE(listeners),
             "live-data listener table full; raise KEYPOINT_LIVE_DATA_LISTENER_MAX");

    if (listener_count >= ARRAY_SIZE(listeners)) {
        LOG_ERR("Live-data listener dropped: table full");
        return;
    }

    listeners[listener_count++] = listener;
}

static void live_data_notify_work_cb(struct k_work *work) {
    ARG_UNUSED(work);

    /* Only this callback reads or writes notified_epoch, and it only ever runs
     * on the display work queue, so the edge needs no lock. */
    static uint8_t notified_epoch;
    const uint8_t epoch = deck_epoch;
    const enum keypoint_live_data_change change = (epoch != notified_epoch)
                                                      ? KEYPOINT_LIVE_DATA_CHANGE_GENERATION
                                                      : KEYPOINT_LIVE_DATA_CHANGE_REFRESH;
    notified_epoch = epoch;

    for (uint8_t i = 0; i < listener_count; i++) {
        listeners[i](change);
    }
}

static K_WORK_DEFINE(live_data_notify_work, live_data_notify_work_cb);

/* Subscribers run on the display work queue, never on the BLE RX thread. */
static void notify_live_data_changed(void) {
    if (zmk_display_is_initialized()) {
        k_work_submit_to_queue(zmk_display_work_q(), &live_data_notify_work);
    }
}

static void live_data_stale_work_cb(struct k_work *work) {
    ARG_UNUSED(work);
    notify_live_data_changed();
}

static K_WORK_DELAYABLE_DEFINE(live_data_stale_work, live_data_stale_work_cb);

struct keypoint_live_data_snapshot keypoint_live_data_snapshot_get(void) {
    k_mutex_lock(&live_data_mutex, K_FOREVER);
    struct keypoint_live_data_snapshot snapshot =
        keypoint_live_data_core_snapshot(&live_deck, k_uptime_get());
    k_mutex_unlock(&live_data_mutex);

    return snapshot;
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

    k_mutex_lock(&live_data_mutex, K_FOREVER);
    const uint8_t previous_generation = live_deck.generation;
    const bool had_deck = live_deck.total > 0;
    const bool committed = keypoint_live_data_core_store(&live_deck, generation, idx, total, icon,
                                                         led_hint, parsed, k_uptime_get());
    if (committed && (!had_deck || live_deck.generation != previous_generation)) {
        deck_epoch++;
    }
    k_mutex_unlock(&live_data_mutex);

    if (!committed) {
        return len;
    }

    k_work_reschedule(&live_data_stale_work, K_MSEC(KEYPOINT_LIVE_DATA_STALE_MS + 1));
    notify_live_data_changed();

    return len;
}

static void live_data_page_advance(int delta) {
    k_mutex_lock(&live_data_mutex, K_FOREVER);
    const bool changed = keypoint_live_data_core_page_advance(&live_deck, delta);
    k_mutex_unlock(&live_data_mutex);

    if (changed) {
        notify_live_data_changed();
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
