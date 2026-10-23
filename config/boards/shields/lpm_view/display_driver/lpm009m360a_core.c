/* SPDX-License-Identifier: Apache-2.0 */
#include "lpm009m360a_core.h"

#include <errno.h>
#include <string.h>

void lpm_frame_init(struct lpm_frame *frame) {
    memset(frame->pixels, 0xff, sizeof(frame->pixels));
    memset(frame->dirty, 1, sizeof(frame->dirty));
}

static uint8_t rgb111(uint16_t pixel) {
    /* Half-range channel thresholds, exact for all eight RGB565 endpoints. */
    return ((pixel >> 13) & 4) | ((pixel >> 9) & 2) | ((pixel >> 4) & 1);
}

static bool set_pixel(uint8_t *row, uint16_t column, uint8_t color) {
    bool changed = false;
    for (unsigned channel = 0; channel < 3; channel++) {
        unsigned bit = column * 3 + channel;
        uint8_t mask = 0x80 >> (bit % 8);
        uint8_t *byte = &row[bit / 8];
        uint8_t next = (color & (4 >> channel)) ? (*byte | mask) : (*byte & ~mask);
        changed |= next != *byte;
        *byte = next;
    }
    return changed;
}

int lpm_frame_write_rgb565(struct lpm_frame *frame, const struct lpm_rect *rect,
                           const void *pixels) {
    if (!frame || !rect || !pixels || !rect->width || !rect->height || rect->pitch < rect->width ||
        rect->x >= LPM_LOGICAL_WIDTH || rect->y >= LPM_LOGICAL_HEIGHT ||
        rect->width > LPM_LOGICAL_WIDTH - rect->x || rect->height > LPM_LOGICAL_HEIGHT - rect->y) {
        return -EINVAL;
    }
    size_t required = ((size_t)(rect->height - 1) * rect->pitch + rect->width) * 2;
    if (rect->buf_size < required) {
        return -EINVAL;
    }

    const uint8_t *source = pixels;
    for (uint16_t y = 0; y < rect->height; y++) {
        for (uint16_t x = 0; x < rect->width; x++) {
            uint16_t pixel;
            /* Native-endian RGB565; memcpy accepts unaligned buffers. */
            memcpy(&pixel, source + ((size_t)y * rect->pitch + x) * 2, sizeof(pixel));
            unsigned row = LPM_NATIVE_ROWS - 1 - rect->x - x;
            frame->dirty[row] |= set_pixel(frame->pixels[row], rect->y + y, rgb111(pixel));
        }
    }
    return 0;
}

int lpm_frame_flush(struct lpm_frame *frame, const struct lpm_transport *transport) {
    if (!frame || !transport || !transport->write || !transport->end) {
        return -EINVAL;
    }
    bool started = false;
    int ret = 0;
    for (unsigned row = 0; row < LPM_NATIVE_ROWS; row++) {
        if (!frame->dirty[row]) {
            continue;
        }
        uint8_t packet[2 + LPM_ROW_BYTES];
        packet[0] = started ? 0x00 : 0x80; /* RGB update, then continuation dummy. */
        packet[1] = row + 1;               /* Native binary line address, 1..144. */
        memcpy(packet + 2, frame->pixels[row], LPM_ROW_BYTES);
        started = true;
        ret = transport->write(transport->context, packet, sizeof(packet));
        if (ret) {
            break;
        }
    }
    if (!started) {
        return 0;
    }
    if (!ret) {
        const uint8_t trailing_clocks[2] = {0, 0};
        ret = transport->write(transport->context, trailing_clocks, sizeof(trailing_clocks));
    }
    int end_ret = transport->end(transport->context);
    if (!ret) {
        ret = end_ret;
    }
    if (!ret) {
        /* A failed transaction may have reached the panel in part. Retry every
         * pending line; never acknowledge desired pixels until CS is released. */
        memset(frame->dirty, 0, sizeof(frame->dirty));
    }
    return ret;
}
