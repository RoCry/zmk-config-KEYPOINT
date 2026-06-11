/*
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#define KEYPOINT_LIVE_DATA_PREFIX "KP3|"
#define KEYPOINT_LIVE_DATA_ICON_MAX 8
#define KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT 6
#define KEYPOINT_LIVE_DATA_LINE_MAX 9
#define KEYPOINT_LIVE_DATA_STALE_MS 360000
#define KEYPOINT_LIVE_DATA_GENERATION_FIELD_MAX 2
#define KEYPOINT_LIVE_DATA_PAGE_MAX 8
#define KEYPOINT_LIVE_DATA_PAGE_FIELD_MAX 1 /* PAGE_MAX <= 9 -> single digit */
#define KEYPOINT_LIVE_DATA_LED_HINT_FIELD_MAX 1
#define KEYPOINT_LIVE_DATA_FRAME_MAX                                                               \
    ((sizeof(KEYPOINT_LIVE_DATA_PREFIX) - 1) +                                                     \
     (KEYPOINT_LIVE_DATA_GENERATION_FIELD_MAX + 1) +                                               \
     ((KEYPOINT_LIVE_DATA_PAGE_FIELD_MAX + 1) * 2) +                                               \
     (KEYPOINT_LIVE_DATA_LED_HINT_FIELD_MAX + 1) +                                                 \
     KEYPOINT_LIVE_DATA_ICON_MAX +                                                                 \
     (KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT * KEYPOINT_LIVE_DATA_LINE_MAX) +                          \
     KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT)

enum keypoint_live_data_icon {
    KEYPOINT_LIVE_DATA_ICON_NONE,
    KEYPOINT_LIVE_DATA_ICON_SUN,
    KEYPOINT_LIVE_DATA_ICON_CLOUD,
    KEYPOINT_LIVE_DATA_ICON_RAIN,
    KEYPOINT_LIVE_DATA_ICON_TEMP,
    KEYPOINT_LIVE_DATA_ICON_WARN,
    KEYPOINT_LIVE_DATA_ICON_CODE,
    KEYPOINT_LIVE_DATA_ICON_TIME,
    KEYPOINT_LIVE_DATA_ICON_CODEX,
    KEYPOINT_LIVE_DATA_ICON_CLAUDE,
};

enum keypoint_live_data_led_hint {
    KEYPOINT_LIVE_DATA_LED_HINT_NONE,
    KEYPOINT_LIVE_DATA_LED_HINT_ACTIVE,
    KEYPOINT_LIVE_DATA_LED_HINT_ATTENTION,
    KEYPOINT_LIVE_DATA_LED_HINT_WARNING,
    KEYPOINT_LIVE_DATA_LED_HINT_ERROR,
};

struct keypoint_live_data_snapshot {
    enum keypoint_live_data_icon icon;
    enum keypoint_live_data_led_hint led_hint;
    char lines[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1];
    bool has_data;
    bool stale;
    uint8_t generation;
    uint8_t view_index;  /* 0-based index of the page being shown */
    uint8_t total_pages; /* current deck size (1 when empty/NO DATA) */
};

int keypoint_live_data_parse(const uint8_t *data, uint16_t len, uint8_t *generation,
                             uint8_t *idx, uint8_t *total, enum keypoint_live_data_icon *icon,
                             enum keypoint_live_data_led_hint *led_hint,
                             char out[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT]
                                     [KEYPOINT_LIVE_DATA_LINE_MAX + 1]);
struct keypoint_live_data_snapshot keypoint_live_data_snapshot_get(void);
void keypoint_live_data_refresh_displays(void);
