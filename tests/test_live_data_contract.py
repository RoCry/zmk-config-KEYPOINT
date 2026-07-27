"""Wiring and structure pins for the firmware tree.

What belongs here: things only a build can express -- CMake targets, Kconfig
symbols, keymap bindings, Zephyr listener and work-queue registration, BLE
UUIDs, module boundaries -- asserted by reading the source, because there is
no way to execute them on a host.

What does NOT belong here: behaviour. Reading C source to pin what the code
*does* fixes its spelling, not its meaning, and it passes just as happily
when the behaviour is wrong. Deck staging, parsing, staleness and attention
folding are executed in `test_kp3_core.py` against the compiled core; the
wire contract is executed in `test_kp3_contract.py` against kp3. Put new
behaviour tests there.
"""

import ast
import importlib.util
import random
import re
from pathlib import Path

import keypoint_demo_cards as demo_cards
import kp3

ROOT = Path(__file__).resolve().parents[1]
BUILD_YAML = ROOT / "build.yaml"
KEYMAP = ROOT / "config/keypoint.keymap"
BINDING_CHECKER = ROOT / "scripts/check_keypoint_bindings.py"
LIVE_DATA_H = ROOT / "config/boards/shields/lpm_view/widgets/live_data.h"
LIVE_DATA_C = ROOT / "config/boards/shields/lpm_view/widgets/live_data.c"
LIVE_DATA_CORE_C = ROOT / "config/boards/shields/lpm_view/widgets/live_data_core.c"
LIVE_DATA_CORE_H = ROOT / "config/boards/shields/lpm_view/widgets/live_data_core.h"
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
WIDGETS_DIR = ROOT / "config/boards/shields/lpm_view/widgets"
STATUS_H = WIDGETS_DIR / "status.h"
STATUS_INFO_PANEL_C = WIDGETS_DIR / "status_info_panel.c"
STATUS_INFO_PANEL_H = WIDGETS_DIR / "status_info_panel.h"
STATUS_LAYOUT_C = WIDGETS_DIR / "status_layout.c"
STATUS_LAYOUT_H = WIDGETS_DIR / "status_layout.h"
UTIL_H = WIDGETS_DIR / "util.h"
CMAKE = ROOT / "config/boards/shields/lpm_view/CMakeLists.txt"
LEFT_CMAKE = ROOT / "config/boards/shields/left_bbtrackpad_keypoint/CMakeLists.txt"
KCONFIG = ROOT / "config/boards/shields/lpm_view/Kconfig.defconfig"
SENDER = ROOT / "scripts/send_keypoint_live_demo.py"
DIAGNOSE = ROOT / "scripts/diagnose_keypoint_live.py"


def sender_ast() -> ast.Module:
    """The demo sender parsed rather than imported.

    CI installs neither bleak nor typer, so the module cannot be executed here
    -- but its module-level declarations are still real values, not source
    text, once they come back out of the AST.
    """
    return ast.parse(SENDER.read_text())


