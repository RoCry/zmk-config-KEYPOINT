/*
 *
 * Copyright (c) 2023 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 *
 */

#include <zephyr/kernel.h>

#include <zephyr/logging/log.h>
LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

#include <zmk/battery.h>
#include <zmk/display.h>
#include "status.h"
#include <zmk/events/usb_conn_state_changed.h>
#include <zmk/event_manager.h>
#include <zmk/events/battery_state_changed.h>
#include <zmk/events/ble_active_profile_changed.h>
#include <zmk/events/endpoint_changed.h>
#include <zmk/events/layer_state_changed.h>
#include <zmk/usb.h>
#include <zmk/ble.h>
#include <zmk/endpoints.h>
#include <zmk/keymap.h>

#include "live_data.h"
#include "status_layout.h"
#include "status_info_panel.h"

static sys_slist_t widgets = SYS_SLIST_STATIC_INIT(&widgets);

struct output_status_state {
    struct zmk_endpoint_instance selected_endpoint;
    int active_profile_index;
    bool active_profile_connected;
    bool active_profile_bonded;
    bool profile_connected[KEYPOINT_STATUS_PROFILE_COUNT];
    bool profile_bonded[KEYPOINT_STATUS_PROFILE_COUNT];
};

struct layer_status_state {
    uint8_t index;
    const char *label;
};

static void draw_bitmap_icon(lv_obj_t *canvas, lv_coord_t x, lv_coord_t y,
                             const lv_draw_rect_dsc_t *icon_dsc,
                             const char rows[KEYPOINT_LIVE_ICON_SIZE]
                                            [KEYPOINT_LIVE_ICON_SIZE + 1]) {
    for (int row = 0; row < KEYPOINT_LIVE_ICON_SIZE; row++) {
        for (int column = 0; column < KEYPOINT_LIVE_ICON_SIZE; column++) {
            if (rows[row][column] == '1') {
                lv_canvas_draw_rect(canvas, x + (column * KEYPOINT_LIVE_ICON_SCALE),
                                    y + (row * KEYPOINT_LIVE_ICON_SCALE),
                                    KEYPOINT_LIVE_ICON_SCALE, KEYPOINT_LIVE_ICON_SCALE, icon_dsc);
            }
        }
    }
}

static void draw_live_data_icon(lv_obj_t *canvas, enum keypoint_live_data_icon icon,
                                const lv_draw_rect_dsc_t *icon_dsc) {
    const char(*rows)[KEYPOINT_LIVE_ICON_SIZE + 1] = NULL;

    switch (icon) {
    case KEYPOINT_LIVE_DATA_ICON_NONE:
        return;
    case KEYPOINT_LIVE_DATA_ICON_SUN:
        rows = icon_sun;
        break;
    case KEYPOINT_LIVE_DATA_ICON_CLOUD:
        rows = icon_cloud;
        break;
    case KEYPOINT_LIVE_DATA_ICON_RAIN:
        rows = icon_rain;
        break;
    case KEYPOINT_LIVE_DATA_ICON_TEMP:
        rows = icon_temp;
        break;
    case KEYPOINT_LIVE_DATA_ICON_WARN:
        rows = icon_warn;
        break;
    case KEYPOINT_LIVE_DATA_ICON_CODE:
        rows = icon_code;
        break;
    case KEYPOINT_LIVE_DATA_ICON_TIME:
        rows = icon_time;
        break;
    case KEYPOINT_LIVE_DATA_ICON_CODEX:
        rows = icon_codex;
        break;
    case KEYPOINT_LIVE_DATA_ICON_CLAUDE:
        rows = icon_claude;
        break;
    }

    draw_bitmap_icon(canvas, KEYPOINT_LIVE_ICON_X, KEYPOINT_LIVE_ICON_Y, icon_dsc, rows);
}

/* Only called once a deck exists (the no-data state shows a centred tip on the
 * top canvas instead, never the health strip). */
