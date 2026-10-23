/*
 * Copyright (c) 2023 Taisheng WANG <wstrn66@gmail.com>
 * SPDX-License-Identifier: Apache-2.0
 */
#define DT_DRV_COMPAT jdi_lpm009m360a

#include "lpm009m360a.h"
#include "lpm009m360a_core.h"

#include <zephyr/device.h>
#include <zephyr/drivers/display.h>
#include <zephyr/drivers/spi.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <string.h>

LOG_MODULE_REGISTER(display_lpm009m360a, CONFIG_DISPLAY_LOG_LEVEL);

struct lpm009m360a_data {
    struct lpm_frame frame;
    struct k_mutex lock;
};

struct lpm009m360a_config {
    struct spi_dt_spec bus;
};

static int transmit(void *context, const uint8_t *bytes, size_t size) {
    const struct device *dev = context;
    const struct lpm009m360a_config *config = dev->config;
    struct spi_buf buffer = {.buf = (void *)bytes, .len = size};
    struct spi_buf_set buffers = {.buffers = &buffer, .count = 1};
    return spi_write_dt(&config->bus, &buffers);
}

static int end_transaction(void *context) {
    const struct device *dev = context;
    const struct lpm009m360a_config *config = dev->config;
    int ret = spi_release_dt(&config->bus);
    /* Minimum low interval before any subsequent transaction. CS setup/hold
     * use the SPI GPIO CS delay of 6 us (spec: setup >=6, hold >=2 us). */
    k_busy_wait(6);
    return ret;
}

static int lpm009m360a_write(const struct device *dev, uint16_t x, uint16_t y,
                             const struct display_buffer_descriptor *desc, const void *buf) {
    if (!desc) {
        return -EINVAL;
    }
    struct lpm009m360a_data *data = dev->data;
    struct lpm_rect rect = {.x = x,
                            .y = y,
                            .width = desc->width,
                            .height = desc->height,
                            .pitch = desc->pitch,
                            .buf_size = desc->buf_size};
    struct lpm_transport transport = {
        .write = transmit, .end = end_transaction, .context = (void *)dev};
    k_mutex_lock(&data->lock, K_FOREVER);
    int ret = lpm_frame_write_rgb565(&data->frame, &rect, buf);
    if (!ret) {
        ret = lpm_frame_flush(&data->frame, &transport);
    }
    k_mutex_unlock(&data->lock);
    return ret;
}

static void lpm009m360a_get_capabilities(const struct device *dev,
                                         struct display_capabilities *capabilities) {
    ARG_UNUSED(dev);
    memset(capabilities, 0, sizeof(*capabilities));
    capabilities->x_resolution = LPM_LOGICAL_WIDTH;
    capabilities->y_resolution = LPM_LOGICAL_HEIGHT;
    capabilities->supported_pixel_formats = PIXEL_FORMAT_RGB_565;
    capabilities->current_pixel_format = PIXEL_FORMAT_RGB_565;
    capabilities->current_orientation = DISPLAY_ORIENTATION_NORMAL;
}

static int lpm009m360a_set_pixel_format(const struct device *dev,
                                        enum display_pixel_format pixel_format) {
    ARG_UNUSED(dev);
    return pixel_format == PIXEL_FORMAT_RGB_565 ? 0 : -ENOTSUP;
}

static int lpm009m360a_set_orientation(const struct device *dev,
                                       enum display_orientation orientation) {
    ARG_UNUSED(dev);
    return orientation == DISPLAY_ORIENTATION_NORMAL ? 0 : -ENOTSUP;
}

static int lpm009m360a_blanking_on(const struct device *dev) {
    ARG_UNUSED(dev);
    /* DISP and EXTCOMIN are not described by this board. Do not claim that
     * software can power down or blank an externally controlled panel. */
    return -ENOTSUP;
}

static int lpm009m360a_blanking_off(const struct device *dev) {
    ARG_UNUSED(dev);
    return 0; /* This board operates the display continuously. */
}

static int lpm009m360a_init(const struct device *dev) {
    const struct lpm009m360a_config *config = dev->config;
    struct lpm009m360a_data *data = dev->data;
    if (!spi_is_ready_dt(&config->bus)) {
        LOG_ERR("Display SPI bus or chip select is not ready");
        return -ENODEV;
    }
    k_mutex_init(&data->lock);
    lpm_frame_init(&data->frame);
    const uint8_t clear[2] = {LPM009M360A_CMD_ALL_CLEAR, 0};
    int ret = transmit((void *)dev, clear, sizeof(clear));
    int end_ret = end_transaction((void *)dev);
    if (ret || end_ret) {
        LOG_ERR("Display all-clear failed: %d", ret ? ret : end_ret);
        return ret ? ret : end_ret;
    }
    k_sleep(K_MSEC(1));
    return 0;
}

static const struct display_driver_api lpm009m360a_api = {
    .blanking_on = lpm009m360a_blanking_on,
    .blanking_off = lpm009m360a_blanking_off,
    .write = lpm009m360a_write,
    .get_capabilities = lpm009m360a_get_capabilities,
    .set_pixel_format = lpm009m360a_set_pixel_format,
    .set_orientation = lpm009m360a_set_orientation,
};

#define LPM009M360A_INIT(inst)                                                                     \
    BUILD_ASSERT(DT_INST_PROP(inst, width) == LPM_LOGICAL_WIDTH, "Display width must be 144");     \
    BUILD_ASSERT(DT_INST_PROP(inst, height) == LPM_LOGICAL_HEIGHT, "Display height must be 72");   \
    static const struct lpm009m360a_config lpm009m360a_config_##inst = {                           \
        .bus = SPI_DT_SPEC_INST_GET(                                                               \
            inst, SPI_OP_MODE_MASTER | SPI_WORD_SET(8) | SPI_HOLD_ON_CS | SPI_LOCK_ON, 6),         \
    };                                                                                             \
    static struct lpm009m360a_data lpm009m360a_data_##inst;                                        \
    DEVICE_DT_INST_DEFINE(inst, lpm009m360a_init, NULL, &lpm009m360a_data_##inst,                  \
                          &lpm009m360a_config_##inst, POST_KERNEL, CONFIG_DISPLAY_INIT_PRIORITY,   \
                          &lpm009m360a_api);

DT_INST_FOREACH_STATUS_OKAY(LPM009M360A_INIT)
