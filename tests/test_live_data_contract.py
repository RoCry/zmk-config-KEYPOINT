import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_YAML = ROOT / "build.yaml"
KEYMAP = ROOT / "config/keypoint.keymap"
BINDING_CHECKER = ROOT / "scripts/check_keypoint_bindings.py"
LIVE_DATA_H = ROOT / "config/boards/shields/lpm_view/widgets/live_data.h"
LIVE_DATA_C = ROOT / "config/boards/shields/lpm_view/widgets/live_data.c"
STATUS_C = ROOT / "config/boards/shields/lpm_view/widgets/status.c"
TRACKPAD_LED_C = ROOT / "config/boards/shields/left_bbtrackpad_keypoint/custom_driver_left/trackpad_led.c"
A320_C = ROOT / "config/boards/shields/left_bbtrackpad_keypoint/custom_driver_left/a320.c"
TRACKPOINT_C = ROOT / "config/boards/shields/right_trackpoint_keypoint/custom_driver_right/trackpoint_0x15.c"
BOARD_CONFIGS = (
    ROOT / "config/boards/arm/zitaotech_keypoint/Kconfig.defconfig",
    ROOT / "config/boards/arm/zitaotech_keypoint/zitaotech_keypoint.conf",
    ROOT / "config/boards/arm/zitaotech_keypoint/zitaotech_keypoint_left_defconfig",
    ROOT / "config/boards/arm/zitaotech_keypoint/zitaotech_keypoint_right_defconfig",
)
STATUS_INFO_PANEL_H = ROOT / "config/boards/shields/lpm_view/widgets/status_info_panel.h"
STATUS_LAYOUT_H = ROOT / "config/boards/shields/lpm_view/widgets/status_layout.h"
UTIL_H = ROOT / "config/boards/shields/lpm_view/widgets/util.h"
CMAKE = ROOT / "config/boards/shields/lpm_view/CMakeLists.txt"
KCONFIG = ROOT / "config/boards/shields/lpm_view/Kconfig.defconfig"
SENDER = ROOT / "scripts/send_keypoint_live_demo.py"


def load_binding_checker():
    spec = importlib.util.spec_from_file_location("check_keypoint_bindings", BINDING_CHECKER)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_matrix_uses_short_artifact_names() -> None:
    text = BUILD_YAML.read_text()

    for artifact_name in ("left", "right", "left-reset", "right-reset"):
        assert f"artifact-name: {artifact_name}" in text


def test_bootloader_shortcuts_are_on_requested_layer_positions() -> None:
    checker = load_binding_checker()
    text = checker.read_keymap_text(KEYMAP)

    lower_bindings = checker.layer_bindings(text, "lower_layer")
    symbol_bindings = checker.layer_bindings(text, "symbol_layer")

    assert lower_bindings[45] == "&bootloader"
    assert symbol_bindings[52] == "&bootloader"


def test_live_data_firmware_contract_constants() -> None:
    text = LIVE_DATA_H.read_text()

    assert "#define KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT 6" in text
    assert "#define KEYPOINT_LIVE_DATA_LINE_MAX 8" in text
    assert "#define KEYPOINT_LIVE_DATA_ICON_MAX 8" in text
    assert "#define KEYPOINT_LIVE_DATA_GENERATION_FIELD_MAX 2" in text
    assert "#define KEYPOINT_LIVE_DATA_LED_HINT_FIELD_MAX 1" in text
    assert "#define KEYPOINT_LIVE_DATA_STALE_MS 360000" in text
    assert '#define KEYPOINT_LIVE_DATA_PREFIX "KP3|"' in text


def test_live_data_deck_contract_constants() -> None:
    text = LIVE_DATA_H.read_text()

    assert "#define KEYPOINT_LIVE_DATA_PAGE_MAX 8" in text
    assert "#define KEYPOINT_LIVE_DATA_PAGE_FIELD_MAX 1" in text
    # Frame-max macro carries GEN, IDX/TOTAL plus the LED hint and their separators.
    assert "(KEYPOINT_LIVE_DATA_GENERATION_FIELD_MAX + 1)" in text
    assert "((KEYPOINT_LIVE_DATA_PAGE_FIELD_MAX + 1) * 2)" in text
    assert "(KEYPOINT_LIVE_DATA_LED_HINT_FIELD_MAX + 1)" in text
    # Snapshot exposes the current page + deck size for the indicator.
    assert "uint8_t view_index;" in text
    assert "uint8_t total_pages;" in text
    assert "uint8_t generation;" in text
    assert "enum keypoint_live_data_led_hint led_hint;" in text
    # Parse signature yields generation/idx/total/icon/led_hint.
    assert "uint8_t *generation" in text
    assert "uint8_t *idx, uint8_t *total" in text
    assert "enum keypoint_live_data_led_hint *led_hint" in text


