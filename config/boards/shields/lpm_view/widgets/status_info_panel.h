/*
 *
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 *
 */

#pragma once

#include <string.h>

#include <lvgl.h>
#include <zephyr/kernel.h>

#include "status_layout.h"
#include "util.h"

static void draw_rect_outline(lv_obj_t *canvas, lv_coord_t x, lv_coord_t y, lv_coord_t width,
                              lv_coord_t height, const lv_draw_rect_dsc_t *rect_dsc) {
    lv_canvas_draw_rect(canvas, x, y, width, 1, rect_dsc);
    lv_canvas_draw_rect(canvas, x, y + height - 1, width, 1, rect_dsc);
    lv_canvas_draw_rect(canvas, x, y, 1, height, rect_dsc);
    lv_canvas_draw_rect(canvas, x + width - 1, y, 1, height, rect_dsc);
}

static void draw_plus_marker(lv_obj_t *canvas, lv_coord_t x, lv_coord_t y, lv_coord_t size,
                             const lv_draw_rect_dsc_t *rect_dsc) {
    const lv_coord_t center = size / 2;
    lv_canvas_draw_rect(canvas, x + center, y, 1, size, rect_dsc);
    lv_canvas_draw_rect(canvas, x, y + center, size, 1, rect_dsc);
}

static void draw_profile_open_slot(lv_obj_t *canvas, lv_coord_t x, lv_coord_t y,
                                   const lv_draw_rect_dsc_t *rect_dsc) {
    const lv_coord_t right = x + KEYPOINT_PROFILE_SLOT_WIDTH - 1;
    const lv_coord_t bottom = y + KEYPOINT_PROFILE_SLOT_HEIGHT - 1;
    const lv_coord_t corner = KEYPOINT_PROFILE_CORNER_SIZE;

    lv_canvas_draw_rect(canvas, x, y, corner, 1, rect_dsc);
    lv_canvas_draw_rect(canvas, x, y, 1, corner, rect_dsc);
    lv_canvas_draw_rect(canvas, right - corner + 1, y, corner, 1, rect_dsc);
    lv_canvas_draw_rect(canvas, right, y, 1, corner, rect_dsc);
    lv_canvas_draw_rect(canvas, x, bottom, corner, 1, rect_dsc);
    lv_canvas_draw_rect(canvas, x, bottom - corner + 1, 1, corner, rect_dsc);
    lv_canvas_draw_rect(canvas, right - corner + 1, bottom, corner, 1, rect_dsc);
    lv_canvas_draw_rect(canvas, right, bottom - corner + 1, 1, corner, rect_dsc);
}

static void draw_profile_slot(lv_obj_t *canvas, const struct status_state *state, uint8_t index,
                              lv_coord_t x, lv_coord_t y,
                              const lv_draw_rect_dsc_t *foreground_rect_dsc,
                              const lv_draw_rect_dsc_t *background_rect_dsc,
                              const lv_draw_label_dsc_t *foreground_label_dsc,
                              const lv_draw_label_dsc_t *background_label_dsc) {
    const bool active = index == state->active_profile_index;
    const bool connected = state->profile_connected[index];
    const bool bonded = state->profile_bonded[index];
    const lv_draw_rect_dsc_t *status_rect_dsc = active ? background_rect_dsc : foreground_rect_dsc;
    char label[2];

    if (active) {
        lv_canvas_draw_rect(canvas, x, y, KEYPOINT_PROFILE_SLOT_WIDTH,
                            KEYPOINT_PROFILE_SLOT_HEIGHT, foreground_rect_dsc);
    } else if (bonded) {
        draw_rect_outline(canvas, x, y, KEYPOINT_PROFILE_SLOT_WIDTH,
                          KEYPOINT_PROFILE_SLOT_HEIGHT, foreground_rect_dsc);
    } else {
        draw_profile_open_slot(canvas, x, y, foreground_rect_dsc);
    }

    snprintk(label, sizeof(label), "%u", index + 1);
    lv_canvas_draw_text(canvas, x + 1, y + 1, 9, active ? background_label_dsc : foreground_label_dsc,
                        label);

    const lv_coord_t mark_x = x + KEYPOINT_PROFILE_MARK_X_OFFSET;
    const lv_coord_t mark_y = y + KEYPOINT_PROFILE_MARK_Y_OFFSET;
    if (connected) {
        lv_canvas_draw_rect(canvas, mark_x, mark_y, KEYPOINT_PROFILE_MARK_SIZE,
                            KEYPOINT_PROFILE_MARK_SIZE, status_rect_dsc);
    } else if (bonded) {
        draw_rect_outline(canvas, mark_x, mark_y, KEYPOINT_PROFILE_MARK_SIZE,
                          KEYPOINT_PROFILE_MARK_SIZE, status_rect_dsc);
    } else {
        draw_plus_marker(canvas, mark_x, mark_y, KEYPOINT_PROFILE_MARK_SIZE, status_rect_dsc);
    }
}

static void draw_profile_grid(lv_obj_t *canvas, const struct status_state *state,
                              const lv_draw_rect_dsc_t *foreground_rect_dsc,
                              const lv_draw_rect_dsc_t *background_rect_dsc,
                              const lv_draw_label_dsc_t *foreground_label_dsc,
                              const lv_draw_label_dsc_t *background_label_dsc) {
    /* Four 15px slots spread flush across the 72px glass (0..71) with even 4px
     * gaps: the first hugs the left frame, the last (57+15-1=71) the right. */
    static const lv_coord_t slot_offsets[KEYPOINT_STATUS_PROFILE_COUNT][2] = {
        {0, KEYPOINT_PROFILE_ROW_Y},
        {19, KEYPOINT_PROFILE_ROW_Y},
        {38, KEYPOINT_PROFILE_ROW_Y},
        {57, KEYPOINT_PROFILE_ROW_Y},
    };

    for (uint8_t i = 0; i < KEYPOINT_STATUS_PROFILE_COUNT; i++) {
        draw_profile_slot(canvas, state, i, slot_offsets[i][0], slot_offsets[i][1],
                          foreground_rect_dsc, background_rect_dsc, foreground_label_dsc,
                          background_label_dsc);
    }
}

static const char *trim_layer_label(const char *label, char *buffer, size_t buffer_size) {
    if (label == NULL || buffer_size == 0) {
        return "";
    }

    while (*label == ' ') {
        label++;
    }

    const char *end = label + strlen(label);
    while (end > label && end[-1] == ' ') {
        end--;
    }

    size_t len = end - label;
    if (len >= buffer_size) {
        len = buffer_size - 1;
    }

    memcpy(buffer, label, len);
    buffer[len] = '\0';
    return buffer;
}

static const char *layer_info_text(const struct status_state *state, char *fallback,
                                   size_t fallback_size) {
    if (state->layer_index == 0) {
        return "BASE";
    }

    if (state->layer_label != NULL) {
        const char *label = trim_layer_label(state->layer_label, fallback, fallback_size);
        if (label[0] != '\0') {
            return label;
        }
    }

    snprintk(fallback, fallback_size, "L%u", state->layer_index);
    return fallback;
}

static void draw_layer_info(lv_obj_t *canvas, const struct status_state *state,
                            const lv_draw_label_dsc_t *label_dsc) {
    char fallback[16] = {};
    const char *label = layer_info_text(state, fallback, sizeof(fallback));

    lv_canvas_draw_text(canvas, KEYPOINT_LAYER_TEXT_X, KEYPOINT_LAYER_TEXT_Y,
                        KEYPOINT_LAYER_TEXT_WIDTH, label_dsc, label);
}
