/*
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "live_data.h"

/*
 * Pure KP3 deck logic: frame parse, deck staging, page wrap, staleness.
 *
 * No Zephyr, no LVGL, no globals, no clock of its own. The caller owns the
 * deck state, supplies `now_ms`, and does its own locking. That is what makes
 * this file compilable — and testable — on a host.
 */

/* One page of a deck as held in firmware, plus the arrival time it is aged from. */
struct keypoint_live_data_card {
    enum keypoint_live_data_icon icon;
    enum keypoint_live_data_led_hint led_hint;
    char lines[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1];
    bool has_data;
    int64_t update_ms;
};

/* The committed deck plus the staging area for the generation being received.
 * Zero-initialise before first use. */
struct keypoint_live_data_deck {
    struct keypoint_live_data_card cards[KEYPOINT_LIVE_DATA_PAGE_MAX];
    struct keypoint_live_data_card pending_cards[KEYPOINT_LIVE_DATA_PAGE_MAX];
    uint8_t total;      /* committed deck size; 0 until the first commit */
    uint8_t view_index; /* page currently shown */
    uint8_t generation;
    uint8_t pending_generation;
    uint8_t pending_total;
    uint8_t pending_mask;
    bool pending_active;
};

/* Stage one page of `generation`. A generation/total mismatch restarts staging.
 * Returns true when this page completed the generation and the deck was swapped
 * in — the only moment the display needs refreshing.
 *
 * Precondition: idx < total <= KEYPOINT_LIVE_DATA_PAGE_MAX, as enforced by
 * keypoint_live_data_parse(). */
bool keypoint_live_data_core_store(struct keypoint_live_data_deck *deck, uint8_t generation,
                                   uint8_t idx, uint8_t total, enum keypoint_live_data_icon icon,
                                   enum keypoint_live_data_led_hint led_hint,
                                   char lines[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT]
                                             [KEYPOINT_LIVE_DATA_LINE_MAX + 1],
                                   int64_t now_ms);

/* Read model for the page in view: the NO DATA fallback, the staleness verdict
 * at `now_ms`, and the attention level those fold into. */
struct keypoint_live_data_snapshot
keypoint_live_data_core_snapshot(const struct keypoint_live_data_deck *deck, int64_t now_ms);

/* Wrap the view index by `delta`. Returns true when the page in view changed. */
bool keypoint_live_data_core_page_advance(struct keypoint_live_data_deck *deck, int delta);