static void draw_live_data_health_strip(lv_obj_t *canvas,
                                        const struct keypoint_live_data_snapshot *snapshot,
                                        const lv_draw_rect_dsc_t *rect_dsc) {
    if (snapshot->stale) {
        static const lv_coord_t segment_x[] = {0, 16, 33, 50, 66};
        for (size_t i = 0; i < ARRAY_SIZE(segment_x); i++) {
            lv_canvas_draw_rect(canvas, segment_x[i], KEYPOINT_LIVE_HEALTH_Y, 6,
                                KEYPOINT_LIVE_HEALTH_HEIGHT, rect_dsc);
        }
        return;
    }

    lv_canvas_draw_rect(canvas, KEYPOINT_LIVE_HEALTH_X, KEYPOINT_LIVE_HEALTH_Y,
                        KEYPOINT_LIVE_HEALTH_WIDTH, KEYPOINT_LIVE_HEALTH_HEIGHT, rect_dsc);
}

/* Page indicator: a scrollbar-style rail with a thumb sized 1/total_pages
 * riding it at view_index. The rail doubles as a divider between the status row
 * and the live data. Integer page->pixel math mirrors the preview oracle
 * (floor division), so the simulator stays pixel-exact. */
static void draw_live_data_page_rail(lv_obj_t *canvas,
                                     const struct keypoint_live_data_snapshot *snapshot,
                                     const lv_draw_rect_dsc_t *ink_dsc,
                                     const lv_draw_rect_dsc_t *bg_dsc) {
    if (!snapshot->has_data || snapshot->total_pages <= 1) {
        return;
    }

    const lv_coord_t x = KEYPOINT_LIVE_TEXT_X;
    const lv_coord_t w = KEYPOINT_LIVE_TEXT_WIDTH;
    const lv_coord_t y = KEYPOINT_LIVE_PAGE_Y;
    const lv_coord_t h = KEYPOINT_LIVE_PAGE_THUMB_HEIGHT;

    lv_canvas_draw_rect(canvas, x, y, w, 1, ink_dsc); // rail / track

    const lv_coord_t tx =
        x + (lv_coord_t)((uint32_t)snapshot->view_index * w / snapshot->total_pages);
    const lv_coord_t tx_next =
        x + (lv_coord_t)((uint32_t)(snapshot->view_index + 1) * w / snapshot->total_pages);
    const lv_coord_t tw = tx_next - tx;
    const lv_coord_t ty = y - h / 2;

    lv_canvas_draw_rect(canvas, tx, ty, tw, h, ink_dsc); // thumb
    // Round the four corners by punching them back to background.
    lv_canvas_draw_rect(canvas, tx, ty, 1, 1, bg_dsc);
    lv_canvas_draw_rect(canvas, tx + tw - 1, ty, 1, 1, bg_dsc);
    lv_canvas_draw_rect(canvas, tx, ty + h - 1, 1, 1, bg_dsc);
    lv_canvas_draw_rect(canvas, tx + tw - 1, ty + h - 1, 1, 1, bg_dsc);
}

/* Detect the [NNN] bar-token (exactly "[" + 3 decimal digits + "]" + NUL) and
 * draw a filled progress bar in the line slot. Returns true when rendered.
 * Bar geometry: 2px top margin, 8px outer box, 6px inner fill area (67px wide). */
static bool try_draw_hbar(lv_obj_t *canvas, lv_coord_t x, lv_coord_t y, const char *line,
                          const lv_draw_rect_dsc_t *ink_dsc,
                          const lv_draw_rect_dsc_t *bg_dsc) {
    if (line[0] != '[' || line[4] != ']' || line[5] != '\0') return false;
    if (line[1] < '0' || line[1] > '9' || line[2] < '0' || line[2] > '9' ||
        line[3] < '0' || line[3] > '9') return false;
    int pct = (line[1] - '0') * 100 + (line[2] - '0') * 10 + (line[3] - '0');
    if (pct > 100) return false;

    const lv_coord_t bar_y = y + KEYPOINT_LIVE_BAR_MARGIN_Y;
    const lv_coord_t bar_h = KEYPOINT_LIVE_BAR_HEIGHT;
    const lv_coord_t inner_w = KEYPOINT_LIVE_TEXT_WIDTH - 2 * KEYPOINT_LIVE_BAR_BORDER;
    const lv_coord_t fill_w = (lv_coord_t)(pct * inner_w / 100);

    lv_canvas_draw_rect(canvas, x, bar_y, KEYPOINT_LIVE_TEXT_WIDTH, bar_h, ink_dsc); /* border */
    lv_canvas_draw_rect(canvas, x + 1, bar_y + 1, inner_w, bar_h - 2, bg_dsc);      /* erase */
    if (fill_w > 0) {
        lv_canvas_draw_rect(canvas, x + 1, bar_y + 1, fill_w, bar_h - 2, ink_dsc); /* fill */
    }
    return true;
}

