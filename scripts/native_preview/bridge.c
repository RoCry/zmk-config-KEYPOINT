/* Host adapter only; rendering, rotation, quantization and parsing are firmware code. */
#include "status_render.h"
#include "live_data_core.h"
#include "lpm009m360a_core.h"
#include <errno.h>
#include <string.h>

static lv_obj_t *canvases[2];
static lv_color_t pixels[2][CANVAS_SIZE * CANVAS_SIZE];
static lv_color_t flush_pixels[LPM_LOGICAL_WIDTH];

int keypoint_preview_dimension(int axis) {
    return axis ? LPM_NATIVE_ROWS : CANVAS_SIZE;
}

static void flush(lv_disp_drv_t *drv, const lv_area_t *area, lv_color_t *colors) {
    (void)area;
    (void)colors;
    lv_disp_flush_ready(drv);
}

static void init(void) {
    if (canvases[0]) return;
    lv_init();
    static lv_disp_draw_buf_t draw;
    static lv_disp_drv_t driver;
    lv_disp_draw_buf_init(&draw, flush_pixels, NULL, LPM_LOGICAL_WIDTH);
    lv_disp_drv_init(&driver);
    driver.draw_buf = &draw;
    driver.hor_res = LPM_LOGICAL_WIDTH;
    driver.ver_res = LPM_LOGICAL_HEIGHT;
    driver.flush_cb = flush;
    lv_disp_drv_register(&driver);
    for (int i = 0; i < 2; ++i) {
        canvases[i] = lv_canvas_create(lv_scr_act());
        lv_canvas_set_buffer(canvases[i], pixels[i], CANVAS_SIZE, CANVAS_SIZE, LV_IMG_CF_TRUE_COLOR);
    }
}

/* state: battery, charging, usb, active profile, connected mask, bonded mask,
 * layer. mode0 = portrait glass, 1/2 = unrotated top/middle canvas. */
int keypoint_preview(uint8_t *rgb, size_t size, const char *frame, bool stale,
                      const int state[7], const char *layer, int mode) {
    if (!rgb || !state || mode < 0 || mode > 2 ||
        size != (size_t)CANVAS_SIZE * (mode ? CANVAS_SIZE : LPM_NATIVE_ROWS) * 3)
        return -EINVAL;
    init();
    struct keypoint_live_data_deck empty = {0};
    struct keypoint_live_data_snapshot s = keypoint_live_data_core_snapshot(&empty, 0);
    if (frame) {
        size_t length = strlen(frame);
        if (length > KEYPOINT_LIVE_DATA_FRAME_MAX) return -EINVAL;
        int ret = keypoint_live_data_parse((const uint8_t *)frame, length, &s.generation,
            &s.view_index, &s.total_pages, &s.icon, &s.led_hint, s.row_roles, s.lines);
        if (ret) return ret;
        s.has_data = true;
        s.stale = stale;
    }
    struct status_state status = {.battery = state[0], .charging = state[1], .usb = state[2],
        .active_profile_index = state[3], .layer_index = state[6], .layer_label = layer};
    for (int i = 0; i < KEYPOINT_STATUS_PROFILE_COUNT; ++i) {
        status.profile_connected[i] = (state[4] >> i) & 1;
        status.profile_bonded[i] = (state[5] >> i) & 1;
    }
    status.active_profile_connected = status.profile_connected[status.active_profile_index];
    status.active_profile_bonded = status.profile_bonded[status.active_profile_index];
    keypoint_draw_top(canvases[0], &status, &s);
    keypoint_draw_middle(canvases[1], &status, &s);
    if (mode) {
        for (int i = 0; i < CANVAS_SIZE * CANVAS_SIZE; ++i) {
            uint16_t c = pixels[mode - 1][i].full;
            rgb[i * 3] = c & 0x8000 ? 255 : 0;
            rgb[i * 3 + 1] = c & 0x0400 ? 255 : 0;
            rgb[i * 3 + 2] = c & 0x0010 ? 255 : 0;
        }
        return 0;
    }
    static lv_color_t screen[LPM_LOGICAL_WIDTH * LPM_LOGICAL_HEIGHT];
    for (unsigned i = 0; i < sizeof(screen) / sizeof(screen[0]); ++i) screen[i] = lv_color_white();
    for (int i = 0; i < 2; ++i) {
        rotate_canvas(canvases[i], pixels[i]);
        int offset = i ? KEYPOINT_MIDDLE_X : 0;
        for (int y = 0; y < CANVAS_SIZE; ++y)
            memcpy(screen + y * LPM_LOGICAL_WIDTH + offset, pixels[i] + y * CANVAS_SIZE,
                   CANVAS_SIZE * sizeof(lv_color_t));
    }
    struct lpm_frame panel;
    lpm_frame_init(&panel);
    const struct lpm_rect r = {.width = LPM_LOGICAL_WIDTH, .height = LPM_LOGICAL_HEIGHT,
        .pitch = LPM_LOGICAL_WIDTH, .buf_size = sizeof(screen)};
    int ret = lpm_frame_write_rgb565(&panel, &r, screen);
    if (ret) return ret;
    /* Panel is mounted with the native origin at the portrait bottom-right. */
    for (int y = 0; y < LPM_NATIVE_ROWS; ++y) {
        const uint8_t *row = panel.pixels[LPM_NATIVE_ROWS - 1 - y];
        for (int x = 0; x < CANVAS_SIZE; ++x) {
            for (int channel = 0; channel < 3; ++channel) {
                int bit = (CANVAS_SIZE - 1 - x) * 3 + channel;
                rgb[(y * CANVAS_SIZE + x) * 3 + channel] = row[bit / 8] & (0x80 >> (bit % 8)) ? 255 : 0;
            }
        }
    }
    return 0;
}
