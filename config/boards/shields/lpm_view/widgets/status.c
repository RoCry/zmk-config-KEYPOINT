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

#define LIVE_DATA_ICON_SIZE 8
#define LIVE_DATA_ICON_SCALE 1

static const char icon_sun[LIVE_DATA_ICON_SIZE][LIVE_DATA_ICON_SIZE + 1] = {
    "00100100", "00011000", "10111101", "01111110",
    "01111110", "10111101", "00011000", "00100100",
};

static const char icon_cloud[LIVE_DATA_ICON_SIZE][LIVE_DATA_ICON_SIZE + 1] = {
    "00000000", "00111000", "01111100", "11111110",
    "11111110", "01111100", "00000000", "00000000",
};

static const char icon_rain[LIVE_DATA_ICON_SIZE][LIVE_DATA_ICON_SIZE + 1] = {
    "00111000", "01111100", "11111110", "01111100",
    "00000000", "01001000", "10010000", "00100100",
};

static const char icon_temp[LIVE_DATA_ICON_SIZE][LIVE_DATA_ICON_SIZE + 1] = {
    "00110000", "01001000", "01001000", "01001000",
    "01001000", "10000100", "10000100", "01111000",
};

static const char icon_warn[LIVE_DATA_ICON_SIZE][LIVE_DATA_ICON_SIZE + 1] = {
    "00010000", "00111000", "00111000", "01101100",
    "01101100", "11111110", "11101110", "11111110",
};

static const char icon_code[LIVE_DATA_ICON_SIZE][LIVE_DATA_ICON_SIZE + 1] = {
    "10000010", "01000100", "00101000", "00010000",
    "00101000", "01000100", "10000010", "00010000",
};

static const char icon_time[LIVE_DATA_ICON_SIZE][LIVE_DATA_ICON_SIZE + 1] = {
    "00111100", "01000010", "10010001", "10010001",
    "10011101", "10000001", "01000010", "00111100",
};

static const char icon_codex[LIVE_DATA_ICON_SIZE][LIVE_DATA_ICON_SIZE + 1] = {
    "00111100", "01011010", "10100101", "10111101",
    "10111101", "10100101", "01011010", "00111100",
};

static const char icon_claude[LIVE_DATA_ICON_SIZE][LIVE_DATA_ICON_SIZE + 1] = {
    "00010000", "00010000", "01010100", "00111000",
    "11111110", "00111000", "01010100", "00010000",
};

static void draw_bitmap_icon(lv_obj_t *canvas, lv_coord_t x, lv_coord_t y,
                             const lv_draw_rect_dsc_t *icon_dsc,
                             const char rows[LIVE_DATA_ICON_SIZE][LIVE_DATA_ICON_SIZE + 1]) {
    for (int row = 0; row < LIVE_DATA_ICON_SIZE; row++) {
        for (int column = 0; column < LIVE_DATA_ICON_SIZE; column++) {
            if (rows[row][column] == '1') {
                lv_canvas_draw_rect(canvas, x + (column * LIVE_DATA_ICON_SCALE),
                                    y + (row * LIVE_DATA_ICON_SCALE), LIVE_DATA_ICON_SCALE,
                                    LIVE_DATA_ICON_SCALE, icon_dsc);
            }
        }
    }
}

static void draw_live_data_icon(lv_obj_t *canvas, enum keypoint_live_data_icon icon,
                                const lv_draw_rect_dsc_t *icon_dsc) {
    const char(*rows)[LIVE_DATA_ICON_SIZE + 1] = NULL;

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

    draw_bitmap_icon(canvas, 2, 55, icon_dsc, rows);
}

static void draw_live_data_panel(lv_obj_t *canvas, const lv_draw_label_dsc_t *label_dsc,
                                 const lv_draw_line_dsc_t *divider_dsc,
                                 const lv_draw_rect_dsc_t *icon_dsc) {
    struct keypoint_live_data_snapshot snapshot = keypoint_live_data_snapshot_get();
    lv_draw_label_dsc_t live_label_dsc = *label_dsc;
    lv_draw_line_dsc_t live_divider_dsc = *divider_dsc;
    lv_draw_rect_dsc_t live_icon_dsc = *icon_dsc;

    if (snapshot.stale) {
        live_label_dsc.opa = LV_OPA_50;
        live_divider_dsc.opa = LV_OPA_50;
        live_icon_dsc.bg_opa = LV_OPA_50;
    }

    draw_live_data_icon(canvas, snapshot.icon, &live_icon_dsc);

    for (int i = 0; i < KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT; i++) {
        lv_canvas_draw_text(canvas, 3, 23 + (i * 11), 67, &live_label_dsc,
                            snapshot.lines[i]);
    }

    lv_point_t divider_points[] = {{0, 65}, {70, 65}};
    lv_canvas_draw_line(canvas, divider_points, 2, &live_divider_dsc);
}