/* The card title (live line 0) renders inverted: a filled foreground bar
 * spanning the text width with the title text knocked out in the background
 * colour and centred. Mirrors the active-profile slot styling. The producer
 * pads the title to align its data columns, so trim it before centring. */
static void draw_live_data_title(lv_obj_t *canvas, const char *title,
                                 const lv_draw_label_dsc_t *label_dsc,
                                 const lv_draw_rect_dsc_t *ink_dsc,
                                 const lv_draw_rect_dsc_t *bg_dsc) {
    char trimmed[KEYPOINT_LIVE_DATA_LINE_MAX + 1];
    const char *text = trim_spaces(title, trimmed, sizeof(trimmed));
    if (text[0] == '\0') {
        return;
    }

    lv_canvas_draw_rect(canvas, KEYPOINT_LIVE_TEXT_X, KEYPOINT_LIVE_TITLE_BAR_Y,
                        KEYPOINT_LIVE_TEXT_WIDTH, KEYPOINT_LIVE_TITLE_BAR_HEIGHT, ink_dsc);

    lv_draw_label_dsc_t title_dsc = *label_dsc;
    title_dsc.color = bg_dsc->bg_color;
    title_dsc.align = LV_TEXT_ALIGN_CENTER;
    lv_canvas_draw_text(canvas, KEYPOINT_LIVE_TEXT_X, KEYPOINT_LIVE_TEXT_Y, KEYPOINT_LIVE_TEXT_WIDTH,
                        &title_dsc, text);
}

/* No live data yet: render a centred hint on the top canvas instead of the
 * live-data grid. Plain centred text -- deliberately unlike the data UI (no
 * inverted title, right-aligned columns, page rail or health strip). */
static void draw_live_data_tip(lv_obj_t *canvas,
                               const struct keypoint_live_data_snapshot *snapshot,
                               const lv_draw_label_dsc_t *label_dsc) {
    lv_draw_label_dsc_t tip_dsc = *label_dsc;
    tip_dsc.align = LV_TEXT_ALIGN_CENTER;

    for (int i = 0; i < KEYPOINT_LIVE_TOP_LINE_COUNT; i++) {
        if (snapshot->lines[i][0] == '\0') {
            continue;
        }
        lv_coord_t y = KEYPOINT_LIVE_TIP_Y + (i * KEYPOINT_LIVE_TEXT_LINE_HEIGHT);
        lv_canvas_draw_text(canvas, KEYPOINT_LIVE_TEXT_X, y, KEYPOINT_LIVE_TEXT_WIDTH, &tip_dsc,
                            snapshot->lines[i]);
    }
}

/* LV_COLOR_DEPTH=1 cannot dim stale data (blending is a >50% opacity
 * threshold), so live data always renders at full contrast; staleness is
 * signaled by the segmented health strip on the middle canvas instead. */
static void draw_live_data_panel(lv_obj_t *canvas, const lv_draw_label_dsc_t *label_dsc,
                                 const lv_draw_rect_dsc_t *ink_dsc,
                                 const lv_draw_rect_dsc_t *bg_dsc) {
    struct keypoint_live_data_snapshot snapshot = keypoint_live_data_snapshot_get();

    if (!snapshot.has_data) {
        draw_live_data_tip(canvas, &snapshot, label_dsc);
        return;
    }

    draw_live_data_icon(canvas, snapshot.icon, ink_dsc);

    draw_live_data_title(canvas, snapshot.lines[0], label_dsc, ink_dsc, bg_dsc);

    for (int i = 1; i < KEYPOINT_LIVE_TOP_LINE_COUNT; i++) {
        lv_coord_t y = KEYPOINT_LIVE_TEXT_Y + (i * KEYPOINT_LIVE_TEXT_LINE_HEIGHT);
        if (!try_draw_hbar(canvas, KEYPOINT_LIVE_TEXT_X, y, snapshot.lines[i], ink_dsc, bg_dsc)) {
            lv_canvas_draw_text(canvas, KEYPOINT_LIVE_TEXT_X, y, KEYPOINT_LIVE_TEXT_WIDTH,
                                label_dsc, snapshot.lines[i]);
        }
    }

    draw_live_data_page_rail(canvas, &snapshot, ink_dsc, bg_dsc);
}

