#include "theme.h"

lv_color_t keypoint_color(enum keypoint_color color) {
    return lv_color_make((color & 4) ? 255 : 0, (color & 2) ? 255 : 0,
                         (color & 1) ? 255 : 0);
}

enum keypoint_color keypoint_card_accent(enum keypoint_live_data_icon icon) {
    switch (icon) {
    case KEYPOINT_LIVE_DATA_ICON_CLAUDE: return KP_CYAN;
    case KEYPOINT_LIVE_DATA_ICON_CODEX: return KP_BLUE;
    case KEYPOINT_LIVE_DATA_ICON_SUN: return KP_YELLOW;
    case KEYPOINT_LIVE_DATA_ICON_CLOUD: return KP_CYAN;
    case KEYPOINT_LIVE_DATA_ICON_RAIN: return KP_BLUE;
    case KEYPOINT_LIVE_DATA_ICON_TEMP: return KP_MAGENTA;
    case KEYPOINT_LIVE_DATA_ICON_WARN: return KP_YELLOW;
    case KEYPOINT_LIVE_DATA_ICON_CODE: return KP_GREEN;
    case KEYPOINT_LIVE_DATA_ICON_TIME: return KP_MAGENTA;
    default: return KP_BLUE;
    }
}

enum keypoint_color keypoint_row_color(enum keypoint_live_data_row_role role,
                                      enum keypoint_color accent) {
    switch (role) {
    case KEYPOINT_LIVE_DATA_ROW_ROLE_POSITIVE: return KP_GREEN;
    case KEYPOINT_LIVE_DATA_ROW_ROLE_ATTENTION: return KP_CYAN;
    case KEYPOINT_LIVE_DATA_ROW_ROLE_WARNING: return KP_YELLOW;
    case KEYPOINT_LIVE_DATA_ROW_ROLE_ERROR: return KP_RED;
    default: return accent;
    }
}

enum keypoint_color keypoint_health_color(const struct keypoint_live_data_snapshot *snapshot) {
    if (snapshot->stale) return KP_MAGENTA;
    switch (snapshot->led_hint) {
    case KEYPOINT_LIVE_DATA_LED_HINT_ACTIVE: return KP_BLUE;
    case KEYPOINT_LIVE_DATA_LED_HINT_ATTENTION: return KP_CYAN;
    case KEYPOINT_LIVE_DATA_LED_HINT_WARNING: return KP_YELLOW;
    case KEYPOINT_LIVE_DATA_LED_HINT_ERROR: return KP_RED;
    default: return snapshot->icon == KEYPOINT_LIVE_DATA_ICON_WARN ? KP_YELLOW : KP_GREEN;
    }
}

lv_color_t keypoint_on_color(enum keypoint_color background) {
    return keypoint_color(background == KP_BLUE || background == KP_BLACK ? KP_WHITE : KP_BLACK);
}
