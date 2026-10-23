/*
 *
 * Copyright (c) 2023 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 *
 */

#pragma once

#include <lvgl.h>
#include <zephyr/kernel.h>
#include "util.h"

/* The one status-widget interface. Both halves link a status screen against
 * it; CMake compiles exactly one implementation -- status.c on the central,
 * peripheral_status.c on the peripheral -- so every translation unit in an
 * image has to agree on this layout.
 *
 * Central: two RGB565 canvases. Peripheral: one RGB565+alpha overlay above
 * fullscreen artwork. Conditional storage follows the implementation selected
 * by CMake; neither half allocates buffers used only by the other. */
struct zmk_widget_status {
    sys_snode_t node;
    lv_obj_t *obj;
#if IS_ENABLED(CONFIG_KEYPOINT_LIVE_DATA)
    lv_color_t cbuf[CANVAS_SIZE * CANVAS_SIZE];
    lv_color_t cbuf2[CANVAS_SIZE * CANVAS_SIZE];
#else
    uint8_t cbuf[LV_IMG_BUF_SIZE_TRUE_COLOR_ALPHA(CANVAS_SIZE, CANVAS_SIZE)];
#endif
    struct status_state state;
};

int zmk_widget_status_init(struct zmk_widget_status *widget, lv_obj_t *parent);
lv_obj_t *zmk_widget_status_obj(struct zmk_widget_status *widget);
