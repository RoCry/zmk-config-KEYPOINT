/* Shared by firmware and the native LVGL preview. No events or host policy. */
#include "status_render.h"
#include "status_info_panel.h"
#include "status_layout.h"
#include "theme.h"
#include <string.h>

static void rect(lv_obj_t *canvas, int x, int y, int w, int h, enum keypoint_color color) {
    lv_draw_rect_dsc_t dsc;
    init_rect_dsc(&dsc, keypoint_color(color));
    lv_canvas_draw_rect(canvas, x, y, w, h, &dsc);
}

static void text(lv_obj_t *canvas, int x, int y, int w, const char *value,
                 lv_color_t color, lv_text_align_t align, const lv_font_t *font) {
    lv_draw_label_dsc_t dsc;
    init_label_dsc(&dsc, color, font, align);
    lv_canvas_draw_text(canvas, x, y, w, &dsc, value);
}

static void draw_icon(lv_obj_t *canvas, enum keypoint_live_data_icon icon,
                      enum keypoint_color accent) {
    const char (*rows)[KEYPOINT_LIVE_ICON_SIZE + 1] = NULL;
    switch (icon) {
    case KEYPOINT_LIVE_DATA_ICON_SUN: rows = icon_sun; break;
    case KEYPOINT_LIVE_DATA_ICON_CLOUD: rows = icon_cloud; break;
    case KEYPOINT_LIVE_DATA_ICON_RAIN: rows = icon_rain; break;
    case KEYPOINT_LIVE_DATA_ICON_TEMP: rows = icon_temp; break;
    case KEYPOINT_LIVE_DATA_ICON_WARN: rows = icon_warn; break;
    case KEYPOINT_LIVE_DATA_ICON_CODE: rows = icon_code; break;
    case KEYPOINT_LIVE_DATA_ICON_TIME: rows = icon_time; break;
    case KEYPOINT_LIVE_DATA_ICON_CODEX: rows = icon_codex; break;
    case KEYPOINT_LIVE_DATA_ICON_CLAUDE: rows = icon_claude; break;
    default: return;
    }
    for (int y = 0; y < KEYPOINT_LIVE_ICON_SIZE; ++y) {
        for (int x = 0; x < KEYPOINT_LIVE_ICON_SIZE; ++x) {
            if (rows[y][x] == '1') {
                rect(canvas, KEYPOINT_LIVE_ICON_X + x * KEYPOINT_LIVE_ICON_SCALE,
                     KEYPOINT_LIVE_ICON_Y + y * KEYPOINT_LIVE_ICON_SCALE,
                     KEYPOINT_LIVE_ICON_SCALE, KEYPOINT_LIVE_ICON_SCALE, accent);
            }
        }
    }
}

static void draw_line(lv_obj_t *canvas, int y, const char *line,
                      enum keypoint_live_data_row_role role, enum keypoint_color accent) {
    enum keypoint_color color = keypoint_row_color(role, accent);
    const int x = KEYPOINT_LIVE_TEXT_X, w = KEYPOINT_LIVE_TEXT_WIDTH;
    if (strlen(line) == 5 && line[0] == '[' && line[4] == ']' &&
        line[1] >= '0' && line[1] <= '9' && line[2] >= '0' && line[2] <= '9' &&
        line[3] >= '0' && line[3] <= '9') {
        int pct = (line[1] - '0') * 100 + (line[2] - '0') * 10 + line[3] - '0';
        if (pct <= 100) {
            int by = y + KEYPOINT_LIVE_BAR_MARGIN_Y;
            int h = KEYPOINT_LIVE_BAR_HEIGHT, b = KEYPOINT_LIVE_BAR_BORDER;
            int inner = w - b * 2;
            rect(canvas, x, by, w, h, KP_BLACK);
            rect(canvas, x + b, by + b, inner, h - b * 2, KP_WHITE);
            if (pct) rect(canvas, x + b, by + b, pct * inner / 100, h - b * 2, color);
            return;
        }
    }
    /* Colored text on white is weak on reflective glass. Semantic text rows
     * get a color backing with black/white lettering instead. */
    lv_color_t ink = keypoint_color(KP_BLACK);
    if (line[0] && role != KEYPOINT_LIVE_DATA_ROW_ROLE_NEUTRAL) {
        rect(canvas, x, y, w, 9, color);
        ink = keypoint_on_color(color);
    }
    text(canvas, x, y, w, line, ink, LV_TEXT_ALIGN_RIGHT, &lv_font_unscii_8);
}

static void draw_page_rail(lv_obj_t *canvas, const struct keypoint_live_data_snapshot *s,
                           enum keypoint_color accent) {
    if (s->total_pages <= 1) return;
    int x = KEYPOINT_LIVE_TEXT_X, w = KEYPOINT_LIVE_TEXT_WIDTH;
    int y = KEYPOINT_LIVE_PAGE_Y, h = KEYPOINT_LIVE_PAGE_THUMB_HEIGHT;
    int tx = x + s->view_index * w / s->total_pages;
    int tw = x + (s->view_index + 1) * w / s->total_pages - tx;
    int ty = y - h / 2;
    rect(canvas, x, y, w, 1, KP_BLACK);
    rect(canvas, tx, ty, tw, h, accent);
    rect(canvas, tx, ty, 1, 1, KP_WHITE);
    rect(canvas, tx + tw - 1, ty, 1, 1, KP_WHITE);
    rect(canvas, tx, ty + h - 1, 1, 1, KP_WHITE);
    rect(canvas, tx + tw - 1, ty + h - 1, 1, 1, KP_WHITE);
}

