/*
 *
 * Copyright (c) 2026 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 *
 */

#pragma once

/* The live-data icon sits in the top status row, between the battery
 * (ends x=32) and the endpoint symbol (starts x>=52). Drawn at 2x so its 16px
 * box matches the battery (16px) and endpoint symbol (~14px) heights instead
 * of looking dwarfed; centred in the gap and top-aligned with the battery. */
#define KEYPOINT_LIVE_ICON_SIZE 8
#define KEYPOINT_LIVE_ICON_SCALE 2
#define KEYPOINT_LIVE_ICON_X 34
#define KEYPOINT_LIVE_ICON_Y 0
/* Top lines sit low (text y=26) and extra lines start at the very top of the
 * middle canvas, so the glass shows an even rhythm: ~10px below the status
 * row, 4px between lines, ~10px across the canvas seam. The band spans the
 * full 72px glass width (x=0) so a 9-char line (9*8=72px) touches both side
 * frames: label flush-left, value flush-right. */
#define KEYPOINT_LIVE_TEXT_X 0
#define KEYPOINT_LIVE_TEXT_Y 26
#define KEYPOINT_LIVE_TEXT_WIDTH 72
#define KEYPOINT_LIVE_TEXT_LINE_HEIGHT 12
/* The first live-data line is the card title. It renders inverted: a filled
 * foreground bar across the full text width with the title knocked out in the
 * background colour, so the card name reads as a highlighted header. The bar
 * brackets the unscii-8 glyphs (text y=26, ~8px tall) with a 1px margin. */
#define KEYPOINT_LIVE_TITLE_BAR_Y 25
#define KEYPOINT_LIVE_TITLE_BAR_HEIGHT 11
/* Before the first frame arrives there is no deck to page through. Instead of
 * the live-data grid, show a centred hint (NO DATA / WAITING) on the top
 * canvas -- plain centred text, no inverted title bar, columns, page rail or
 * health strip. The two lines sit roughly centred in the top live band. */
#define KEYPOINT_LIVE_TIP_Y 31
/* Page indicator for a multi-card deck: a scrollbar-style rail with a thumb
 * sized 1/N riding it at the current page's position (position + proportion,
 * no exact count). Lives in the free band between the status row and the first
 * live-data line, doubling as a status/data divider. Shown only when the deck
 * has >1 page. Reuses KEYPOINT_LIVE_TEXT_X / _WIDTH for the rail extent.
 * KEYPOINT_LIVE_PAGE_Y is the rail (divider) centre; the thumb is centred on it. */
#define KEYPOINT_LIVE_PAGE_Y 20
#define KEYPOINT_LIVE_PAGE_THUMB_HEIGHT 3

/* Live-data lines 1..KEYPOINT_LIVE_TOP_LINE_COUNT render on the top canvas;
 * the remaining lines and the health strip render on the middle (profile)
 * canvas, above the profile row. Canvas rows >= 66 never reach the glass
 * (middle-canvas overlap + rotate_canvas clipping), so keep content above. */
#define KEYPOINT_LIVE_TOP_LINE_COUNT 3
#define KEYPOINT_LIVE_EXTRA_TEXT_Y 0
#define KEYPOINT_LIVE_HEALTH_X 0
#define KEYPOINT_LIVE_HEALTH_Y 38
#define KEYPOINT_LIVE_HEALTH_WIDTH 72
#define KEYPOINT_LIVE_HEALTH_HEIGHT 2

/* Progress bar geometry for [NNN] tokens within a KEYPOINT_LIVE_TEXT_LINE_HEIGHT slot */
#define KEYPOINT_LIVE_BAR_MARGIN_Y 2
#define KEYPOINT_LIVE_BAR_HEIGHT 8
#define KEYPOINT_LIVE_BAR_BORDER 1

#define KEYPOINT_PROFILE_SLOT_WIDTH 15
#define KEYPOINT_PROFILE_SLOT_HEIGHT 14
#define KEYPOINT_PROFILE_CORNER_SIZE 4
#define KEYPOINT_PROFILE_MARK_SIZE 3
#define KEYPOINT_PROFILE_MARK_X_OFFSET 10
#define KEYPOINT_PROFILE_MARK_Y_OFFSET 9
#define KEYPOINT_PROFILE_ROW_Y 43

#define KEYPOINT_LAYER_TEXT_X 2
#define KEYPOINT_LAYER_TEXT_Y 61
#define KEYPOINT_LAYER_TEXT_WIDTH 68

/* Live-data icon bitmaps, defined in status_layout.c: one row string each,
 * '1' = ink. status.c maps the KP3 icon enum onto them. */
extern const char icon_sun[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_cloud[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_rain[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_temp[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_warn[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_code[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_time[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_codex[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_claude[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
