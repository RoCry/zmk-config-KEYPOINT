/*
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 */

#include <errno.h>
#include <stddef.h>
#include <string.h>

#include "live_data_core.h"

static bool is_printable_ascii(uint8_t ch) { return ch >= 0x20 && ch <= 0x7e; }

static int hex_nibble(uint8_t ch) {
    if (ch >= '0' && ch <= '9') {
        return ch - '0';
    }
    if (ch >= 'A' && ch <= 'F') {
        return 10 + ch - 'A';
    }
    return -EINVAL;
}

static int icon_from_field(const char *field, enum keypoint_live_data_icon *icon) {
    if (strcmp(field, "NONE") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_NONE;
    } else if (strcmp(field, "SUN") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_SUN;
    } else if (strcmp(field, "CLOUD") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_CLOUD;
    } else if (strcmp(field, "RAIN") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_RAIN;
    } else if (strcmp(field, "TEMP") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_TEMP;
    } else if (strcmp(field, "WARN") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_WARN;
    } else if (strcmp(field, "CODE") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_CODE;
    } else if (strcmp(field, "TIME") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_TIME;
    } else if (strcmp(field, "CODEX") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_CODEX;
    } else if (strcmp(field, "CLAUDE") == 0) {
        *icon = KEYPOINT_LIVE_DATA_ICON_CLAUDE;
    } else {
        return -EINVAL;
    }

    return 0;
}

static int led_hint_from_field(const char *field, enum keypoint_live_data_led_hint *led_hint) {
    if (strcmp(field, "0") == 0) {
        *led_hint = KEYPOINT_LIVE_DATA_LED_HINT_NONE;
    } else if (strcmp(field, "1") == 0) {
        *led_hint = KEYPOINT_LIVE_DATA_LED_HINT_ACTIVE;
    } else if (strcmp(field, "2") == 0) {
        *led_hint = KEYPOINT_LIVE_DATA_LED_HINT_ATTENTION;
    } else if (strcmp(field, "3") == 0) {
        *led_hint = KEYPOINT_LIVE_DATA_LED_HINT_WARNING;
    } else if (strcmp(field, "4") == 0) {
        *led_hint = KEYPOINT_LIVE_DATA_LED_HINT_ERROR;
    } else {
        return -EINVAL;
    }

    return 0;
}

static uint8_t received_mask_for_total(uint8_t total) { return (uint8_t)((1U << total) - 1U); }

static void copy_lines(char dst[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1],
                       const char src[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT]
                                     [KEYPOINT_LIVE_DATA_LINE_MAX + 1]) {
    for (int i = 0; i < KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT; i++) {
        strncpy(dst[i], src[i], KEYPOINT_LIVE_DATA_LINE_MAX);
        dst[i][KEYPOINT_LIVE_DATA_LINE_MAX] = '\0';
    }
}

