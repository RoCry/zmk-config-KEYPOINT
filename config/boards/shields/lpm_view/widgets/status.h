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
 * Only the central draws a second (middle) canvas, so its buffer exists only
 * there, selected by the same CONFIG_KEYPOINT_LIVE_DATA the build selects the
 * implementation on. Handing the peripheral the spare buffer just to make the
 * shapes match would cost it CANVAS_SIZE^2 bytes of RAM it never touches. */
struct zmk_widget_status {
    sys_snode_t node;
    lv_obj_t *obj;
    lv_color_t cbuf[CANVAS_SIZE * CANVAS_SIZE];
#if IS_ENABLED(CONFIG_KEYPOINT_LIVE_DATA)
    lv_color_t cbuf2[CANVAS_SIZE * CANVAS_SIZE];
#endif
    struct status_state state;
};

int zmk_widget_status_init(struct zmk_widget_status *widget, lv_obj_t *parent);
lv_obj_t *zmk_widget_status_obj(struct zmk_widget_status *widget);
