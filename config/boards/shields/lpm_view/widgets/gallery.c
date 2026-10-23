#include "gallery.h"

LV_IMG_DECLARE(al_pacino);
LV_IMG_DECLARE(favorite_69b97550);
LV_IMG_DECLARE(rezaul_karim);
LV_IMG_DECLARE(minion);

const struct keypoint_picture keypoint_gallery[] = {
    {"al_pacino", &al_pacino},
    {"favorite_69b97550", &favorite_69b97550},
    {"rezaul_karim", &rezaul_karim},
    {"minion", &minion},
};

const size_t keypoint_gallery_count = sizeof(keypoint_gallery) / sizeof(keypoint_gallery[0]);
