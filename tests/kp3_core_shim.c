/*
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 *
 * ctypes shim for the pure KP3 core.
 *
 * The core's interface speaks C structs and enums. Rather than hand-mirror
 * their layout in Python -- the twin-maintenance problem these tests exist to
 * kill -- this shim flattens every call to primitives, so the Python side
 * needs no layout knowledge at all. Line buffers are flat arrays whose
 * dimensions Python takes from kp3, which derives them from the same header.
 *
 * Test fixture only; never compiled into firmware.
 */

#include <stdint.h>
#include <string.h>

#include "live_data_core.h"

#define LINE_COUNT KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT
#define LINE_STRIDE (KEYPOINT_LIVE_DATA_LINE_MAX + 1)

size_t kp3_shim_deck_size(void) { return sizeof(struct keypoint_live_data_deck); }

size_t kp3_shim_line_count(void) { return LINE_COUNT; }

size_t kp3_shim_line_stride(void) { return LINE_STRIDE; }

void kp3_shim_deck_reset(void *deck) { memset(deck, 0, sizeof(struct keypoint_live_data_deck)); }

/* Parse only. Returns the firmware's own return code (0 = accepted). */
int kp3_shim_parse(const uint8_t *data, uint16_t len, int *generation, int *idx, int *total,
                   int *icon, int *led_hint, char *lines_out) {
    uint8_t generation_val = 0, idx_val = 0, total_val = 0;
    enum keypoint_live_data_icon icon_val = KEYPOINT_LIVE_DATA_ICON_NONE;
    enum keypoint_live_data_led_hint led_val = KEYPOINT_LIVE_DATA_LED_HINT_NONE;
    char lines[LINE_COUNT][LINE_STRIDE];

    const int ret = keypoint_live_data_parse(data, len, &generation_val, &idx_val, &total_val,
                                             &icon_val, &led_val, lines);
    if (ret < 0) {
        return ret;
    }

    *generation = generation_val;
    *idx = idx_val;
    *total = total_val;
    *icon = (int)icon_val;
    *led_hint = (int)led_val;
    memcpy(lines_out, lines, sizeof(lines));
    return 0;
}

/* Parse a frame and stage it into `deck`, exactly as the GATT write handler
 * does. Returns the parse code; `*committed` reports whether the page
 * completed its generation and swapped the deck in. */
int kp3_shim_write(void *deck, const uint8_t *data, uint16_t len, int64_t now_ms, int *committed) {
    uint8_t generation = 0, idx = 0, total = 0;
    enum keypoint_live_data_icon icon = KEYPOINT_LIVE_DATA_ICON_NONE;
    enum keypoint_live_data_led_hint led_hint = KEYPOINT_LIVE_DATA_LED_HINT_NONE;
    char lines[LINE_COUNT][LINE_STRIDE];

    const int ret =
        keypoint_live_data_parse(data, len, &generation, &idx, &total, &icon, &led_hint, lines);
    if (ret < 0) {
        *committed = 0;
        return ret;
    }

    *committed = keypoint_live_data_core_store((struct keypoint_live_data_deck *)deck, generation,
                                               idx, total, icon, led_hint, lines, now_ms)
                     ? 1
                     : 0;
    return 0;
}

void kp3_shim_snapshot(const void *deck, int64_t now_ms, int *icon, int *led_hint, int *attention,
                       int *has_data, int *stale, int *generation, int *view_index,
                       int *total_pages, char *lines_out) {
    const struct keypoint_live_data_snapshot snapshot = keypoint_live_data_core_snapshot(
        (const struct keypoint_live_data_deck *)deck, now_ms);

    *icon = (int)snapshot.icon;
    *led_hint = (int)snapshot.led_hint;
    *attention = (int)snapshot.attention;
    *has_data = snapshot.has_data ? 1 : 0;
    *stale = snapshot.stale ? 1 : 0;
    *generation = snapshot.generation;
    *view_index = snapshot.view_index;
    *total_pages = snapshot.total_pages;
    memcpy(lines_out, snapshot.lines, sizeof(snapshot.lines));
}

int kp3_shim_page_advance(void *deck, int delta) {
    return keypoint_live_data_core_page_advance((struct keypoint_live_data_deck *)deck, delta) ? 1
                                                                                              : 0;
}
