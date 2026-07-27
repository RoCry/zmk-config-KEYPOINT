/*
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 */

#include <math.h>

#include "motion_shaping.h"

float motion_cursor_scale(const struct motion_cursor_config *cfg, int8_t delta,
                          uint8_t speed_preference, float boost) {
    const int prescaled = (delta * cfg->prescale_num) / cfg->prescale_den;
    const float sensitivity = cfg->sens_base + cfg->sens_step * speed_preference;

    return prescaled * cfg->base_speed * sensitivity * boost;
}

/* Scroll gain per sample, stepped by how fast the finger is moving. */
static float scroll_gain(int8_t dx, int8_t dy) {
    const float speed = sqrtf((float)(dx * dx + dy * dy));

    return (speed > 80)   ? 0.05f
           : (speed > 40) ? 0.04f
           : (speed > 20) ? 0.03f
           : (speed > 5)  ? 0.02f
                          : 0.015f;
}

struct motion_scroll_ticks motion_scroll_accumulate(struct motion_scroll_residue *residue,
                                                    int8_t dx, int8_t dy) {
    const float gain = scroll_gain(dx, dy);

    residue->x += dx * gain;
    residue->y += dy * gain;

    const struct motion_scroll_ticks ticks = {
        .x = (int16_t)residue->x,
        .y = (int16_t)residue->y,
    };

    residue->x -= ticks.x;
    residue->y -= ticks.y;

    return ticks;
}
