from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_DATA_H = ROOT / "config/boards/shields/lpm_view/widgets/live_data.h"
LIVE_DATA_C = ROOT / "config/boards/shields/lpm_view/widgets/live_data.c"
STATUS_C = ROOT / "config/boards/shields/lpm_view/widgets/status.c"
UTIL_H = ROOT / "config/boards/shields/lpm_view/widgets/util.h"
CMAKE = ROOT / "config/boards/shields/lpm_view/CMakeLists.txt"
KCONFIG = ROOT / "config/boards/shields/lpm_view/Kconfig.defconfig"
SENDER = ROOT / "scripts/send_keypoint_live_demo.py"


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
    assert "with_current_time" not in text


def test_demo_sender_can_resolve_macos_connected_keyboard() -> None:
    text = SENDER.read_text()

    assert "retrieveConnectedPeripheralsWithServices_" in text
    assert "CentralManagerDelegate" in text
    assert "BLEDevice" in text
