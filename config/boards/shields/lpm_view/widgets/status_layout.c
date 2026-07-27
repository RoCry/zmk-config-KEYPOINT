/*
 *
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 *
 */

/* The live-data icon bitmaps. One KEYPOINT_LIVE_ICON_SIZE-long string per row,
 * '1' = ink; status.c maps the KP3 icon enum onto them and draws each set bit
 * as a KEYPOINT_LIVE_ICON_SCALE square. The preview parses these bitmaps out of
 * this file, so the simulator cannot drift from the glass. */

#include "status_layout.h"

const char icon_sun[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00100100", "00011000", "10111101", "01111110",
    "01111110", "10111101", "00011000", "00100100",
};

const char icon_cloud[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00000000", "00111000", "01111100", "11111110",
    "11111110", "01111100", "00000000", "00000000",
};

const char icon_rain[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00111000", "01111100", "11111110", "01111100",
    "00000000", "01001000", "10010000", "00100100",
};

const char icon_temp[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00110000", "01001000", "01001000", "01001000",
    "01001000", "10000100", "10000100", "01111000",
};

const char icon_warn[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00010000", "00111000", "00111000", "01101100",
    "01101100", "11111110", "11101110", "11111110",
};

const char icon_code[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "10000010", "01000100", "00101000", "00010000",
    "00101000", "01000100", "10000010", "00010000",
};

const char icon_time[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00111100", "01000010", "10010001", "10010001",
    "10011101", "10000001", "01000010", "00111100",
};

const char icon_codex[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00111100", "01011010", "10100101", "10111101",
    "10111101", "10100101", "01011010", "00111100",
};

const char icon_claude[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {
    "00010000", "00010000", "01010100", "00111000",
    "11111110", "00111000", "01010100", "00010000",
};
