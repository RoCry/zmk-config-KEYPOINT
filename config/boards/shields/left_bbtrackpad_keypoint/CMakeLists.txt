zephyr_library()
zephyr_library_sources(custom_driver_left/a320.c)
zephyr_library_sources(custom_driver_left/trackpad_led.c)
zephyr_library_sources(custom_driver_left/custom_led.c)
zephyr_library_sources(../../../motion/motion_shaping.c)
zephyr_library_include_directories(../../../motion)
zephyr_library_include_directories(${ZEPHYR_BASE}/drivers)
zephyr_library_include_directories(../../../include)
zephyr_library_include_directories(${CMAKE_SOURCE_DIR}/include)
# The LiveData contract header, so trackpad_led.c includes it by name instead of
# reaching across shields. Header-only: without the lpm_view shield
# CONFIG_KEYPOINT_LIVE_DATA is unset and nothing here is compiled in.
zephyr_library_include_directories(../lpm_view/widgets)
