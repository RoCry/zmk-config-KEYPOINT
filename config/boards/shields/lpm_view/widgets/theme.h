#pragma once

#include <lvgl.h>
#include "live_data.h"

/* RGB bit order matches the panel, but UI uses names rather than wire bits. */
enum keypoint_color {
    KP_BLACK, KP_BLUE, KP_GREEN, KP_CYAN, KP_RED, KP_MAGENTA, KP_YELLOW, KP_WHITE
};

lv_color_t keypoint_color(enum keypoint_color color);
enum keypoint_color keypoint_card_accent(enum keypoint_live_data_icon icon);
enum keypoint_color keypoint_row_color(enum keypoint_live_data_row_role role,
                                      enum keypoint_color accent);
enum keypoint_color keypoint_health_color(const struct keypoint_live_data_snapshot *snapshot);
