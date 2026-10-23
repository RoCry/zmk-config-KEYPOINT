#include "display_surface.h"
#include "theme.h"

void keypoint_style_surface(lv_obj_t *object) {
    lv_obj_remove_style_all(object);
    lv_obj_set_style_bg_color(object, LVGL_BACKGROUND, 0);
    lv_obj_set_style_bg_opa(object, LV_OPA_COVER, 0);
    lv_obj_clear_flag(object, LV_OBJ_FLAG_SCROLLABLE);
}

lv_obj_t *keypoint_create_surface(lv_obj_t *parent) {
    lv_obj_t *surface = lv_obj_create(parent);
    keypoint_style_surface(surface);
    lv_obj_set_size(surface, 144, 72);
    lv_obj_set_pos(surface, 0, 0);
    return surface;
}

lv_obj_t *keypoint_create_canvas(lv_obj_t *parent, lv_color_t *pixels, int x) {
    lv_obj_t *canvas = lv_canvas_create(parent);
    lv_obj_remove_style_all(canvas);
    lv_canvas_set_buffer(canvas, pixels, CANVAS_SIZE, CANVAS_SIZE, LV_IMG_CF_TRUE_COLOR);
    lv_canvas_fill_bg(canvas, LVGL_BACKGROUND, LV_OPA_COVER);
    lv_obj_set_pos(canvas, x, 0);
    return canvas;
}

lv_obj_t *keypoint_create_art(lv_obj_t *parent, const lv_img_dsc_t *image) {
    lv_obj_t *art = lv_img_create(parent);
    lv_obj_remove_style_all(art);
    lv_img_set_src(art, image);
    /* Assets cover the entire 144x72 logical screen at their native size. */
    lv_obj_align(art, LV_ALIGN_TOP_RIGHT, 0, 0);
    return art;
}

lv_obj_t *keypoint_create_overlay(lv_obj_t *parent, uint8_t *pixels) {
    lv_obj_t *canvas = lv_canvas_create(parent);
    lv_obj_remove_style_all(canvas);
    lv_canvas_set_buffer(canvas, pixels, CANVAS_SIZE, CANVAS_SIZE, LV_IMG_CF_TRUE_COLOR_ALPHA);
    lv_canvas_fill_bg(canvas, LVGL_BACKGROUND, LV_OPA_TRANSP);
    lv_obj_set_pos(canvas, 0, 0);
    return canvas;
}

void keypoint_draw_peripheral_top(lv_obj_t *canvas, const struct status_state *state,
                                 bool connected) {
    lv_canvas_fill_bg(canvas, LVGL_BACKGROUND, LV_OPA_TRANSP);
    lv_draw_rect_dsc_t backing;
    init_rect_dsc(&backing, LVGL_BACKGROUND);
    lv_canvas_draw_rect(canvas, 0, 0, CANVAS_SIZE, 18, &backing);
    draw_battery(canvas, state);
    lv_draw_label_dsc_t label;
    init_label_dsc(&label, keypoint_color(connected ? KP_GREEN : KP_RED),
                   &lv_font_montserrat_16, LV_TEXT_ALIGN_RIGHT);
    lv_canvas_draw_text(canvas, 0, 0, CANVAS_SIZE, &label,
                       connected ? LV_SYMBOL_WIFI : LV_SYMBOL_CLOSE);
}