static void draw_live_data_extra(lv_obj_t *canvas, const lv_draw_label_dsc_t *label_dsc,
                                 const lv_draw_rect_dsc_t *ink_dsc,
                                 const lv_draw_rect_dsc_t *bg_dsc) {
    struct keypoint_live_data_snapshot snapshot = keypoint_live_data_snapshot_get();

    if (!snapshot.has_data) {
        return; /* the no-data tip lives on the top canvas only */
    }

    for (int i = KEYPOINT_LIVE_TOP_LINE_COUNT; i < KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT; i++) {
        lv_coord_t y = KEYPOINT_LIVE_EXTRA_TEXT_Y +
                       ((i - KEYPOINT_LIVE_TOP_LINE_COUNT) * KEYPOINT_LIVE_TEXT_LINE_HEIGHT);
        if (!try_draw_hbar(canvas, KEYPOINT_LIVE_TEXT_X, y, snapshot.lines[i], ink_dsc, bg_dsc)) {
            lv_canvas_draw_text(canvas, KEYPOINT_LIVE_TEXT_X, y, KEYPOINT_LIVE_TEXT_WIDTH,
                                label_dsc, snapshot.lines[i]);
        }
    }

    draw_live_data_health_strip(canvas, &snapshot, ink_dsc);
}

static void draw_top(lv_obj_t *widget, lv_color_t cbuf[], const struct status_state *state) {
    lv_obj_t *canvas = lv_obj_get_child(widget, 0);

    lv_draw_label_dsc_t label_dsc;
    init_label_dsc(&label_dsc, LVGL_FOREGROUND, &lv_font_montserrat_16, LV_TEXT_ALIGN_RIGHT);
    lv_draw_label_dsc_t label_dsc_wpm;
    init_label_dsc(&label_dsc_wpm, LVGL_FOREGROUND, &lv_font_unscii_8, LV_TEXT_ALIGN_RIGHT);
    lv_draw_rect_dsc_t rect_black_dsc;
    init_rect_dsc(&rect_black_dsc, LVGL_BACKGROUND);
    lv_draw_rect_dsc_t icon_dsc;
    init_rect_dsc(&icon_dsc, LVGL_FOREGROUND);

    // Fill background
    lv_canvas_draw_rect(canvas, 0, 0, CANVAS_SIZE, CANVAS_SIZE, &rect_black_dsc);

    // Draw battery
    draw_battery(canvas, state);

    // Draw output status
    char output_text[10] = {};

    switch (state->selected_endpoint.transport) {
    case ZMK_TRANSPORT_USB:
        strcat(output_text, LV_SYMBOL_USB);
        break;
    case ZMK_TRANSPORT_BLE:
        if (state->active_profile_bonded) {
            if (state->active_profile_connected) {
                strcat(output_text, LV_SYMBOL_WIFI);
            } else {
                strcat(output_text, LV_SYMBOL_CLOSE);
            }
        } else {
            strcat(output_text, LV_SYMBOL_SETTINGS);
        }
        break;
    }

    lv_canvas_draw_text(canvas, 0, 0, CANVAS_SIZE, &label_dsc, output_text);

    draw_live_data_panel(canvas, &label_dsc_wpm, &icon_dsc, &rect_black_dsc);

    // Rotate canvas
    rotate_canvas(canvas, cbuf);
}

