/*
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#define KEYPOINT_LIVE_DATA_PREFIX "KP2|"
#define KEYPOINT_LIVE_DATA_ICON_MAX 8
#define KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT 6
#define KEYPOINT_LIVE_DATA_LINE_MAX 8
#define KEYPOINT_LIVE_DATA_STALE_MS 360000
#define KEYPOINT_LIVE_DATA_FRAME_MAX                                                               \
    ((sizeof(KEYPOINT_LIVE_DATA_PREFIX) - 1) +                                                     \
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

struct keypoint_live_data_snapshot {
    enum keypoint_live_data_icon icon;
    char lines[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1];
    bool has_data;
    bool stale;
};

int keypoint_live_data_parse(const uint8_t *data, uint16_t len,
                             enum keypoint_live_data_icon *icon,
                             char out[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT]
                                     [KEYPOINT_LIVE_DATA_LINE_MAX + 1]);
struct keypoint_live_data_snapshot keypoint_live_data_snapshot_get(void);
void keypoint_live_data_refresh_displays(void);
