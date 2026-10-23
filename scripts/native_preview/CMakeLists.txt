cmake_minimum_required(VERSION 3.20)
project(keypoint_preview C)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(LV_CONF_PATH ${CMAKE_CURRENT_SOURCE_DIR}/lv_conf.h CACHE STRING "LVGL config" FORCE)
add_subdirectory(${LVGL_SOURCE_DIR} lvgl EXCLUDE_FROM_ALL)
set(SHIELD ${CMAKE_CURRENT_SOURCE_DIR}/../../config/boards/shields/lpm_view)
add_library(keypoint_preview SHARED
    bridge.c
    ${SHIELD}/widgets/status_render.c
    ${SHIELD}/widgets/status_info_panel.c
    ${SHIELD}/widgets/status_layout.c
    ${SHIELD}/widgets/util.c
    ${SHIELD}/widgets/theme.c
    ${SHIELD}/widgets/bolt.c
    ${SHIELD}/widgets/live_data_core.c
    ${SHIELD}/display_driver/lpm009m360a_core.c)
target_compile_definitions(keypoint_preview PRIVATE CONFIG_KEYPOINT_LIVE_DATA=1 CONFIG_NICE_VIEW_WIDGET_INVERTED=0)
target_include_directories(keypoint_preview PRIVATE ${SHIELD}/widgets ${SHIELD}/display_driver)
target_link_libraries(keypoint_preview PRIVATE lvgl m)
target_compile_options(keypoint_preview PRIVATE -Wall -Wextra -Werror)