def test_trackpad_led_consumes_live_data_hint_without_capslock_animation() -> None:
    text = TRACKPAD_LED_C.read_text()

    assert '#include "../../lpm_view/widgets/live_data.h"' in text
    assert "keypoint_live_data_snapshot_get()" in text
    assert "live_confirm_start_ms" in text
    assert "live_snapshot.led_hint" in text
    assert "snapshot.generation" in text
    assert "KEYPOINT_LIVE_DATA_LED_HINT_WARNING" in text
    assert "zmk_hid_indicators_get_current_profile" not in text
    assert "capslock" not in text.lower()
    assert "animation_work" not in text


def test_live_data_page_navigation_listener() -> None:
    text = LIVE_DATA_C.read_text()

    # Left center-cluster keys (pos 32 NEXT, 33 PREV) drive page navigation.
    assert "#define KEYPOINT_LIVE_PAGE_NEXT_POS 32" in text
    assert "#define KEYPOINT_LIVE_PAGE_PREV_POS 33" in text
    # FN-gated so &msc SCRL_* on those keys still scrolls.
    assert "zmk_keymap_highest_layer_active() == KEYPOINT_FN_LAYER" in text
    assert "ZMK_SUBSCRIPTION(keypoint_live_data_page_keys, zmk_position_state_changed)" in text
    # Wrap-around page advance over the deck.
    assert "(view_index + deck_total + delta) % deck_total" in text


def test_live_data_uses_generation_staged_deck_commit() -> None:
    text = LIVE_DATA_C.read_text()

    assert "pending_deck[KEYPOINT_LIVE_DATA_PAGE_MAX]" in text
    assert "pending_generation" in text
    assert "pending_mask" in text
    assert "received_mask_for_total(pending_total)" in text
    assert "memcpy(deck, pending_deck, sizeof(deck));" in text
    assert "deck_generation = pending_generation;" in text


def test_status_widget_renders_page_indicator() -> None:
    layout = STATUS_LAYOUT_H.read_text()
    assert "#define KEYPOINT_LIVE_PAGE_Y" in layout
    assert "#define KEYPOINT_LIVE_PAGE_THUMB_HEIGHT" in layout

    status = STATUS_C.read_text()
    # Scrollbar rail page indicator: hidden for a single-page deck, thumb sized
    # 1/total_pages riding the rail at view_index.
    assert "draw_live_data_page_rail" in status
    assert "snapshot->total_pages <= 1" in status
    assert "KEYPOINT_LIVE_PAGE_Y" in status


def test_default_layer_bindings_are_consistent() -> None:
    # Runs the full binding checker (raises SystemExit with details on drift),
    # covering the live-data page-nav keys at positions 32/33.
    load_binding_checker().main()


def test_live_data_ble_uuids_are_stable() -> None:
    text = LIVE_DATA_C.read_text()

    assert "f5d40000-6d2f-4f4b-9b2a-2f4a8e8c0001" in text
    assert "f5d40001-6d2f-4f4b-9b2a-2f4a8e8c0001" in text
    assert "BT_GATT_CHRC_WRITE_WITHOUT_RESP" in text
    assert "BT_GATT_CHRC_WRITE" in text
    assert "BT_GATT_PERM_WRITE_ENCRYPT" in text


def test_live_data_schedules_stale_refresh() -> None:
    text = LIVE_DATA_C.read_text()

    assert "K_WORK_DELAYABLE_DEFINE(live_data_stale_work" in text
    assert "k_work_reschedule(&live_data_stale_work" in text
    assert "KEYPOINT_LIVE_DATA_STALE_MS + 1" in text


def test_live_data_compiled_for_central_lpm_view() -> None:
    text = CMAKE.read_text()

    assert "widgets/live_data.c" in text
    assert "NOT CONFIG_ZMK_SPLIT OR CONFIG_ZMK_SPLIT_ROLE_CENTRAL" in text


