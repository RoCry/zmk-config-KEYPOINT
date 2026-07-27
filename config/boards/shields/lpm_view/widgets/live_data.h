/*
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#define KEYPOINT_LIVE_DATA_PREFIX "KP3|"
#define KEYPOINT_LIVE_DATA_ICON_MAX 8
#define KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT 6
#define KEYPOINT_LIVE_DATA_LINE_MAX 9
#define KEYPOINT_LIVE_DATA_STALE_MS 360000
#define KEYPOINT_LIVE_DATA_GENERATION_FIELD_MAX 2
#define KEYPOINT_LIVE_DATA_PAGE_MAX 8
#define KEYPOINT_LIVE_DATA_PAGE_FIELD_MAX 1 /* PAGE_MAX <= 9 -> single digit */
#define KEYPOINT_LIVE_DATA_LED_HINT_FIELD_MAX 1
#define KEYPOINT_LIVE_DATA_FRAME_MAX                                                               \
    ((sizeof(KEYPOINT_LIVE_DATA_PREFIX) - 1) +                                                     \
     (KEYPOINT_LIVE_DATA_GENERATION_FIELD_MAX + 1) +                                               \
     ((KEYPOINT_LIVE_DATA_PAGE_FIELD_MAX + 1) * 2) +                                               \
     (KEYPOINT_LIVE_DATA_LED_HINT_FIELD_MAX + 1) +                                                 \
     KEYPOINT_LIVE_DATA_ICON_MAX +                                                                 \
     (KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT * KEYPOINT_LIVE_DATA_LINE_MAX) +                          \
     KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT)

enum keypoint_live_data_icon {
    KEYPOINT_LIVE_DATA_ICON_NONE,
    KEYPOINT_LIVE_DATA_ICON_SUN,
    KEYPOINT_LIVE_DATA_ICON_CLOUD,
    KEYPOINT_LIVE_DATA_ICON_RAIN,
    KEYPOINT_LIVE_DATA_ICON_TEMP,
    KEYPOINT_LIVE_DATA_ICON_WARN,
    KEYPOINT_LIVE_DATA_ICON_CODE,
    KEYPOINT_LIVE_DATA_ICON_TIME,
    KEYPOINT_LIVE_DATA_ICON_CODEX,
    KEYPOINT_LIVE_DATA_ICON_CLAUDE,
};

enum keypoint_live_data_led_hint {
    KEYPOINT_LIVE_DATA_LED_HINT_NONE,
    KEYPOINT_LIVE_DATA_LED_HINT_ACTIVE,
    KEYPOINT_LIVE_DATA_LED_HINT_ATTENTION,
    KEYPOINT_LIVE_DATA_LED_HINT_WARNING,
    KEYPOINT_LIVE_DATA_LED_HINT_ERROR,
};

/* The one LED semantic LiveData exposes: the producer's LED hint, staleness and
 * the card's own icon emphasis folded into a single value. LiveData is the only
 * module that decides this. LED hardware modules render a level and hold no
 * opinion about icons or staleness, so a new icon never reaches them.
 *
 * Every level is a distinct pattern on the device -- do not merge two that look
 * redundant here. Ordered by rising emphasis. */
enum keypoint_live_data_attention {
    KEYPOINT_LIVE_DATA_ATTENTION_IDLE,             /* a card with nothing to say */
    KEYPOINT_LIVE_DATA_ATTENTION_NO_DATA,          /* no deck has ever arrived */
    KEYPOINT_LIVE_DATA_ATTENTION_HEARTBEAT_SINGLE, /* unhinted long-running session */
    KEYPOINT_LIVE_DATA_ATTENTION_HEARTBEAT_DOUBLE, /* ditto, a second session identity */
    KEYPOINT_LIVE_DATA_ATTENTION_ACTIVE,
    KEYPOINT_LIVE_DATA_ATTENTION_CAUTION, /* unhinted card that is itself a warning */
    KEYPOINT_LIVE_DATA_ATTENTION_ATTENTION,
    KEYPOINT_LIVE_DATA_ATTENTION_WARNING,
    KEYPOINT_LIVE_DATA_ATTENTION_STALE, /* deck aged past KEYPOINT_LIVE_DATA_STALE_MS */
    KEYPOINT_LIVE_DATA_ATTENTION_ERROR,
};

struct keypoint_live_data_snapshot {
    enum keypoint_live_data_icon icon;
    enum keypoint_live_data_led_hint led_hint;
    enum keypoint_live_data_attention attention;
    char lines[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1];
    bool has_data;
    bool stale;
    uint8_t generation;
    uint8_t view_index;  /* 0-based index of the page being shown */
    uint8_t total_pages; /* current deck size (1 when empty/NO DATA) */
};

/* What a snapshot-changed notification is about. */
enum keypoint_live_data_change {
    KEYPOINT_LIVE_DATA_CHANGE_REFRESH,    /* same deck: page moved, or staleness tipped */
    KEYPOINT_LIVE_DATA_CHANGE_GENERATION, /* a new generation replaced the deck */
};

/* Snapshot subscriber, run on the display work queue after the snapshot has
 * already changed. Read the new state with keypoint_live_data_snapshot_get(). */
typedef void (*keypoint_live_data_listener_t)(enum keypoint_live_data_change change);

int keypoint_live_data_parse(const uint8_t *data, uint16_t len, uint8_t *generation,
                             uint8_t *idx, uint8_t *total, enum keypoint_live_data_icon *icon,
                             enum keypoint_live_data_led_hint *led_hint,
                             char out[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT]
                                     [KEYPOINT_LIVE_DATA_LINE_MAX + 1]);
struct keypoint_live_data_snapshot keypoint_live_data_snapshot_get(void);

/* Register a subscriber. Init-time only and never unregistered: the seam is
 * one-way, so LiveData links without knowing any of its consumers. */
void keypoint_live_data_subscribe(keypoint_live_data_listener_t listener);
