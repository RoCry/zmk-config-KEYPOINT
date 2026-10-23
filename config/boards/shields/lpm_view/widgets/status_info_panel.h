/*
 *
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 *
 */

#pragma once

#include <stddef.h>

#include <lvgl.h>

#include "util.h"

/* The middle canvas' info panel: the BLE profile grid and the layer label.
 * Implemented in status_info_panel.c; the slot geometry lives there too. */

void draw_profile_grid(lv_obj_t *canvas, const struct status_state *state);

void draw_layer_info(lv_obj_t *canvas, const struct status_state *state);

/* Strip leading and trailing spaces into `buffer` (truncating to fit) and
 * return it, or "" when there is nothing to trim into. Shared with the
 * live-data title bar, which centres a string the producer padded to align its
 * data columns. */
const char *trim_spaces(const char *label, char *buffer, size_t buffer_size);
