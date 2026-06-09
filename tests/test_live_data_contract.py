import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_YAML = ROOT / "build.yaml"
KEYMAP = ROOT / "config/keypoint.keymap"
BINDING_CHECKER = ROOT / "scripts/check_keypoint_bindings.py"
LIVE_DATA_H = ROOT / "config/boards/shields/lpm_view/widgets/live_data.h"
LIVE_DATA_C = ROOT / "config/boards/shields/lpm_view/widgets/live_data.c"
STATUS_C = ROOT / "config/boards/shields/lpm_view/widgets/status.c"
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

    assert "#define KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT 3" in text
    assert "#define KEYPOINT_LIVE_DATA_LINE_MAX 8" in text
    assert "#define KEYPOINT_LIVE_DATA_ICON_MAX 8" in text
    assert "#define KEYPOINT_LIVE_DATA_STALE_MS 360000" in text
    assert '#define KEYPOINT_LIVE_DATA_PREFIX "KP2|"' in text


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


def test_live_data_panel_uses_bottom_divider_without_frame() -> None:
    text = STATUS_C.read_text()

    panel_start = text.index("static void draw_live_data_panel(")
    panel_end = text.index("static void draw_top(", panel_start)
    panel = text[panel_start:panel_end]

    assert "lv_canvas_draw_rect(" not in panel
    assert "lv_canvas_draw_line(" in panel
    assert "init_line_dsc(" in text


def test_live_data_panel_dims_stale_snapshot() -> None:
    text = STATUS_C.read_text()

    panel_start = text.index("static void draw_live_data_panel(")
    panel_end = text.index("static void draw_top(", panel_start)
    panel = text[panel_start:panel_end]

    assert "snapshot.stale" in panel
    assert "LV_OPA_50" in panel
    assert ".opa" in panel


def test_live_data_icon_does_not_reduce_text_width() -> None:
    text = STATUS_C.read_text()

    panel_start = text.index("static void draw_live_data_panel(")
    panel_end = text.index("static void draw_top(", panel_start)
    panel = text[panel_start:panel_end]

    assert "const bool has_icon" not in panel
    assert "text_x = has_icon" not in panel
    assert "lv_canvas_draw_text(canvas, 3, 23 + (i * 11), 67" in panel
    assert "#define LIVE_DATA_ICON_SCALE 1" in text
    assert "draw_bitmap_icon(canvas, 2, 55, icon_dsc, rows);" in text


def test_live_data_kp2_icon_contract_is_explicit() -> None:
    header = LIVE_DATA_H.read_text()
    firmware = LIVE_DATA_C.read_text()
    status = STATUS_C.read_text()

    for icon in ("NONE", "SUN", "CLOUD", "RAIN", "TEMP", "WARN", "CODE", "TIME", "CODEX", "CLAUDE"):
        assert f"KEYPOINT_LIVE_DATA_ICON_{icon}" in header

    assert "enum keypoint_live_data_icon *icon" in firmware
    assert "icon_from_field(" in firmware
    assert "draw_live_data_icon(" in status
    assert "draw_bitmap_icon(" in status


def test_live_data_stale_keeps_last_payload_text() -> None:
    text = LIVE_DATA_C.read_text()

    assert '"STALE"' not in text
    assert "snapshot.stale" in text


def test_demo_sender_uses_same_limits() -> None:
    text = SENDER.read_text()

    assert "TEXT_LINE_COUNT = 3" in text
    assert "LINE_MAX = 8" in text
    assert "ICON_IDS" in text
    assert 'PREFIX = "KP2|"' in text
    assert 'CHAR_UUID = "f5d40001-6d2f-4f4b-9b2a-2f4a8e8c0001"' in text


def test_demo_sender_uses_data_time_not_send_time() -> None:
    text = SENDER.read_text()

    assert "source_interval" in text
    assert "data_time" in text
    assert "count:" in text
    assert "with_current_time" not in text


def test_demo_sender_exercises_diverse_icon_data() -> None:
    text = SENDER.read_text()

    for icon in ("NONE", "SUN", "CLOUD", "RAIN", "TEMP", "WARN", "CODE", "TIME", "CODEX", "CLAUDE"):
        assert f'DemoSource(icon="{icon}"' in text

    assert text.count("DemoSource(") >= 16
    assert '"MAX8CHAR"' in text
    assert '"ABCDEFGH"' in text


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