def test_status_uses_live_data_instead_of_wpm_chart() -> None:
    text = STATUS_C.read_text()
    util = UTIL_H.read_text()
    kconfig = KCONFIG.read_text()

    assert '#include "live_data.h"' in text
    assert "draw_live_data_panel(" in text
    assert "ZMK_SUBSCRIPTION(widget_wpm_status" not in text
    assert "zmk_wpm_get_state" not in text
    assert "uint8_t wpm[10];" not in util
    assert "select ZMK_WPM" not in kconfig


def test_shared_widget_headers_are_guarded() -> None:
    assert "#pragma once" in UTIL_H.read_text()
    assert "#pragma once" in STATUS_INFO_PANEL_H.read_text()
    assert "#pragma once" in STATUS_LAYOUT_H.read_text()


def test_status_tracks_each_ble_profile_state() -> None:
    text = STATUS_C.read_text()
    util = UTIL_H.read_text()

    assert "#define KEYPOINT_STATUS_PROFILE_COUNT 4" in util
    assert "profile_connected[KEYPOINT_STATUS_PROFILE_COUNT]" in util
    assert "profile_bonded[KEYPOINT_STATUS_PROFILE_COUNT]" in util
    assert "profile_connected[KEYPOINT_STATUS_PROFILE_COUNT]" in text
    assert "profile_bonded[KEYPOINT_STATUS_PROFILE_COUNT]" in text
    assert "for (uint8_t i = 0; i < KEYPOINT_STATUS_PROFILE_COUNT; i++)" in text
    assert "zmk_ble_profile_is_connected(i)" in text
    assert "!zmk_ble_profile_is_open(i)" in text


def test_status_uses_compact_profile_grid_and_layer_info() -> None:
    status = STATUS_C.read_text()
    info_panel = STATUS_INFO_PANEL_H.read_text()
    text = status + info_panel

    middle_start = status.index("static void draw_middle(")
    middle_end = status.index("static void set_battery_status(", middle_start)
    middle = status[middle_start:middle_end]

    assert "draw_profile_grid(" in middle
    assert "draw_profile_slot(" in text
    assert "lv_canvas_draw_arc(" not in middle
    assert "draw_layer_info(" in middle
    assert "draw_layer_chip(" not in text
    assert 'return "BASE";' in text


def test_layer_status_refreshes_visible_profile_layer_canvas() -> None:
    text = STATUS_C.read_text()

    setter_start = text.index("static void set_layer_status(")
    setter_end = text.index("static void layer_status_update_cb(", setter_start)
    setter = text[setter_start:setter_end]

    assert "draw_middle(widget->obj, widget->cbuf2, &widget->state);" in setter
    assert "draw_bottom(" not in setter


def test_status_does_not_overpaint_layer_info_with_third_canvas() -> None:
    text = STATUS_C.read_text()

    assert "static void draw_bottom(" not in text
    assert "lv_obj_get_child(widget, 2)" not in text
    assert "lv_canvas_set_buffer(bottom" not in text


def test_live_data_splits_lines_between_top_and_middle_canvas() -> None:
    text = STATUS_C.read_text()
    layout = STATUS_LAYOUT_H.read_text()

    # Lines 1..TOP render on the top canvas; the rest + health strip render on
    # the middle (profile) canvas. The old bottom divider is gone: canvas rows
    # >= 66 never reach the glass, so it was invisible on hardware.
    assert "#define KEYPOINT_LIVE_TOP_LINE_COUNT 3" in layout
    assert "#define KEYPOINT_LIVE_EXTRA_TEXT_Y" in layout
    assert "KEYPOINT_LIVE_DIVIDER" not in layout
    assert "static void draw_live_data_extra(" in text
    assert "draw_live_data_extra(canvas, &live_label_dsc, &rect_white_dsc, &rect_black_dsc);" in text
    assert "lv_canvas_draw_line(" not in text

    middle_start = text.index("static void draw_middle(")
    middle_end = text.index("void keypoint_live_data_refresh_displays(", middle_start)
    middle = text[middle_start:middle_end]
    assert "draw_live_data_extra(" in middle

    refresh_start = text.index("void keypoint_live_data_refresh_displays(")
    refresh_end = text.index("static void set_battery_status(", refresh_start)
    refresh = text[refresh_start:refresh_end]
    assert "draw_top(widget->obj, widget->cbuf, &widget->state);" in refresh
    assert "draw_middle(widget->obj, widget->cbuf2, &widget->state);" in refresh


