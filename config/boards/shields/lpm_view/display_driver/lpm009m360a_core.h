/* SPDX-License-Identifier: Apache-2.0 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Logical landscape coordinates; native panel is 72 columns x 144 rows. */
#define LPM_LOGICAL_WIDTH 144
#define LPM_LOGICAL_HEIGHT 72
#define LPM_NATIVE_ROWS 144
#define LPM_ROW_BYTES 27

struct lpm_frame {
    uint8_t pixels[LPM_NATIVE_ROWS][LPM_ROW_BYTES];
    bool dirty[LPM_NATIVE_ROWS];
};

struct lpm_rect {
    uint16_t x;
    uint16_t y;
    uint16_t width;
    uint16_t height;
    uint16_t pitch;
    size_t buf_size;
};

/* write holds CS high between calls; end always releases CS, including errors. */
struct lpm_transport {
    int (*write)(void *context, const uint8_t *bytes, size_t size);
    int (*end)(void *context);
    void *context;
};

void lpm_frame_init(struct lpm_frame *frame);
int lpm_frame_write_rgb565(struct lpm_frame *frame, const struct lpm_rect *rect,
                           const void *pixels);
int lpm_frame_flush(struct lpm_frame *frame, const struct lpm_transport *transport);
