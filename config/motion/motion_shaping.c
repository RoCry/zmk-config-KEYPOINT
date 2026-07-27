/*
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 */

#include <math.h>
#include <stdlib.h>

#include "motion_shaping.h"

float motion_cursor_scale(const struct motion_cursor_config *cfg, int8_t delta,
                          uint8_t speed_preference, bool slow, float boost) {
    const int prescaled = (delta * cfg->prescale_num) / cfg->prescale_den;
    const float sensitivity = cfg->sens_base + cfg->sens_step * speed_preference;
    const float slow_multiplier = slow ? cfg->slow_multiplier : 1.0f;

    return prescaled * cfg->base_speed * sensitivity * boost * slow_multiplier;
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

int motion_arrow_divisor(const struct motion_arrow_config *cfg, int8_t delta) {
    /* abs(int8_t) never exceeds MOTION_DELTA_MAX, so t stays in [0, 1] and the
     * divisor stays in [divisor_fast, divisor_slow] -- no floor clamp needed. */
    const float t = (float)abs(delta) / MOTION_DELTA_MAX;
    const float curve = t * t;

    return (int)(cfg->divisor_slow - (cfg->divisor_slow - cfg->divisor_fast) * curve);
}

struct motion_arrow_pulse motion_arrow_step(const struct motion_arrow_config *cfg, int8_t delta,
                                            int16_t *residue) {
    struct motion_arrow_pulse pulse = {.pulses = 0, .direction = 0};

    if (abs(delta) <= cfg->deadzone) {
        return pulse;
    }

    const int divisor = motion_arrow_divisor(cfg, delta);

    *residue += delta;

    const int16_t ticks = (int16_t)(*residue / divisor);
    if (ticks != 0) {
        /* One pulse per sample however many ticks were earned: the repeat rate
         * comes from how fast the residue refills, not from the tick count. */
        pulse.pulses = 1;
        pulse.direction = (ticks > 0) ? 1 : -1;
        *residue = (int16_t)(*residue % divisor);
    }

    /* Bleed off what is left so a finger that stops does not keep firing. */
    *residue = (int16_t)((*residue * 3) / 4);

    return pulse;
}

void motion_dominant_axis(int8_t *dx, int8_t *dy, int numerator, int denominator) {
    const int abs_dx = abs(*dx);
    const int abs_dy = abs(*dy);

    if (abs_dy * denominator > abs_dx * numerator) {
        *dx = 0;
    } else if (abs_dx * denominator > abs_dy * numerator) {
        *dy = 0;
    } else {
        *dx = 0;
        *dy = 0;
    }
}