def test_status_layout_uses_named_constants_for_live_data_and_profile_grid() -> None:
    text = STATUS_C.read_text() + STATUS_INFO_PANEL_H.read_text()
    layout = STATUS_LAYOUT_H.read_text()

    for name in (
        "KEYPOINT_LIVE_TEXT_X",
        "KEYPOINT_LIVE_TEXT_Y",
        "KEYPOINT_LIVE_TOP_LINE_COUNT",
        "KEYPOINT_LIVE_EXTRA_TEXT_Y",
        "KEYPOINT_LIVE_HEALTH_Y",
        "KEYPOINT_PROFILE_SLOT_WIDTH",
        "KEYPOINT_PROFILE_SLOT_HEIGHT",
        "KEYPOINT_PROFILE_MARK_SIZE",
        "KEYPOINT_PROFILE_ROW_Y",
        "KEYPOINT_LAYER_TEXT_Y",
    ):
        assert name in text
        assert name in layout

    assert "lv_canvas_draw_text(canvas, 3, 23 + (i * 11), 67" not in text
    assert "draw_bitmap_icon(canvas, 2, 55, icon_dsc, rows);" not in text


def test_profile_layout_leaves_room_for_layer_chip() -> None:
    layout = STATUS_LAYOUT_H.read_text()

    assert "#define KEYPOINT_PROFILE_SLOT_WIDTH 15" in layout
    assert "#define KEYPOINT_PROFILE_SLOT_HEIGHT 14" in layout
    assert "#define KEYPOINT_PROFILE_MARK_SIZE 3" in layout
    assert "#define KEYPOINT_PROFILE_ROW_Y 43" in layout
    assert "#define KEYPOINT_LAYER_TEXT_Y 61" in layout
    assert "KEYPOINT_LAYER_CHIP" not in layout


def test_layer_info_uses_small_unframed_trimmed_text() -> None:
    status = STATUS_C.read_text()
    info_panel = STATUS_INFO_PANEL_H.read_text()
    text = status + info_panel

    layer_start = info_panel.index("static void draw_layer_info(")
    layer = info_panel[layer_start:]

    assert "draw_rect_outline(" not in layer
    assert "KEYPOINT_LAYER_TEXT_Y" in layer
    assert "trim_layer_label(" in text
    assert "lv_font_unscii_8" in text
    assert "layer_label_dsc, LVGL_FOREGROUND, &lv_font_unscii_8" in text


def test_live_data_panel_draws_health_strip() -> None:
    text = STATUS_C.read_text()

    panel_start = text.index("static void draw_live_data_panel(")
    panel_end = text.index("static void draw_top(", panel_start)
    panel = text[panel_start:panel_end]

    assert "draw_live_data_health_strip(" in panel
    assert "snapshot->has_data" in text
    assert "KEYPOINT_LIVE_HEALTH_Y" in text


def test_live_data_stale_uses_segments_not_opacity() -> None:
    text = STATUS_C.read_text()

    # LV_COLOR_DEPTH=1 blending is a >50% threshold, so LV_OPA_50 dimming
    # would hide stale data entirely; staleness must be signaled by the
    # segmented health strip at full contrast instead.
    assert "LV_OPA_50" not in text

    strip_start = text.index("static void draw_live_data_health_strip(")
    strip_end = text.index("static void draw_live_data_panel(", strip_start)
    strip = text[strip_start:strip_end]
    assert "snapshot->stale" in strip
    assert "segment_x" in strip


def test_live_data_icon_does_not_reduce_text_width() -> None:
    text = STATUS_C.read_text()
    layout = STATUS_LAYOUT_H.read_text()

    panel_start = text.index("static void draw_live_data_panel(")
    panel_end = text.index("static void draw_top(", panel_start)
    panel = text[panel_start:panel_end]

    assert "const bool has_icon" not in panel
    assert "text_x = has_icon" not in panel
    assert "KEYPOINT_LIVE_TEXT_WIDTH" in panel
    assert "#define KEYPOINT_LIVE_ICON_SCALE 1" in layout
    assert "KEYPOINT_LIVE_ICON_X" in text
    assert "KEYPOINT_LIVE_ICON_Y" in text


def test_live_data_kp3_icon_contract_is_explicit() -> None:
    header = LIVE_DATA_H.read_text()
    firmware = LIVE_DATA_C.read_text()
    status = STATUS_C.read_text()

    for icon in ("NONE", "SUN", "CLOUD", "RAIN", "TEMP", "WARN", "CODE", "TIME", "CODEX", "CLAUDE"):
        assert f"KEYPOINT_LIVE_DATA_ICON_{icon}" in header

    assert "enum keypoint_live_data_icon *icon" in firmware
    assert "icon_from_field(" in firmware
    assert "draw_live_data_icon(" in status
    assert "draw_bitmap_icon(" in status


