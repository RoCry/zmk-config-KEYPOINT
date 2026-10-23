#pragma once

#include "util.h"

/* Shared object geometry: firmware and native previews render the same tree. */
void keypoint_style_surface(lv_obj_t *object);
lv_obj_t *keypoint_create_surface(lv_obj_t *parent);
lv_obj_t *keypoint_create_canvas(lv_obj_t *parent, lv_color_t *pixels, int x);
lv_obj_t *keypoint_create_overlay(lv_obj_t *parent, uint8_t *pixels);
lv_obj_t *keypoint_create_art(lv_obj_t *parent, const lv_img_dsc_t *image);
void keypoint_draw_peripheral_top(lv_obj_t *canvas, const struct status_state *state,
                                 bool connected);
