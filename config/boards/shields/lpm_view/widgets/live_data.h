/*
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#define KEYPOINT_LIVE_DATA_PREFIX "KP1|"
#define KEYPOINT_LIVE_DATA_LINE_COUNT 4
#define KEYPOINT_LIVE_DATA_LINE_MAX 8
#define KEYPOINT_LIVE_DATA_STALE_MS 120000
#define KEYPOINT_LIVE_DATA_FRAME_MAX                                                               \
    ((sizeof(KEYPOINT_LIVE_DATA_PREFIX) - 1) +                                                     \
     (KEYPOINT_LIVE_DATA_LINE_COUNT * KEYPOINT_LIVE_DATA_LINE_MAX) +                               \
     (KEYPOINT_LIVE_DATA_LINE_COUNT - 1))

struct keypoint_live_data_snapshot {
    char lines[KEYPOINT_LIVE_DATA_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1];
    bool has_data;
    bool stale;
};

int keypoint_live_data_parse(const uint8_t *data, uint16_t len,
                             char out[KEYPOINT_LIVE_DATA_LINE_COUNT]
                                     [KEYPOINT_LIVE_DATA_LINE_MAX + 1]);
struct keypoint_live_data_snapshot keypoint_live_data_snapshot_get(void);
void keypoint_live_data_refresh_displays(void);
