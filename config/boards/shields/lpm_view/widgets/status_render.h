#pragma once

#include "util.h"
#include "live_data.h"

void keypoint_draw_top(lv_obj_t *canvas, const struct status_state *state,
                       const struct keypoint_live_data_snapshot *snapshot);
void keypoint_draw_middle(lv_obj_t *canvas, const struct status_state *state,
                          const struct keypoint_live_data_snapshot *snapshot);