def module_assigned_names(module: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in module.body:
        match node:
            case ast.Assign(targets=targets):
                names.update(target.id for target in targets if isinstance(target, ast.Name))
            case ast.AnnAssign(target=ast.Name(id=name)):
                names.add(name)
    return names


def module_constants(module: ast.Module) -> dict[str, object]:
    return {
        target.id: node.value.value
        for node in module.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


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


def test_trackpad_led_renders_attention_levels_and_nothing_else() -> None:
    text = TRACKPAD_LED_C.read_text()

    # Plain include: the shield's CMakeLists puts lpm_view/widgets on the path,
    # so the driver no longer reaches across shields by relative path.
    assert '#include "live_data.h"' in text
    assert "../../lpm_view" not in text

    # Subscribes to the one-way seam; the new-deck confirm pulse is driven by
    # the notification, not by comparing generations here.
    assert "keypoint_live_data_subscribe(live_data_changed)" in text
    assert "KEYPOINT_LIVE_DATA_CHANGE_GENERATION" in text
    assert "live_confirm_start_ms" in text

    # Attention level -> blink pattern is the whole job. No icon names, no LED
    # hints, no staleness or generation math: a new icon never lands here.
    assert "keypoint_live_data_snapshot_get().attention" in text
    for icon in ("SUN", "CLOUD", "RAIN", "TEMP", "CODE", "TIME", "CODEX", "CLAUDE"):
        assert f"KEYPOINT_LIVE_DATA_ICON_{icon}" not in text
    assert "KEYPOINT_LIVE_DATA_ICON_" not in text
    assert "KEYPOINT_LIVE_DATA_LED_HINT" not in text
    assert "snapshot.stale" not in text
    assert "snapshot.generation" not in text
    assert "live_generation" not in text

    # "Live data is compiled in" is stated once, in Kconfig, and this file has
    # exactly one #if referencing it.
    assert "IS_ENABLED(CONFIG_KEYPOINT_LIVE_DATA)" in text
    assert text.count("#if ") == 1
    assert "TRACKPAD_LED_HAS_LIVE_DATA" not in text

    assert "zmk_hid_indicators_get_current_profile" not in text
    assert "capslock" not in text.lower()
    assert "animation_work" not in text


def test_live_data_seam_is_one_way() -> None:
    header = LIVE_DATA_H.read_text()
    glue = LIVE_DATA_C.read_text()
    status = STATUS_C.read_text()

    # The protocol module declares nothing the renderer has to define, so it
    # links without the renderer.
    for source in (header, glue, status):
        assert "keypoint_live_data_refresh_displays" not in source

    # LiveData publishes; consumers subscribe.
    assert "typedef void (*keypoint_live_data_listener_t)(enum keypoint_live_data_change change);" in header
    assert "void keypoint_live_data_subscribe(keypoint_live_data_listener_t listener);" in header
    assert "KEYPOINT_LIVE_DATA_CHANGE_REFRESH" in header
    assert "KEYPOINT_LIVE_DATA_CHANGE_GENERATION" in header

    # Fixed-size subscriber table, loud on overflow, and subscribers still run
    # on the display work queue where the refresh used to be submitted.
    assert "#define KEYPOINT_LIVE_DATA_LISTENER_MAX" in glue
    assert "LOG_ERR(" in glue
    assert "k_work_submit_to_queue(zmk_display_work_q(), &live_data_notify_work)" in glue

    # The renderer registers its own repaint.
    assert "keypoint_live_data_subscribe(live_data_changed)" in status


def test_live_data_page_navigation_listener() -> None:
    text = LIVE_DATA_C.read_text()
    core = LIVE_DATA_CORE_C.read_text()

    # Left center-cluster keys (pos 32 NEXT, 33 PREV) drive page navigation.
    assert "#define KEYPOINT_LIVE_PAGE_NEXT_POS 32" in text
    assert "#define KEYPOINT_LIVE_PAGE_PREV_POS 33" in text
    # FN-gated so &msc SCRL_* on those keys still scrolls.
    assert "zmk_keymap_highest_layer_active() == KEYPOINT_FN_LAYER" in text
    assert "ZMK_SUBSCRIPTION(keypoint_live_data_page_keys, zmk_position_state_changed)" in text
    # Wrap-around page advance over the deck, computed by the pure core.
    assert "(deck->view_index + deck->total + delta) % deck->total" in core


def test_live_data_core_is_free_of_zephyr_and_globals() -> None:
    text = LIVE_DATA_CORE_C.read_text()
    header = LIVE_DATA_CORE_H.read_text()

    # The core must stay host-compilable: no Zephyr/LVGL anywhere in its
    # include graph (live_data.h itself only pulls in stdbool/stdint).
    for source in (text, header):
        assert "<zephyr/" not in source
        assert "<zmk/" not in source
        assert "lvgl" not in source
        assert "k_uptime_get()" not in source
        assert "k_mutex" not in source

    # Deck state is caller-owned and time is an argument, not a global clock.
    assert "static struct keypoint_live_data_deck" not in text
    assert "int64_t now_ms" in header
    assert "struct keypoint_live_data_deck *deck" in header

    # The glue owns the single instance and the lock around every core call.
    glue = LIVE_DATA_C.read_text()
    assert "static struct keypoint_live_data_deck live_deck;" in glue
    assert "keypoint_live_data_core_store(&live_deck" in glue
    assert "keypoint_live_data_core_snapshot(&live_deck, k_uptime_get())" in glue
    assert "keypoint_live_data_core_page_advance(&live_deck, delta)" in glue


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
    cmake = CMAKE.read_text()
    kconfig = KCONFIG.read_text()
    left_cmake = LEFT_CMAKE.read_text()

    assert "widgets/live_data.c" in cmake
    assert "widgets/live_data_core.c" in cmake

    # One statement of the condition: a Kconfig symbol the build and every #if
    # site reference, rather than four independent spellings.
    assert "config KEYPOINT_LIVE_DATA" in kconfig
    assert "default y if ZMK_DISPLAY && NICE_VIEW_WIDGET_STATUS && (!ZMK_SPLIT || ZMK_SPLIT_ROLE_CENTRAL)" in kconfig
    assert "if(CONFIG_KEYPOINT_LIVE_DATA)" in cmake
    assert "NOT CONFIG_ZMK_SPLIT OR CONFIG_ZMK_SPLIT_ROLE_CENTRAL" not in cmake

    # The contract header reaches the left shield by include path, not by a
    # relative reach from the source file.
    assert "zephyr_library_include_directories(../lpm_view/widgets)" in left_cmake


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


def test_widget_headers_declare_rather_than_define() -> None:
    """Headers under widgets/ carry interfaces, not code or data.

    A `static` definition in a header compiles a private copy into every
    translation unit that includes it, and a definition that varies by build
    config is how one struct tag ended up with two shapes across the split.
    """
    for header in sorted(WIDGETS_DIR.rglob("*.h")):
        text = header.read_text()
        assert not re.search(r"^static\b", text, re.M), f"{header.name} defines a static function or table"
        assert "] = {" not in text, f"{header.name} defines a data table"


def test_one_status_widget_struct_serves_both_halves() -> None:
    """The status screen allocates the widget; CMake picks which half
    implements it. One tag with one layout per image, or the peripheral
    allocates the central's shape and reads a struct nobody wrote."""
    status_h = STATUS_H.read_text()
    screen = (ROOT / "config/boards/shields/lpm_view/custom_status_screen.c").read_text()
    peripheral = (WIDGETS_DIR / "peripheral_status.c").read_text()
    cmake = CMAKE.read_text()

    assert not (WIDGETS_DIR / "peripheral_status.h").exists()
    assert '#include "status.h"' in peripheral
    assert '#include "widgets/status.h"' in screen

    # The second canvas buffer exists exactly where the second canvas is drawn:
    # under the same symbol CMake selects widgets/status.c on.
    assert "#if IS_ENABLED(CONFIG_KEYPOINT_LIVE_DATA)\n    lv_color_t cbuf2[CANVAS_SIZE * CANVAS_SIZE];" in status_h
    assert "if(CONFIG_KEYPOINT_LIVE_DATA)" in cmake
    assert "cbuf2" not in peripheral


def test_central_only_drawing_sources_stay_out_of_the_peripheral_image() -> None:
    """status.c's drawing helpers own the live-data icon bitmaps and the
    profile grid, neither of which the peripheral screen renders. Wired outside
    the central branch they would link their .rodata into it anyway."""
    _, _, conditional = CMAKE.read_text().partition("if(CONFIG_KEYPOINT_LIVE_DATA)")
    central, _, peripheral = conditional.partition("else()")

    for source in ("widgets/status.c", "widgets/status_layout.c", "widgets/status_info_panel.c"):
        assert source in central
        assert source not in peripheral


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
    info_panel = STATUS_INFO_PANEL_C.read_text()
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
    middle_end = text.index("static void live_data_changed(", middle_start)
    middle = text[middle_start:middle_end]
    assert "draw_live_data_extra(" in middle

    # Both canvases carry live data, so the subscribed repaint redraws both.
    refresh_start = text.index("static void live_data_changed(")
    refresh_end = text.index("static void set_battery_status(", refresh_start)
    refresh = text[refresh_start:refresh_end]
    assert "draw_top(widget->obj, widget->cbuf, &widget->state);" in refresh
    assert "draw_middle(widget->obj, widget->cbuf2, &widget->state);" in refresh


def test_status_layout_uses_named_constants_for_live_data_and_profile_grid() -> None:
    text = STATUS_C.read_text() + STATUS_INFO_PANEL_C.read_text()
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
    info_panel = STATUS_INFO_PANEL_C.read_text()
    text = status + info_panel

    layer_start = info_panel.index("void draw_layer_info(")
    layer = info_panel[layer_start:]

    assert "draw_rect_outline(" not in layer
    assert "KEYPOINT_LAYER_TEXT_Y" in layer
    assert "trim_spaces(" in text
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


def test_live_data_title_renders_inverted_bar() -> None:
    text = STATUS_C.read_text()
    layout = STATUS_LAYOUT_H.read_text()

    assert "#define KEYPOINT_LIVE_TITLE_BAR_Y" in layout
    assert "#define KEYPOINT_LIVE_TITLE_BAR_HEIGHT" in layout

    # The title (live line 0) draws a filled foreground bar, then the title
    # text in the background colour -- an inverted highlighted header.
    title_start = text.index("static void draw_live_data_title(")
    title_end = text.index("static void draw_live_data_panel(", title_start)
    title = text[title_start:title_end]
    assert "KEYPOINT_LIVE_TITLE_BAR_Y" in title
    assert "ink_dsc" in title  # filled bar
    assert "title_dsc.color = bg_dsc->bg_color;" in title  # knocked-out text
    assert "title_dsc.align = LV_TEXT_ALIGN_CENTER;" in title  # centred
    assert "trim_spaces(" in title  # trim producer padding before centring

    # The panel renders the title separately and starts the line loop at 1.
    panel_start = text.index("static void draw_live_data_panel(")
    panel_end = text.index("static void draw_top(", panel_start)
    panel = text[panel_start:panel_end]
    assert "draw_live_data_title(canvas, snapshot.lines[0]" in panel
    assert "for (int i = 1; i < KEYPOINT_LIVE_TOP_LINE_COUNT; i++)" in panel


def test_no_data_renders_centered_tip() -> None:
    text = STATUS_C.read_text()
    layout = STATUS_LAYOUT_H.read_text()

    assert "#define KEYPOINT_LIVE_TIP_Y" in layout
    assert "static void draw_live_data_tip(" in text
    assert "tip_dsc.align = LV_TEXT_ALIGN_CENTER;" in text

    # The panel shows the tip and returns before the data grid...
    panel_start = text.index("static void draw_live_data_panel(")
    panel = text[panel_start : text.index("static void draw_live_data_extra(", panel_start)]
    assert "draw_live_data_tip(canvas, &snapshot, label_dsc);" in panel

    # ...and the middle-canvas extra block is skipped entirely (so no health
    # strip is drawn while there is no data).
    extra = text[text.index("static void draw_live_data_extra(") : text.index("static void draw_top(")]
    assert "if (!snapshot.has_data) {" in extra
    assert "30, KEYPOINT_LIVE_HEALTH_Y, 13" not in text


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
    # Icon drawn at 2x to match the battery/endpoint-symbol heights.
    assert "#define KEYPOINT_LIVE_ICON_SCALE 2" in layout
    assert "KEYPOINT_LIVE_ICON_X" in text
    assert "KEYPOINT_LIVE_ICON_Y" in text


def test_every_accepted_icon_reaches_the_renderer() -> None:
    """Which icons exist is kp3's business (it derives them and cross-checks
    the enum against the acceptance chain). What this pins is the wiring: the
    parser resolves an icon and the status widget draws one."""
    firmware = LIVE_DATA_CORE_C.read_text()
    status = STATUS_C.read_text()

    assert "enum keypoint_live_data_icon *icon" in firmware
    assert "icon_from_field(" in firmware
    assert "draw_live_data_icon(" in status
    assert "draw_bitmap_icon(" in status


def test_codex_icon_uses_openai_mark_inspired_bitmap() -> None:
    bitmaps = STATUS_LAYOUT_C.read_text()

    assert (
        "const char icon_codex[KEYPOINT_LIVE_ICON_SIZE][KEYPOINT_LIVE_ICON_SIZE + 1] = {\n"
        '    "00111100", "01011010", "10100101", "10111101",\n'
        '    "10111101", "10100101", "01011010", "00111100",\n'
        "};"
    ) in bitmaps

    # The plain X it replaced.
    old_x_rows = '    "10000001", "01000010", "00100100", "00011000",\n'
    assert old_x_rows not in bitmaps


def test_demo_sender_declares_no_contract_of_its_own() -> None:
    """The demo consumes kp3; a second copy of the grammar is how they drift.

    Nothing here restates a limit: the forbidden names and the deck ceiling
    both come out of kp3, which derives them from live_data.h at import.
    """
    module = sender_ast()
    contract_names = {name for name in vars(kp3) if name.isupper()}

    assert "kp3" in {alias.name for node in module.body if isinstance(node, ast.Import) for alias in node.names}
    assert not module_assigned_names(module) & contract_names
    assert not {name for name in vars(demo_cards) if name.isupper()} & contract_names
    assert 1 <= module_constants(module)["DEMO_DECK_SIZE"] <= kp3.PAGE_MAX


def test_demo_sender_uuids_match_the_firmware_service() -> None:
    firmware = LIVE_DATA_C.read_text()
    constants = module_constants(sender_ast())

    for name in ("SERVICE_UUID", "CHAR_UUID"):
        assert constants[name] in firmware


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


def test_demo_cards_cover_every_icon_the_firmware_accepts() -> None:
    """A demo run has to exercise the whole icon enum, not a stale subset."""
    assert {source.icon for source in demo_cards.DEFAULT_DEMO_SOURCES} == set(kp3.ICON_NAMES)
    assert len(demo_cards.DEFAULT_DEMO_SOURCES) >= 16


def test_every_demo_card_builds_a_frame_the_firmware_would_accept() -> None:
    """The cards are checked as frames, not as source text.

    Each card is pushed at the widest page coordinates the deck allows, so a
    card that only fits on page 0 of a single-page deck still fails here.
    """
    for index, source in enumerate(demo_cards.DEFAULT_DEMO_SOURCES):
        frame = demo_cards.card_frame(
            source,
            "23:59",
            generation=0xFF,
            idx=index % kp3.PAGE_MAX,
            total=kp3.PAGE_MAX,
        )
        parsed = kp3.parse(frame)
        assert parsed.icon == source.icon
        assert parsed.led_hint == source.led_hint
        assert parsed.led_hint in kp3.LED_CODES


def test_grid_probe_card_fills_every_line_edge_to_edge() -> None:
    """The one card that proves the glass renders a full character grid."""
    probe = demo_cards.grid_probe_source()
    lines = (probe.line1, probe.line2, probe.extra1, probe.extra2, probe.extra3)

    assert len(lines) == kp3.TEXT_LINE_COUNT - 1  # the sixth line is the timestamp
    assert {len(line) for line in lines} == {kp3.LINE_MAX}
    assert len(set(lines)) == len(lines)


def test_demo_sender_randomizes_dynamic_mock_data_by_default() -> None:
    """The CLI wiring is source text (typer is not installed in CI); what the
    generators actually produce is checked as values."""
    text = SENDER.read_text()

    assert "randomize: bool = typer.Option(True" in text
    assert '"--random/--sequential"' in text
    assert "source_interval: float = typer.Option(2.0" in text

    rng = random.Random(1337)
    previous = None
    icons = set()
    for _ in range(2000):
        source = demo_cards.random_demo_source(rng=rng, previous=previous)
        assert source != previous  # consecutive cards differ, so the glass visibly moves
        kp3.parse(demo_cards.card_frame(source, "12:00", generation=0, idx=0, total=1))
        icons.add(source.icon)
        previous = source

    assert icons == set(kp3.ICON_NAMES)


def test_sequential_demo_decks_walk_the_default_cards_in_order() -> None:
    deck = demo_cards.demo_deck(
        source_iter=iter(demo_cards.DEFAULT_DEMO_SOURCES),
        rng=random.Random(0),
        randomize=False,
        size=kp3.PAGE_MAX,
    )

    assert deck == list(demo_cards.DEFAULT_DEMO_SOURCES[: kp3.PAGE_MAX])


def test_demo_sender_can_resolve_macos_connected_keyboard() -> None:
    text = SENDER.read_text()

    assert "retrieveConnectedPeripheralsWithServices_" in text
    assert "CentralManagerDelegate" in text
    assert "BLEDevice" in text


def test_diagnose_probe_frame_is_built_by_kp3_at_runtime() -> None:
    """A frozen probe would drift past the grammar it is meant to test.

    The script exists to tell "the firmware is stale" apart from "the producer
    is stale"; a hardcoded frame quietly turns every run into the second.
    """
    text = DIAGNOSE.read_text()
    module = ast.parse(text)

    assert "kp3.build_frame(" in text
    assert not [node for node in ast.walk(module) if isinstance(node, ast.Constant) and isinstance(node.value, bytes)]
    # Writing *with* response is the whole point: it surfaces the GATT verdict.
    assert "response=True" in text
