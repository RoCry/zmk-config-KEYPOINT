/* Compact, unboxed keyboard controls on the shared black surface. */
#include "status_info_panel.h"
#include "status_layout.h"
#include "theme.h"
#include <stdio.h>
#include <string.h>

static void mark(lv_obj_t *canvas, int x, int y, int w, int h, enum keypoint_color color) {
    lv_draw_rect_dsc_t dsc;
    init_rect_dsc(&dsc, keypoint_color(color));
    lv_canvas_draw_rect(canvas, x, y, w, h, &dsc);
}

void draw_profile_grid(lv_obj_t *canvas, const struct status_state *state) {
    for (int i = 0; i < KEYPOINT_STATUS_PROFILE_COUNT; ++i) {
        const int x = i * 18, y = KEYPOINT_PROFILE_ROW_Y;
        const bool active = i == state->active_profile_index;
        lv_draw_label_dsc_t label;
        init_label_dsc(&label, keypoint_color(active ? KP_CYAN : KP_WHITE),
                       &lv_font_unscii_8, LV_TEXT_ALIGN_LEFT);
        char number[2] = {(char)('1' + i), '\0'};
        lv_canvas_draw_text(canvas, x + 2, y, 8, &label, number);
        if (state->profile_connected[i]) {
            mark(canvas, x + 12, y + 3, 3, 3, KP_GREEN);
        } else if (state->profile_bonded[i]) {
            mark(canvas, x + 12, y + 4, 3, 1, KP_BLUE);
        } else {
            mark(canvas, x + 12, y + 4, 3, 1, KP_CYAN);
            mark(canvas, x + 13, y + 3, 1, 3, KP_CYAN);
        }
        if (active) mark(canvas, x + 2, y + 11, 13, 1, KP_CYAN);
    }
}

const char *trim_spaces(const char *label, char *buffer, size_t buffer_size) {
    if (label == NULL || buffer_size == 0) return "";
    while (*label == ' ') ++label;
    const char *end = label + strlen(label);
    while (end > label && end[-1] == ' ') --end;
    size_t len = end - label;
    if (len >= buffer_size) len = buffer_size - 1;
    memcpy(buffer, label, len);
    buffer[len] = '\0';
    return buffer;
}

void draw_layer_info(lv_obj_t *canvas, const struct status_state *state) {
    char fallback[16];
    const char *value = "BASE";
    if (state->layer_index) {
        value = trim_spaces(state->layer_label, fallback, sizeof(fallback));
        if (!value[0]) {
            snprintf(fallback, sizeof(fallback), "L%u", state->layer_index);
            value = fallback;
        }
    }
    lv_draw_label_dsc_t label;
    init_label_dsc(&label, keypoint_color(state->layer_index ? KP_MAGENTA : KP_WHITE),
                   &lv_font_unscii_8, LV_TEXT_ALIGN_CENTER);
    lv_canvas_draw_text(canvas, KEYPOINT_LAYER_TEXT_X, KEYPOINT_LAYER_TEXT_Y,
                       KEYPOINT_LAYER_TEXT_WIDTH, &label, value);
}