static void draw_top(lv_obj_t *widget, lv_color_t cbuf[], const struct status_state *state) {
    lv_obj_t *canvas = lv_obj_get_child(widget, 0);

    lv_draw_label_dsc_t label_dsc;
    init_label_dsc(&label_dsc, LVGL_FOREGROUND, &lv_font_montserrat_16, LV_TEXT_ALIGN_RIGHT);
    lv_draw_label_dsc_t label_dsc_wpm;
    init_label_dsc(&label_dsc_wpm, LVGL_FOREGROUND, &lv_font_unscii_8, LV_TEXT_ALIGN_RIGHT);
    lv_draw_rect_dsc_t rect_black_dsc;
    init_rect_dsc(&rect_black_dsc, LVGL_BACKGROUND);
    lv_draw_line_dsc_t line_dsc;
    init_line_dsc(&line_dsc, LVGL_FOREGROUND, 1);
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

    draw_live_data_panel(canvas, &label_dsc_wpm, &line_dsc, &icon_dsc);

    // Rotate canvas
    rotate_canvas(canvas, cbuf);
}

void keypoint_live_data_refresh_displays(void) {
    struct zmk_widget_status *widget;
    SYS_SLIST_FOR_EACH_CONTAINER(&widgets, widget, node) {
        draw_top(widget->obj, widget->cbuf, &widget->state);
    }
}

static void draw_rect_outline(lv_obj_t *canvas, lv_coord_t x, lv_coord_t y, lv_coord_t width,
                              lv_coord_t height, const lv_draw_rect_dsc_t *rect_dsc) {
    lv_canvas_draw_rect(canvas, x, y, width, 1, rect_dsc);
    lv_canvas_draw_rect(canvas, x, y + height - 1, width, 1, rect_dsc);
    lv_canvas_draw_rect(canvas, x, y, 1, height, rect_dsc);
    lv_canvas_draw_rect(canvas, x + width - 1, y, 1, height, rect_dsc);
}

static void draw_plus_marker(lv_obj_t *canvas, lv_coord_t x, lv_coord_t y,
                             const lv_draw_rect_dsc_t *rect_dsc) {
    lv_canvas_draw_rect(canvas, x + 2, y, 1, 5, rect_dsc);
    lv_canvas_draw_rect(canvas, x, y + 2, 5, 1, rect_dsc);
}

static void draw_profile_slot(lv_obj_t *canvas, const struct status_state *state, uint8_t index,
                              lv_coord_t x, lv_coord_t y,
                              const lv_draw_rect_dsc_t *foreground_rect_dsc,
                              const lv_draw_rect_dsc_t *background_rect_dsc,
                              const lv_draw_label_dsc_t *foreground_label_dsc,
                              const lv_draw_label_dsc_t *background_label_dsc) {
    const bool active = index == state->active_profile_index;
    const bool connected = state->profile_connected[index];
    const bool bonded = state->profile_bonded[index];
    const lv_draw_rect_dsc_t *status_rect_dsc = active ? background_rect_dsc : foreground_rect_dsc;
    char label[2];

    if (active) {
        lv_canvas_draw_rect(canvas, x, y, 29, 23, foreground_rect_dsc);
    } else if (bonded) {
        draw_rect_outline(canvas, x, y, 29, 23, foreground_rect_dsc);
    } else {
        lv_canvas_draw_rect(canvas, x, y, 7, 1, foreground_rect_dsc);
        lv_canvas_draw_rect(canvas, x, y, 1, 7, foreground_rect_dsc);
        lv_canvas_draw_rect(canvas, x + 22, y, 7, 1, foreground_rect_dsc);
        lv_canvas_draw_rect(canvas, x + 28, y, 1, 7, foreground_rect_dsc);
        lv_canvas_draw_rect(canvas, x, y + 22, 7, 1, foreground_rect_dsc);
        lv_canvas_draw_rect(canvas, x, y + 16, 1, 7, foreground_rect_dsc);
        lv_canvas_draw_rect(canvas, x + 22, y + 22, 7, 1, foreground_rect_dsc);
        lv_canvas_draw_rect(canvas, x + 28, y + 16, 1, 7, foreground_rect_dsc);
    }

    snprintk(label, sizeof(label), "%u", index + 1);
    lv_canvas_draw_text(canvas, x + 2, y + 2, 16, active ? background_label_dsc : foreground_label_dsc,
                        label);

    if (connected) {
        lv_canvas_draw_rect(canvas, x + 21, y + 7, 5, 5, status_rect_dsc);
    } else if (bonded) {
        draw_rect_outline(canvas, x + 21, y + 7, 5, 5, status_rect_dsc);
    } else {
        draw_plus_marker(canvas, x + 21, y + 7, status_rect_dsc);
    }
}