static void draw_middle(lv_obj_t *widget, lv_color_t cbuf[], const struct status_state *state) {
    lv_obj_t *canvas = lv_obj_get_child(widget, 1);

    lv_draw_rect_dsc_t rect_black_dsc;
    init_rect_dsc(&rect_black_dsc, LVGL_BACKGROUND);
    lv_draw_rect_dsc_t rect_white_dsc;
    init_rect_dsc(&rect_white_dsc, LVGL_FOREGROUND);
    lv_draw_label_dsc_t live_label_dsc;
    init_label_dsc(&live_label_dsc, LVGL_FOREGROUND, &lv_font_unscii_8, LV_TEXT_ALIGN_RIGHT);
    lv_draw_label_dsc_t profile_label_dsc;
    init_label_dsc(&profile_label_dsc, LVGL_FOREGROUND, &lv_font_unscii_8, LV_TEXT_ALIGN_LEFT);
    lv_draw_label_dsc_t profile_label_dsc_black;
    init_label_dsc(&profile_label_dsc_black, LVGL_BACKGROUND, &lv_font_unscii_8,
                   LV_TEXT_ALIGN_LEFT);
    lv_draw_label_dsc_t layer_label_dsc;
    init_label_dsc(&layer_label_dsc, LVGL_FOREGROUND, &lv_font_unscii_8, LV_TEXT_ALIGN_CENTER);

    // Fill background.
    lv_canvas_draw_rect(canvas, 0, 0, CANVAS_SIZE, CANVAS_SIZE, &rect_black_dsc);
    draw_live_data_extra(canvas, &live_label_dsc, &rect_white_dsc, &rect_black_dsc);
    draw_profile_grid(canvas, state, &rect_white_dsc, &rect_black_dsc, &profile_label_dsc,
                      &profile_label_dsc_black);
    draw_layer_info(canvas, state, &layer_label_dsc);

    rotate_canvas(canvas, cbuf);
}

/* Subscribed to LiveData in zmk_widget_status_init(). Both canvases carry live
 * data, so any change repaints both regardless of what changed. */
static void live_data_changed(enum keypoint_live_data_change change) {
    ARG_UNUSED(change);

    struct zmk_widget_status *widget;
    SYS_SLIST_FOR_EACH_CONTAINER(&widgets, widget, node) {
        draw_top(widget->obj, widget->cbuf, &widget->state);
        draw_middle(widget->obj, widget->cbuf2, &widget->state);
    }
}

static void set_battery_status(struct zmk_widget_status *widget,
                               struct battery_status_state state) {
#if IS_ENABLED(CONFIG_USB_DEVICE_STACK)
    widget->state.charging = state.usb_present;
#endif /* IS_ENABLED(CONFIG_USB_DEVICE_STACK) */

    widget->state.battery = state.level;

    draw_top(widget->obj, widget->cbuf, &widget->state);
}

static void battery_status_update_cb(struct battery_status_state state) {
    struct zmk_widget_status *widget;
    SYS_SLIST_FOR_EACH_CONTAINER(&widgets, widget, node) { set_battery_status(widget, state); }
}

static struct battery_status_state battery_status_get_state(const zmk_event_t *eh) {
    const struct zmk_battery_state_changed *ev = as_zmk_battery_state_changed(eh);

    return (struct battery_status_state){
        .level = (ev != NULL) ? ev->state_of_charge : zmk_battery_state_of_charge(),
#if IS_ENABLED(CONFIG_USB_DEVICE_STACK)
        .usb_present = zmk_usb_is_powered(),
#endif /* IS_ENABLED(CONFIG_USB_DEVICE_STACK) */
    };
}

ZMK_DISPLAY_WIDGET_LISTENER(widget_battery_status, struct battery_status_state,
                            battery_status_update_cb, battery_status_get_state)

ZMK_SUBSCRIPTION(widget_battery_status, zmk_battery_state_changed);
#if IS_ENABLED(CONFIG_USB_DEVICE_STACK)
ZMK_SUBSCRIPTION(widget_battery_status, zmk_usb_conn_state_changed);
#endif /* IS_ENABLED(CONFIG_USB_DEVICE_STACK) */

static void set_output_status(struct zmk_widget_status *widget,
                              const struct output_status_state *state) {
    widget->state.selected_endpoint = state->selected_endpoint;
    widget->state.active_profile_index = state->active_profile_index;
    widget->state.active_profile_connected = state->active_profile_connected;
    widget->state.active_profile_bonded = state->active_profile_bonded;
    for (uint8_t i = 0; i < KEYPOINT_STATUS_PROFILE_COUNT; i++) {
        widget->state.profile_connected[i] = state->profile_connected[i];
        widget->state.profile_bonded[i] = state->profile_bonded[i];
    }

    draw_top(widget->obj, widget->cbuf, &widget->state);
    draw_middle(widget->obj, widget->cbuf2, &widget->state);
}