int keypoint_live_data_parse(const uint8_t *data, uint16_t len, uint8_t *generation,
                             uint8_t *idx, uint8_t *total, enum keypoint_live_data_icon *icon,
                             enum keypoint_live_data_led_hint *led_hint,
                             char out[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT]
                                     [KEYPOINT_LIVE_DATA_LINE_MAX + 1]) {
    if (data == NULL || generation == NULL || idx == NULL || total == NULL || icon == NULL ||
        led_hint == NULL || out == NULL || len > KEYPOINT_LIVE_DATA_FRAME_MAX) {
        return -EINVAL;
    }

    const size_t prefix_len = sizeof(KEYPOINT_LIVE_DATA_PREFIX) - 1;
    if (len < prefix_len || memcmp(data, KEYPOINT_LIVE_DATA_PREFIX, prefix_len) != 0) {
        return -EINVAL;
    }

    uint16_t generation_val = 0;
    char icon_field[KEYPOINT_LIVE_DATA_ICON_MAX + 1] = {};
    char led_hint_field[KEYPOINT_LIVE_DATA_LED_HINT_FIELD_MAX + 1] = {};
    memset(out, 0, KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT * (KEYPOINT_LIVE_DATA_LINE_MAX + 1));

    /* Field layout after the prefix:
     * 0=GEN, 1=IDX, 2=TOTAL, 3=ICON, 4=LED, 5..10=lines. */
    uint16_t idx_val = 0, total_val = 0;
    size_t field = 0;
    size_t column = 0;

    for (size_t i = prefix_len; i < len; i++) {
        const uint8_t ch = data[i];

        if (ch == '|') {
            if (field >= 4 + KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT) {
                return -EINVAL;
            }
            if (field == 0 && column != KEYPOINT_LIVE_DATA_GENERATION_FIELD_MAX) {
                return -EINVAL; /* GEN is exactly two uppercase hex digits */
            }
            if ((field == 1 || field == 2) && column == 0) {
                return -EINVAL; /* empty IDX/TOTAL field */
            }
            if (field == 4 && column != KEYPOINT_LIVE_DATA_LED_HINT_FIELD_MAX) {
                return -EINVAL; /* LED hint is exactly one digit */
            }
            field++;
            column = 0;
            continue;
        }

        if (field == 0) {
            int nibble = hex_nibble(ch);
            if (nibble < 0 || column >= KEYPOINT_LIVE_DATA_GENERATION_FIELD_MAX) {
                return -EINVAL;
            }
            generation_val = (uint16_t)((generation_val << 4) | (uint8_t)nibble);
            column++;
            continue;
        }

        if (field == 1 || field == 2) {
            if (ch < '0' || ch > '9' || column >= KEYPOINT_LIVE_DATA_PAGE_FIELD_MAX) {
                return -EINVAL;
            }
            uint16_t *acc = (field == 1) ? &idx_val : &total_val;
            *acc = (uint16_t)(*acc * 10 + (ch - '0'));
            column++;
            continue;
        }

        const size_t field_max = (field == 3)   ? KEYPOINT_LIVE_DATA_ICON_MAX
                                 : (field == 4) ? KEYPOINT_LIVE_DATA_LED_HINT_FIELD_MAX
                                                : KEYPOINT_LIVE_DATA_LINE_MAX;
        if (!is_printable_ascii(ch) || column >= field_max) {
            return -EINVAL;
        }
        if (field == 3) {
            icon_field[column++] = (char)ch;
        } else if (field == 4) {
            led_hint_field[column++] = (char)ch;
        } else {
            out[field - 5][column++] = (char)ch;
        }
    }

    if (field != 4 + KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT) {
        return -EINVAL;
    }
    if (total_val < 1 || total_val > KEYPOINT_LIVE_DATA_PAGE_MAX || idx_val >= total_val) {
        return -EINVAL;
    }

    *generation = (uint8_t)generation_val;
    *idx = (uint8_t)idx_val;
    *total = (uint8_t)total_val;
    int ret = icon_from_field(icon_field, icon);
    if (ret < 0) {
        return ret;
    }
    return led_hint_from_field(led_hint_field, led_hint);
}

bool keypoint_live_data_core_store(struct keypoint_live_data_deck *deck, uint8_t generation,
                                   uint8_t idx, uint8_t total, enum keypoint_live_data_icon icon,
                                   enum keypoint_live_data_led_hint led_hint,
                                   char lines[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT]
                                             [KEYPOINT_LIVE_DATA_LINE_MAX + 1],
                                   int64_t now_ms) {
    if (!deck->pending_active || generation != deck->pending_generation ||
        total != deck->pending_total) {
        memset(deck->pending_cards, 0, sizeof(deck->pending_cards));
        deck->pending_generation = generation;
        deck->pending_total = total;
        deck->pending_mask = 0;
        deck->pending_active = true;
    }

    struct keypoint_live_data_card *card = &deck->pending_cards[idx];
    card->icon = icon;
    card->led_hint = led_hint;
    copy_lines(card->lines, lines);
    card->has_data = true;
    card->update_ms = now_ms;
    deck->pending_mask |= (uint8_t)(1U << idx);

    if (deck->pending_mask != received_mask_for_total(deck->pending_total)) {
        return false;
    }

    memcpy(deck->cards, deck->pending_cards, sizeof(deck->cards));
    deck->generation = deck->pending_generation;
    deck->total = deck->pending_total;
    deck->pending_active = false;
    deck->pending_mask = 0;

    if (deck->view_index >= deck->total) {
        deck->view_index = deck->total - 1;
    }

    return true;
}

