/*
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 *
 * ctypes shim for the pure motion-shaping module.
 *
 * Same trick as kp3_core_shim.c: flatten every call to primitives so the Python
 * side needs no struct-layout knowledge, and the device configs live here in C,
 * read straight from the two adapters' Kconfig defaults.
 *
 * Test fixture only; never compiled into firmware.
 */

#include <stdint.h>

#include "motion_shaping.h"

int motion_shim_delta_max(void) { return MOTION_DELTA_MAX; }

int motion_shim_arrow_divisor(int deadzone, int divisor_slow, int divisor_fast, int delta) {
    const struct motion_arrow_config cfg = {
        .deadzone = deadzone,
        .divisor_slow = divisor_slow,
        .divisor_fast = divisor_fast,
    };

    return motion_arrow_divisor(&cfg, (int8_t)delta);
}

/* One arrow step. Returns the pulse count; `*direction` carries the sign. */
int motion_shim_arrow_step(int deadzone, int divisor_slow, int divisor_fast, int delta,
                           int16_t *residue, int *direction) {
    const struct motion_arrow_config cfg = {
        .deadzone = deadzone,
        .divisor_slow = divisor_slow,
        .divisor_fast = divisor_fast,
    };

    const struct motion_arrow_pulse pulse = motion_arrow_step(&cfg, (int8_t)delta, residue);

    *direction = pulse.direction;
    return pulse.pulses;
}

/* One scroll sample. `residue` is a two-float array owned by the caller. */
void motion_shim_scroll_accumulate(float *residue, int delta_x, int delta_y, int16_t *tick_x,
                                   int16_t *tick_y) {
    struct motion_scroll_residue state = {.x = residue[0], .y = residue[1]};

    const struct motion_scroll_ticks ticks =
        motion_scroll_accumulate(&state, (int8_t)delta_x, (int8_t)delta_y);

    residue[0] = state.x;
    residue[1] = state.y;
    *tick_x = ticks.x;
    *tick_y = ticks.y;
}

float motion_shim_cursor_scale(int prescale_num, int prescale_den, float base_speed,
                               float sens_base, float sens_step, float slow_multiplier, int delta,
                               int speed_preference, int slow, float boost) {
    const struct motion_cursor_config cfg = {
        .prescale_num = (int16_t)prescale_num,
        .prescale_den = (int16_t)prescale_den,
        .base_speed = base_speed,
        .sens_base = sens_base,
        .sens_step = sens_step,
        .slow_multiplier = slow_multiplier,
    };

    return motion_cursor_scale(&cfg, (int8_t)delta, (uint8_t)speed_preference, slow != 0, boost);
}

void motion_shim_dominant_axis(int numerator, int denominator, int *delta_x, int *delta_y) {
    int8_t dx = (int8_t)*delta_x;
    int8_t dy = (int8_t)*delta_y;

    motion_dominant_axis(&dx, &dy, numerator, denominator);

    *delta_x = dx;
    *delta_y = dy;
}
