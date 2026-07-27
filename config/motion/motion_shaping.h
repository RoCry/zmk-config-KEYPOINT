/*
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

/*
 * Motion shaping: the pure math that turns a pointing device's raw deltas into
 * cursor movement, scroll ticks and arrow-key repeats.
 *
 * No Zephyr, no device handles, no globals, no I/O. The caller owns every piece
 * of state and does every report; these functions only decide *what* should be
 * emitted. That is what makes this file compilable -- and testable -- on a
 * host, and what lets the trackpad and the trackpoint share one copy of the
 * math instead of two that drift apart.
 */

/* Magnitude limit of a device delta: deltas arrive as int8_t and abs(INT8_MIN)
 * is 128. The arrow speed curve is normalised over exactly this domain. */
#define MOTION_DELTA_MAX 128

/* ========================================================================= */
/* Cursor                                                                    */
/* ========================================================================= */

/* How a device turns a raw delta into cursor movement. */
struct motion_cursor_config {
    /* Integer pre-scale applied to the raw delta before any float math. The
     * truncation is part of the device's feel -- it swallows the smallest
     * deltas -- so it stays in integers, deliberately. Use 1/1 for none. */
    int16_t prescale_num;
    int16_t prescale_den;
    float base_speed;      /* fixed device gain */
    float sens_base;       /* user gain at speed preference 0 */
    float sens_step;       /* user gain added per unit of speed preference */
    float slow_multiplier; /* applied while the slow key is held */
};

/* Cursor movement for one axis, before the adapter applies its own sign
 * convention and rounds to whole pixels.
 *
 * `speed_preference` is the user's cursor-speed setting. `boost` is a
 * device-specific acceleration multiplier; pass 1.0f for none. */
float motion_cursor_scale(const struct motion_cursor_config *cfg, int8_t delta,
                          uint8_t speed_preference, bool slow, float boost);

/* ========================================================================= */
/* Scroll                                                                    */
/* ========================================================================= */

/* Fractional scroll carried between samples. Zero-initialise. */
struct motion_scroll_residue {
    float x;
    float y;
};

/* Whole scroll ticks owed on each axis; 0 means "not yet". */
struct motion_scroll_ticks {
    int16_t x;
    int16_t y;
};

/* Fold one sample into `residue` and take out the whole ticks it earns. The
 * gain steps up with the sample's speed, so a flick scrolls further per sample
 * than a drag, and the fraction left over survives to the next sample -- which
 * is what makes slow scrolling possible at all. Sign is the caller's business. */
struct motion_scroll_ticks motion_scroll_accumulate(struct motion_scroll_residue *residue,
                                                    int8_t dx, int8_t dy);

/* ========================================================================= */
/* Arrow mode                                                                */
/* ========================================================================= */

/* How a device turns deltas into arrow-key repeats.
 * Precondition: 1 <= divisor_fast <= divisor_slow. */
struct motion_arrow_config {
    int deadzone;     /* |delta| at or below this emits nothing */
    int divisor_slow; /* residue one key press costs at rest -- finest control */
    int divisor_fast; /* residue one key press costs at full scale -- fastest */
};

/* What one axis of arrow motion should emit. */
struct motion_arrow_pulse {
    uint8_t pulses;   /* press/release pulses to send; 0 means nothing */
    int8_t direction; /* -1 or +1; only meaningful when pulses > 0 */
};

/* The speed curve: residue one arrow press costs at `delta`. Quadratic in
 * |delta| normalised over MOTION_DELTA_MAX, running from `divisor_slow` at rest
 * down to `divisor_fast` at full scale and never leaving that range. */
int motion_arrow_divisor(const struct motion_arrow_config *cfg, int8_t delta);

/* Fold `delta` into `residue` and decide the arrow repeat it earns. */
struct motion_arrow_pulse motion_arrow_step(const struct motion_arrow_config *cfg, int8_t delta,
                                            int16_t *residue);

/* Zero the weaker axis so a diagonal drag does not fire two arrows at once.
 * When neither axis leads the other by `numerator`/`denominator`, both are
 * zeroed: an ambiguous drag should move nothing. */
void motion_dominant_axis(int8_t *dx, int8_t *dy, int numerator, int denominator);