/* Fold LED hint, staleness and icon emphasis into the one LED semantic. An
 * explicit hint always wins; an unhinted card falls back to what its icon says
 * about itself. Icons with nothing to say leave the LED dark. */
static enum keypoint_live_data_attention
attention_for(const struct keypoint_live_data_snapshot *snapshot) {
    if (!snapshot->has_data) {
        return KEYPOINT_LIVE_DATA_ATTENTION_NO_DATA;
    }
    if (snapshot->stale) {
        return KEYPOINT_LIVE_DATA_ATTENTION_STALE;
    }

    switch (snapshot->led_hint) {
    case KEYPOINT_LIVE_DATA_LED_HINT_ERROR:
        return KEYPOINT_LIVE_DATA_ATTENTION_ERROR;
    case KEYPOINT_LIVE_DATA_LED_HINT_WARNING:
        return KEYPOINT_LIVE_DATA_ATTENTION_WARNING;
    case KEYPOINT_LIVE_DATA_LED_HINT_ATTENTION:
        return KEYPOINT_LIVE_DATA_ATTENTION_ATTENTION;
    case KEYPOINT_LIVE_DATA_LED_HINT_ACTIVE:
        return KEYPOINT_LIVE_DATA_ATTENTION_ACTIVE;
    case KEYPOINT_LIVE_DATA_LED_HINT_NONE:
        break;
    }

    switch (snapshot->icon) {
    case KEYPOINT_LIVE_DATA_ICON_CLAUDE:
        return KEYPOINT_LIVE_DATA_ATTENTION_HEARTBEAT_SINGLE;
    case KEYPOINT_LIVE_DATA_ICON_CODEX:
        return KEYPOINT_LIVE_DATA_ATTENTION_HEARTBEAT_DOUBLE;
    case KEYPOINT_LIVE_DATA_ICON_WARN:
        return KEYPOINT_LIVE_DATA_ATTENTION_CAUTION;
    default:
        return KEYPOINT_LIVE_DATA_ATTENTION_IDLE;
    }
}

struct keypoint_live_data_snapshot
keypoint_live_data_core_snapshot(const struct keypoint_live_data_deck *deck, int64_t now_ms) {
    struct keypoint_live_data_snapshot snapshot = {};

    snapshot.total_pages = deck->total > 0 ? deck->total : 1;
    snapshot.view_index = deck->view_index;
    snapshot.generation = deck->generation;
    const struct keypoint_live_data_card *card =
        (deck->total > 0) ? &deck->cards[deck->view_index] : NULL;

    if (card != NULL && card->has_data) {
        snapshot.icon = card->icon;
        snapshot.led_hint = card->led_hint;
        snapshot.has_data = true;
        const int64_t age_ms = now_ms - card->update_ms;
        snapshot.stale = age_ms >= KEYPOINT_LIVE_DATA_STALE_MS;
        copy_lines(snapshot.lines, card->lines);
    } else {
        snapshot.icon = KEYPOINT_LIVE_DATA_ICON_WARN;
        strcpy(snapshot.lines[0], "NO DATA");
        strcpy(snapshot.lines[1], "WAITING");
    }

    snapshot.attention = attention_for(&snapshot);

    return snapshot;
}

bool keypoint_live_data_core_page_advance(struct keypoint_live_data_deck *deck, int delta) {
    if (deck->total <= 1) {
        return false;
    }

    deck->view_index = (uint8_t)((deck->view_index + deck->total + delta) % deck->total);
    return true;
}