static void output_status_update_cb(struct output_status_state state) {
    struct zmk_widget_status *widget;
    SYS_SLIST_FOR_EACH_CONTAINER(&widgets, widget, node) { set_output_status(widget, &state); }
}

static struct output_status_state output_status_get_state(const zmk_event_t *_eh) {
    struct output_status_state state = {
        .selected_endpoint = zmk_endpoints_selected(),
        .active_profile_index = zmk_ble_active_profile_index(),
        .active_profile_connected = zmk_ble_active_profile_is_connected(),
        .active_profile_bonded = !zmk_ble_active_profile_is_open(),
    };

    for (uint8_t i = 0; i < KEYPOINT_STATUS_PROFILE_COUNT; i++) {
        state.profile_connected[i] = zmk_ble_profile_is_connected(i);
        state.profile_bonded[i] = !zmk_ble_profile_is_open(i);
    }

    return state;
}

ZMK_DISPLAY_WIDGET_LISTENER(widget_output_status, struct output_status_state,
                            output_status_update_cb, output_status_get_state)
ZMK_SUBSCRIPTION(widget_output_status, zmk_endpoint_changed);

#if IS_ENABLED(CONFIG_USB_DEVICE_STACK)
ZMK_SUBSCRIPTION(widget_output_status, zmk_usb_conn_state_changed);
#endif
#if defined(CONFIG_ZMK_BLE)
ZMK_SUBSCRIPTION(widget_output_status, zmk_ble_active_profile_changed);
#endif

static void set_layer_status(struct zmk_widget_status *widget, struct layer_status_state state) {
    widget->state.layer_index = state.index;
    widget->state.layer_label = state.label;

    draw_middle(widget->obj, widget->cbuf2, &widget->state);
}

static void layer_status_update_cb(struct layer_status_state state) {
    struct zmk_widget_status *widget;
    SYS_SLIST_FOR_EACH_CONTAINER(&widgets, widget, node) { set_layer_status(widget, state); }
}

static struct layer_status_state layer_status_get_state(const zmk_event_t *eh) {
    uint8_t index = zmk_keymap_highest_layer_active();
    return (struct layer_status_state){.index = index, .label = zmk_keymap_layer_name(index)};
}

ZMK_DISPLAY_WIDGET_LISTENER(widget_layer_status, struct layer_status_state, layer_status_update_cb,
                            layer_status_get_state)

ZMK_SUBSCRIPTION(widget_layer_status, zmk_layer_state_changed);

int zmk_widget_status_init(struct zmk_widget_status *widget, lv_obj_t *parent) {
    widget->obj = lv_obj_create(parent);
    lv_obj_set_size(widget->obj, 144, 72);

    // top battery status and output, wpm status
    lv_obj_t *top = lv_canvas_create(widget->obj);
    lv_obj_align(top, LV_ALIGN_BOTTOM_LEFT, 0, 0);
    lv_canvas_set_buffer(top, widget->cbuf, CANVAS_SIZE, CANVAS_SIZE, LV_IMG_CF_TRUE_COLOR);
    // middle connecion status
    lv_obj_t *middle = lv_canvas_create(widget->obj);
    lv_obj_align(middle, LV_ALIGN_TOP_LEFT, 68, 0);
    lv_canvas_set_buffer(middle, widget->cbuf2, CANVAS_SIZE, CANVAS_SIZE, LV_IMG_CF_TRUE_COLOR);

    /* One subscription covers every widget on the list, so register on the
     * first init only. */
    if (sys_slist_is_empty(&widgets)) {
        keypoint_live_data_subscribe(live_data_changed);
    }
    sys_slist_append(&widgets, &widget->node);

    widget_battery_status_init();
    widget_output_status_init();
    widget_layer_status_init();

    return 0;
}

lv_obj_t *zmk_widget_status_obj(struct zmk_widget_status *widget) { return widget->obj; }
