/*
 *
 * Copyright (c) 2023 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 *
 */

#include <string.h>
#include "util.h"
#include "theme.h"

LV_IMG_DECLARE(bolt);

void rotate_canvas(lv_obj_t *canvas, lv_color_t cbuf[]) {
    /* Exact quarter turn in place. LVGL 8.3's general transform both resamples
     * right-angle rotations and dereferences a refreshing display outside a
     * refresh callback. Integer permutation avoids both and needs no scratch. */
    for (int first = 0; first < CANVAS_SIZE / 2; ++first) {
        int last = CANVAS_SIZE - 1 - first;
        for (int i = first; i < last; ++i) {
            int opposite = last - (i - first);
            lv_color_t top = cbuf[first * CANVAS_SIZE + i];
            cbuf[first * CANVAS_SIZE + i] = cbuf[i * CANVAS_SIZE + last];
            cbuf[i * CANVAS_SIZE + last] = cbuf[last * CANVAS_SIZE + opposite];
            cbuf[last * CANVAS_SIZE + opposite] = cbuf[opposite * CANVAS_SIZE + first];
            cbuf[opposite * CANVAS_SIZE + first] = top;
        }
    }
    lv_obj_invalidate(canvas);
}

void draw_battery(lv_obj_t *canvas, const struct status_state *state) {
    lv_draw_rect_dsc_t rect_black_dsc;
    init_rect_dsc(&rect_black_dsc, LVGL_BACKGROUND);
    lv_draw_rect_dsc_t rect_white_dsc;
    init_rect_dsc(&rect_white_dsc, LVGL_FOREGROUND);

    lv_canvas_draw_rect(canvas, 0, 2, 29, 12, &rect_white_dsc);
    lv_canvas_draw_rect(canvas, 1, 3, 27, 10, &rect_black_dsc);
    lv_draw_rect_dsc_t fill;
    enum keypoint_color color = state->charging ? KP_CYAN :
        state->battery <= 10 ? KP_RED : state->battery <= 20 ? KP_YELLOW : KP_GREEN;
    init_rect_dsc(&fill, keypoint_color(color));
    lv_canvas_draw_rect(canvas, 2, 4, (state->battery + 2) / 4, 8, &fill);
    lv_canvas_draw_rect(canvas, 30, 5, 3, 6, &rect_white_dsc);
    lv_canvas_draw_rect(canvas, 31, 6, 1, 4, &rect_black_dsc);

    if (state->charging) {
        lv_draw_img_dsc_t img_dsc;
        lv_draw_img_dsc_init(&img_dsc);
        lv_canvas_draw_img(canvas, 9, -1, &bolt, &img_dsc);
    }
}

void init_label_dsc(lv_draw_label_dsc_t *label_dsc, lv_color_t color, const lv_font_t *font,
                    lv_text_align_t align) {
    lv_draw_label_dsc_init(label_dsc);
    label_dsc->color = color;
    label_dsc->font = font;
    label_dsc->align = align;
}

void init_rect_dsc(lv_draw_rect_dsc_t *rect_dsc, lv_color_t bg_color) {
    lv_draw_rect_dsc_init(rect_dsc);
    rect_dsc->bg_color = bg_color;
}

void init_line_dsc(lv_draw_line_dsc_t *line_dsc, lv_color_t color, uint8_t width) {
    lv_draw_line_dsc_init(line_dsc);
    line_dsc->color = color;
    line_dsc->width = width;
}

void init_arc_dsc(lv_draw_arc_dsc_t *arc_dsc, lv_color_t color, uint8_t width) {
    lv_draw_arc_dsc_init(arc_dsc);
    arc_dsc->color = color;
    arc_dsc->width = width;
}
