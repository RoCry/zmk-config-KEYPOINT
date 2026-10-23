/* Real LVGL object composition and flush, followed by the firmware panel encoder. */
#include "status_render.h"
#include "display_surface.h"
#include "gallery.h"
#include "live_data_core.h"
#include "lpm009m360a_core.h"
#include <errno.h>
#include <string.h>

static lv_obj_t *surfaces[2], *canvases[3], *art;
static lv_color_t pixels[2][CANVAS_SIZE * CANVAS_SIZE];
static uint8_t overlay_pixels[LV_IMG_BUF_SIZE_TRUE_COLOR_ALPHA(CANVAS_SIZE, CANVAS_SIZE)];
static lv_color_t draw_pixels[LPM_LOGICAL_WIDTH * LPM_LOGICAL_HEIGHT];
static lv_color_t screen[LPM_LOGICAL_WIDTH * LPM_LOGICAL_HEIGHT];

int keypoint_preview_dimension(int axis) {
    return axis ? LPM_NATIVE_ROWS : CANVAS_SIZE;
}

const char *keypoint_preview_image_name(int index) {
    return index >= 0 && (size_t)index < keypoint_gallery_count ? keypoint_gallery[index].name : NULL;
}

static void flush(lv_disp_drv_t *drv, const lv_area_t *area, lv_color_t *colors) {
    int width = area->x2 - area->x1 + 1;
    for (int y = area->y1; y <= area->y2; ++y)
        memcpy(screen + y * LPM_LOGICAL_WIDTH + area->x1,
               colors + (y - area->y1) * width, width * sizeof(lv_color_t));
    lv_disp_flush_ready(drv);
}

static void init(void) {
    if (surfaces[0]) return;
    lv_init();
    static lv_disp_draw_buf_t draw;
    static lv_disp_drv_t driver;
    lv_disp_draw_buf_init(&draw, draw_pixels, NULL, LPM_LOGICAL_WIDTH * LPM_LOGICAL_HEIGHT);
    lv_disp_drv_init(&driver);
    driver.draw_buf = &draw;
    driver.hor_res = LPM_LOGICAL_WIDTH;
    driver.ver_res = LPM_LOGICAL_HEIGHT;
    driver.flush_cb = flush;
    lv_disp_drv_register(&driver);
    keypoint_style_surface(lv_scr_act());
    for (int i = 0; i < 2; ++i) surfaces[i] = keypoint_create_surface(lv_scr_act());
    canvases[0] = keypoint_create_canvas(surfaces[0], pixels[0], 0);
    canvases[1] = keypoint_create_canvas(surfaces[0], pixels[1], KEYPOINT_MIDDLE_X);
    art = keypoint_create_art(surfaces[1], keypoint_gallery[0].image);
    canvases[2] = keypoint_create_overlay(surfaces[1], overlay_pixels);
}

static int glass(uint8_t *rgb, int side) {
    lv_obj_add_flag(surfaces[1 - side], LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(surfaces[side], LV_OBJ_FLAG_HIDDEN);
    lv_obj_invalidate(lv_scr_act());
    lv_refr_now(NULL);
    struct lpm_frame panel;
    lpm_frame_init(&panel);
    const struct lpm_rect r = {.width = LPM_LOGICAL_WIDTH, .height = LPM_LOGICAL_HEIGHT,
        .pitch = LPM_LOGICAL_WIDTH, .buf_size = sizeof(screen)};
    int ret = lpm_frame_write_rgb565(&panel, &r, screen);
    if (ret) return ret;
    /* Panel is mounted with its native origin at the portrait bottom-right. */
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
    for (int i = 0; i < 2; ++i) rotate_canvas(canvases[i], pixels[i]);
    return glass(rgb, 0);
}

int keypoint_preview_right(uint8_t *rgb, size_t size, int battery, bool charging,
                           bool connected, int image) {
    if (!rgb || size != CANVAS_SIZE * LPM_NATIVE_ROWS * 3 || battery < 0 || battery > 100 ||
        image < 0 || (size_t)image >= keypoint_gallery_count) return -EINVAL;
    init();
    struct status_state status = {.battery = battery, .charging = charging};
    keypoint_draw_peripheral_top(canvases[2], &status, connected);
    rotate_canvas(canvases[2], overlay_pixels);
    lv_img_set_src(art, keypoint_gallery[image].image);
    return glass(rgb, 1);
}