void keypoint_draw_top(lv_obj_t *canvas, const struct status_state *state,
                       const struct keypoint_live_data_snapshot *s) {
    lv_canvas_fill_bg(canvas, keypoint_color(KP_WHITE), LV_OPA_COVER);
    draw_battery(canvas, state);
    const char *symbol = state->usb ? LV_SYMBOL_USB :
        !state->active_profile_bonded ? LV_SYMBOL_SETTINGS :
        state->active_profile_connected ? LV_SYMBOL_WIFI : LV_SYMBOL_CLOSE;
    enum keypoint_color connection = state->usb ? KP_BLUE :
        !state->active_profile_bonded ? KP_CYAN :
        state->active_profile_connected ? KP_GREEN : KP_RED;
    text(canvas, 0, 0, CANVAS_SIZE, symbol, keypoint_color(connection),
         LV_TEXT_ALIGN_RIGHT, &lv_font_montserrat_16);

    if (!s->has_data) {
        for (int i = 0; i < KEYPOINT_LIVE_TOP_LINE_COUNT; ++i)
            text(canvas, KEYPOINT_LIVE_TEXT_X, KEYPOINT_LIVE_TIP_Y + i * KEYPOINT_LIVE_TEXT_LINE_HEIGHT,
                 KEYPOINT_LIVE_TEXT_WIDTH, s->lines[i], keypoint_color(KP_BLUE),
                 LV_TEXT_ALIGN_CENTER, &lv_font_unscii_8);
        return;
    }
    enum keypoint_color accent = keypoint_card_accent(s->icon);
    draw_icon(canvas, s->icon, accent);
    char title[KEYPOINT_LIVE_DATA_LINE_MAX + 1];
    trim_spaces(s->lines[0], title, sizeof(title));
    if (title[0]) {
        enum keypoint_color title_color = keypoint_row_color(s->row_roles[0], accent);
        rect(canvas, KEYPOINT_LIVE_TEXT_X, KEYPOINT_LIVE_TITLE_BAR_Y,
             KEYPOINT_LIVE_TEXT_WIDTH, KEYPOINT_LIVE_TITLE_BAR_HEIGHT, title_color);
        text(canvas, KEYPOINT_LIVE_TEXT_X, KEYPOINT_LIVE_TEXT_Y, KEYPOINT_LIVE_TEXT_WIDTH,
             title, keypoint_on_color(title_color), LV_TEXT_ALIGN_CENTER, &lv_font_unscii_8);
    }
    for (int i = 1; i < KEYPOINT_LIVE_TOP_LINE_COUNT; ++i)
        draw_line(canvas, KEYPOINT_LIVE_TEXT_Y + i * KEYPOINT_LIVE_TEXT_LINE_HEIGHT,
                  s->lines[i], s->row_roles[i], accent);
    draw_page_rail(canvas, s, accent);
}

void keypoint_draw_middle(lv_obj_t *canvas, const struct status_state *state,
                          const struct keypoint_live_data_snapshot *s) {
    lv_canvas_fill_bg(canvas, keypoint_color(KP_WHITE), LV_OPA_COVER);
    if (s->has_data) {
        enum keypoint_color accent = keypoint_card_accent(s->icon);
        for (int i = KEYPOINT_LIVE_TOP_LINE_COUNT; i < KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT; ++i)
            draw_line(canvas, KEYPOINT_LIVE_EXTRA_TEXT_Y +
                      (i - KEYPOINT_LIVE_TOP_LINE_COUNT) * KEYPOINT_LIVE_TEXT_LINE_HEIGHT,
                      s->lines[i], s->row_roles[i], accent);
        enum keypoint_color health = keypoint_health_color(s);
        if (s->stale) {
            static const int segments[] = {0, 16, 33, 50, 66};
            for (unsigned i = 0; i < sizeof(segments) / sizeof(segments[0]); ++i)
                rect(canvas, segments[i], KEYPOINT_LIVE_HEALTH_Y, 6, KEYPOINT_LIVE_HEALTH_HEIGHT, health);
        } else {
            rect(canvas, KEYPOINT_LIVE_HEALTH_X, KEYPOINT_LIVE_HEALTH_Y,
                 KEYPOINT_LIVE_HEALTH_WIDTH, KEYPOINT_LIVE_HEALTH_HEIGHT, health);
        }
    }
    lv_draw_rect_dsc_t fg;
    lv_draw_label_dsc_t label, inverse;
    init_rect_dsc(&fg, keypoint_color(KP_BLACK));
    init_label_dsc(&label, keypoint_color(KP_BLACK), &lv_font_unscii_8, LV_TEXT_ALIGN_LEFT);
    init_label_dsc(&inverse, keypoint_color(KP_WHITE), &lv_font_unscii_8, LV_TEXT_ALIGN_LEFT);
    draw_profile_grid(canvas, state, &fg, &label, &inverse);
    label.align = LV_TEXT_ALIGN_CENTER;
    draw_layer_info(canvas, state, &label);
}