static void draw_profile_grid(lv_obj_t *canvas, const struct status_state *state,
                              const lv_draw_rect_dsc_t *foreground_rect_dsc,
                              const lv_draw_rect_dsc_t *background_rect_dsc,
                              const lv_draw_label_dsc_t *foreground_label_dsc,
                              const lv_draw_label_dsc_t *background_label_dsc) {
    static const lv_coord_t slot_offsets[KEYPOINT_STATUS_PROFILE_COUNT][2] = {
        {4, 8},
        {39, 8},
        {4, 41},
        {39, 41},
    };

    for (uint8_t i = 0; i < KEYPOINT_STATUS_PROFILE_COUNT; i++) {
        draw_profile_slot(canvas, state, i, slot_offsets[i][0], slot_offsets[i][1],
                          foreground_rect_dsc, background_rect_dsc, foreground_label_dsc,
                          background_label_dsc);
    }
}

static void draw_middle(lv_obj_t *widget, lv_color_t cbuf[], const struct status_state *state) {
    lv_obj_t *canvas = lv_obj_get_child(widget, 1);

    lv_draw_rect_dsc_t rect_black_dsc;
    init_rect_dsc(&rect_black_dsc, LVGL_BACKGROUND);
    lv_draw_rect_dsc_t rect_white_dsc;
    init_rect_dsc(&rect_white_dsc, LVGL_FOREGROUND);
    lv_draw_label_dsc_t label_dsc;
    init_label_dsc(&label_dsc, LVGL_FOREGROUND, &lv_font_montserrat_14, LV_TEXT_ALIGN_CENTER);
    lv_draw_label_dsc_t label_dsc_black;
    init_label_dsc(&label_dsc_black, LVGL_BACKGROUND, &lv_font_montserrat_14, LV_TEXT_ALIGN_CENTER);

    // Fill background.
    lv_canvas_draw_rect(canvas, 0, 0, CANVAS_SIZE, CANVAS_SIZE, &rect_black_dsc);
    draw_profile_grid(canvas, state, &rect_white_dsc, &rect_black_dsc, &label_dsc,
                      &label_dsc_black);

    rotate_canvas(canvas, cbuf);
}

static const char *layer_chip_text(const struct status_state *state, char *fallback,
                                   size_t fallback_size) {
    if (state->layer_index == 0) {
        return "BASE";
    }

    if (state->layer_label != NULL) {
        return state->layer_label;
    }

    snprintk(fallback, fallback_size, "LAYER %u", state->layer_index);
    return fallback;
}

static void draw_layer_chip(lv_obj_t *canvas, const struct status_state *state,
                            const lv_draw_rect_dsc_t *rect_dsc,
                            const lv_draw_label_dsc_t *label_dsc) {
    char fallback[10] = {};
    const char *label = layer_chip_text(state, fallback, sizeof(fallback));

    draw_rect_outline(canvas, 2, 20, 68, 28, rect_dsc);
    lv_canvas_draw_text(canvas, 4, 24, 64, label_dsc, label);
}

static void draw_bottom(lv_obj_t *widget, lv_color_t cbuf[], const struct status_state *state) {
    lv_obj_t *canvas = lv_obj_get_child(widget, 2);

    lv_draw_rect_dsc_t rect_black_dsc;
    init_rect_dsc(&rect_black_dsc, LVGL_BACKGROUND);
    lv_draw_rect_dsc_t rect_white_dsc;
    init_rect_dsc(&rect_white_dsc, LVGL_FOREGROUND);
    lv_draw_label_dsc_t label_dsc;
    init_label_dsc(&label_dsc, LVGL_FOREGROUND, &lv_font_montserrat_14, LV_TEXT_ALIGN_CENTER);

    // Fill background
    lv_canvas_draw_rect(canvas, 0, 0, CANVAS_SIZE, CANVAS_SIZE, &rect_black_dsc);

    draw_layer_chip(canvas, state, &rect_white_dsc, &label_dsc);

    // Rotate canvas
    rotate_canvas(canvas, cbuf);
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

    draw_bottom(widget->obj, widget->cbuf3, &widget->state);
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
    // bottom layer status
    lv_obj_t *bottom = lv_canvas_create(widget->obj);
    lv_obj_align(bottom, LV_ALIGN_TOP_LEFT, 128, 0);
    lv_canvas_set_buffer(bottom, widget->cbuf3, CANVAS_SIZE, CANVAS_SIZE, LV_IMG_CF_TRUE_COLOR);

    sys_slist_append(&widgets, &widget->node);
    widget_battery_status_init();
    widget_output_status_init();
    widget_layer_status_init();

    return 0;
}

lv_obj_t *zmk_widget_status_obj(struct zmk_widget_status *widget) { return widget->obj; }
