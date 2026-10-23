#pragma once

#include <lvgl.h>
#include <stddef.h>

struct keypoint_picture {
    const char *name;
    const lv_img_dsc_t *image;
};

extern const struct keypoint_picture keypoint_gallery[];
extern const size_t keypoint_gallery_count;
