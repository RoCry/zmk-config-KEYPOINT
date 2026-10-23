#pragma once

/* Portrait pixel coordinates within two contiguous 72x72 canvases. */
#define KEYPOINT_LIVE_ICON_SIZE 8
#define KEYPOINT_LIVE_ICON_SCALE 2
#define KEYPOINT_LIVE_ICON_X 34
#define KEYPOINT_LIVE_ICON_Y 0
#define KEYPOINT_LIVE_TEXT_X 0
#define KEYPOINT_LIVE_TEXT_Y 26
#define KEYPOINT_LIVE_TEXT_WIDTH 72
#define KEYPOINT_LIVE_TEXT_LINE_HEIGHT 14
#define KEYPOINT_LIVE_TIP_Y 31
#define KEYPOINT_LIVE_PAGE_Y 20
#define KEYPOINT_LIVE_TOP_LINE_COUNT 3
#define KEYPOINT_LIVE_EXTRA_TEXT_Y 0
#define KEYPOINT_PROFILE_ROW_Y 43
#define KEYPOINT_LAYER_TEXT_X 2
#define KEYPOINT_LAYER_TEXT_Y 61
#define KEYPOINT_LAYER_TEXT_WIDTH 64

/* Eight-pixel icons, enlarged without interpolation. */
extern const char icon_sun[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_cloud[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_rain[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_temp[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_warn[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_code[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_time[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_codex[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
extern const char icon_claude[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1];
