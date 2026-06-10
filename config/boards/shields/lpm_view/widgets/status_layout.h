/*
 *
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 *
 */

#pragma once

/* The live-data icon sits in the top status row, between the battery
 * (ends x=32) and the endpoint symbol (starts x>=52). */
#define KEYPOINT_LIVE_ICON_SIZE 8
#define KEYPOINT_LIVE_ICON_SCALE 1
#define KEYPOINT_LIVE_ICON_X 38
#define KEYPOINT_LIVE_ICON_Y 4
/* Top lines sit low (text y=26) and extra lines start at the very top of the
 * middle canvas, so the glass shows an even rhythm: ~10px below the status
 * row, 4px between lines, ~10px across the canvas seam. */
#define KEYPOINT_LIVE_TEXT_X 3
#define KEYPOINT_LIVE_TEXT_Y 26
#define KEYPOINT_LIVE_TEXT_WIDTH 67
#define KEYPOINT_LIVE_TEXT_LINE_HEIGHT 12
/* Page indicator ("n/N") for a multi-card deck: right-aligned in the free band
 * between the status row and the first live-data line. Shown only when the deck
 * has >1 page. Reuses KEYPOINT_LIVE_TEXT_X / _WIDTH for right alignment. */
#define KEYPOINT_LIVE_PAGE_Y 14

/* Live-data lines 1..KEYPOINT_LIVE_TOP_LINE_COUNT render on the top canvas;
 * the remaining lines and the health strip render on the middle (profile)
 * canvas, above the profile row. Canvas rows >= 66 never reach the glass
 * (middle-canvas overlap + rotate_canvas clipping), so keep content above. */
#define KEYPOINT_LIVE_TOP_LINE_COUNT 3
#define KEYPOINT_LIVE_EXTRA_TEXT_Y 0
#define KEYPOINT_LIVE_HEALTH_X 2
#define KEYPOINT_LIVE_HEALTH_Y 38
#define KEYPOINT_LIVE_HEALTH_WIDTH 68
#define KEYPOINT_LIVE_HEALTH_HEIGHT 2

#define KEYPOINT_PROFILE_SLOT_WIDTH 15
#define KEYPOINT_PROFILE_SLOT_HEIGHT 14
#define KEYPOINT_PROFILE_CORNER_SIZE 4
#define KEYPOINT_PROFILE_MARK_SIZE 3
#define KEYPOINT_PROFILE_MARK_X_OFFSET 10
#define KEYPOINT_PROFILE_MARK_Y_OFFSET 9
#define KEYPOINT_PROFILE_ROW_Y 43

#define KEYPOINT_LAYER_TEXT_X 2
#define KEYPOINT_LAYER_TEXT_Y 61
#define KEYPOINT_LAYER_TEXT_WIDTH 68

static const char icon_sun[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00100100", "00011000", "10111101", "01111110",
    "01111110", "10111101", "00011000", "00100100",
};

static const char icon_cloud[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00000000", "00111000", "01111100", "11111110",
    "11111110", "01111100", "00000000", "00000000",
};

static const char icon_rain[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00111000", "01111100", "11111110", "01111100",
    "00000000", "01001000", "10010000", "00100100",
};

static const char icon_temp[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00110000", "01001000", "01001000", "01001000",
    "01001000", "10000100", "10000100", "01111000",
};

static const char icon_warn[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00010000", "00111000", "00111000", "01101100",
    "01101100", "11111110", "11101110", "11111110",
};

static const char icon_code[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "10000010", "01000100", "00101000", "00010000",
    "00101000", "01000100", "10000010", "00010000",
};

static const char icon_time[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00111100", "01000010", "10010001", "10010001",
    "10011101", "10000001", "01000010", "00111100",
};

static const char icon_codex[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00111100", "01011010", "10100101", "10111101",
    "10111101", "10100101", "01011010", "00111100",
};

static const char icon_claude[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00010000", "00010000", "01010100", "00111000",
    "11111110", "00111000", "01010100", "00010000",
};