def test_codex_icon_uses_openai_mark_inspired_bitmap() -> None:
    status = STATUS_LAYOUT_H.read_text()

    assert (
        "static const char icon_codex[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {\n"
        '    "00111100", "01011010", "10100101", "10111101",\n'
        '    "10111101", "10100101", "01011010", "00111100",\n'
        "};"
    ) in status

    old_x_bitmap = (
        "static const char icon_codex[LIVE_DATA_ICON_SIZE][LIVE_DATA_ICON_SIZE + 1] = {\n"
        '    "10000001", "01000010", "00100100", "00011000",\n'
        '    "00011000", "00100100", "01000010", "10000001",\n'
        "};"
    )
    assert old_x_bitmap not in status


def test_live_data_stale_keeps_last_payload_text() -> None:
    text = LIVE_DATA_C.read_text()

    assert '"STALE"' not in text
    assert "snapshot.stale" in text


def test_demo_sender_uses_same_limits() -> None:
    text = SENDER.read_text()

    assert "TEXT_LINE_COUNT = 6" in text
    assert "LINE_MAX = 8" in text
    assert "GENERATION_FIELD_MAX = 2" in text
    assert "LED_HINT_IDS" in text
    assert "ICON_IDS" in text
    assert 'PREFIX = "KP3|"' in text
    assert 'CHAR_UUID = "f5d40001-6d2f-4f4b-9b2a-2f4a8e8c0001"' in text


def test_a320_touch_and_i2c_paths_are_fail_fast_without_capslock_mode() -> None:
    text = A320_C.read_text()

    assert "k_mutex_unlock(&a320_i2c_mutex);" in text
    assert "ret = i2c_write_dt" in text
    assert "ret = i2c_burst_read_dt" in text
    assert "return ret;" in text
    assert "last_touch_time" in text
    assert "k_uptime_get_32() - last_touch_time" in text
    assert "zmk_hid_indicators_changed" not in text
    assert "capslock" not in text.lower()


def test_capslock_indicator_path_is_removed_from_pointing_firmware() -> None:
    sources = [A320_C, TRACKPOINT_C, *BOARD_CONFIGS]
    joined = "\n".join(path.read_text() for path in sources)

    assert "zmk_hid_indicators_changed" not in joined
    assert "HID_INDICATORS" not in joined
    assert "ZMK_HID_INDICATORS" not in joined
    assert "ZMK_SPLIT_PERIPHERAL_HID_INDICATORS" not in joined
    assert "capslock" not in joined.lower()


def test_demo_sender_uses_data_time_not_send_time() -> None:
    text = SENDER.read_text()

    assert "source_interval" in text
    assert "data_time" in text
    assert "count:" in text
    assert "with_current_time" not in text


def test_demo_sender_exercises_diverse_icon_data() -> None:
    text = SENDER.read_text()

    for icon in ("NONE", "SUN", "CLOUD", "RAIN", "TEMP", "WARN", "CODE", "TIME", "CODEX", "CLAUDE"):
        assert f'icon="{icon}"' in text

    assert text.count("DemoSource(") >= 16
    assert '"MAX8CHAR"' in text
    assert '"ABCDEFGH"' in text
    # Demo lines exploit the monospace grid: padded label/value columns.
    assert "def kv(" in text
    assert "def title(" in text


def test_demo_sender_randomizes_dynamic_mock_data_by_default() -> None:
    text = SENDER.read_text()

    assert "import random" in text
    assert "DEMO_GENERATORS" in text
    assert "random_demo_source(" in text
    assert "randomize: bool = typer.Option(True" in text
    assert '"--random/--sequential"' in text
    assert "source_interval: float = typer.Option(2.0" in text

    for generator_name in (
        "random_sun_source",
        "random_cloud_source",
        "random_rain_source",
        "random_temp_source",
        "random_warn_source",
        "random_codex_source",
        "random_claude_source",
    ):
        assert generator_name in text


def test_demo_sender_can_resolve_macos_connected_keyboard() -> None:
    text = SENDER.read_text()

    assert "retrieveConnectedPeripheralsWithServices_" in text
    assert "CentralManagerDelegate" in text
    assert "BLEDevice" in text
