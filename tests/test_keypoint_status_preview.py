import importlib.util
import tempfile
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "preview_keypoint_status.py"


def load_module():
    spec = importlib.util.spec_from_file_location("preview_keypoint_status", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


preview = load_module()

FRESH_FRAME = "KP3|A0|0|1|SUN|0|SUNNY|TMP 24C|12:00|UV 5|HUM 40%|AQI 42"
STATE = preview.StatusState(
    battery=85,
    charging=False,
    transport="ble",
    active_profile_index=0,
    profile_connected=(True, False, False, False),
    profile_bonded=(True, True, False, False),
    layer_index=0,
)


# Glass-pixel positions of logical canvas pixels, following the simulated
# pipeline (fixed-point -90 deg canvas rotation + lpm009m360a rotation=1):
# top-canvas col c -> glass x (c<=36: c, else c+1), row r -> glass y
# (r<=35: r+1, else r+2); middle-canvas rows land 68 glass rows lower.
def glass_x(col: int) -> int:
    return col if col <= 36 else col + 1


def glass_y_top(row: int) -> int:
    return row + 1 if row <= 35 else row + 2


def glass_y_middle(row: int) -> int:
    return row + 69 if row <= 35 else row + 70


def test_write_preview_set_writes_portrait_glass_screenshots() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp)
        for stale_name in preview.STALE_PREVIEW_FILES:
            (output_dir / stale_name).write_bytes(b"stale")

        written = preview.write_preview_set(output_dir, scale=2)

        names = {path.name for path in written}
        assert names == {f"left_screen_{case.name}.png" for case in preview.DEMO_CASES}
        assert {path.name for path in output_dir.iterdir()} == names

        for path in written:
            with Image.open(path) as image:
                assert image.mode == "L"
                assert image.size == (preview.GLASS_WIDTH * 2, preview.GLASS_HEIGHT * 2)


def test_write_frame_preview_renders_and_validates_producer_frames() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "frame.png"
        assert preview.write_frame_preview(FRESH_FRAME, output, scale=2) == output
        with Image.open(output) as image:
            assert image.size == (preview.GLASS_WIDTH * 2, preview.GLASS_HEIGHT * 2)

        with pytest.raises(ValueError):
            preview.write_frame_preview("KP2|SUN|TOO|FEW|FIELDS", Path(tmp) / "bad.png")


def test_parse_live_frame_accepts_firmware_contract() -> None:
    assert preview.parse_live_frame(FRESH_FRAME) == (
        0xA0,
        0,
        1,
        "SUN",
        0,
        ("SUNNY", "TMP 24C", "12:00", "UV 5", "HUM 40%", "AQI 42"),
    )
    assert preview.parse_live_frame("KP3|0F|0|1|NONE|0||||||") == (0x0F, 0, 1, "NONE", 0, ("",) * 6)
    assert preview.parse_live_frame("KP3|FF|2|5|CLAUDE|2|MAX8CHAR|ABCDEFGH|12345678|IJKLMNOP|87654321|QRSTUVWX") == (
        0xFF,
        2,
        5,
        "CLAUDE",
        2,
        ("MAX8CHAR", "ABCDEFGH", "12345678", "IJKLMNOP", "87654321", "QRSTUVWX"),
    )


def test_parse_live_frame_returns_idx_and_total() -> None:
    generation, idx, total, icon, led_hint, lines = preview.parse_live_frame(
        "KP3|A1|1|3|CLAUDE|2|CLAUDE  |5H   76%|14:30|||"
    )
    assert (generation, idx, total, icon, led_hint) == (0xA1, 1, 3, "CLAUDE", 2)
    assert lines[0] == "CLAUDE  "


def test_live_frame_max_grew_for_led_hint() -> None:
    # 6 text lines * 9 chars (LINE_MAX) + separators, GEN/IDX/TOTAL/ICON/LED.
    assert preview.LIVE_FRAME_MAX == 81


@pytest.mark.parametrize(
    "frame",
    [
        "KP2|A0|0|1|SUN|0|SUNNY|TMP 24C|12:00|||",  # old prefix is not accepted
        "KP3|A|0|1|SUN|0|SUNNY|TMP 24C|12:00|||",  # GEN must be exactly two hex digits
        "KP3|a0|0|1|SUN|0|SUNNY|TMP 24C|12:00|||",  # GEN must be uppercase hex
        "KP3|GG|0|1|SUN|0|SUNNY|TMP 24C|12:00|||",  # GEN must be hex
        "KP3|A0|0|1|SUN|0|SUNNY|TMP 24C|12:00",  # legacy 3-line frame: too few fields
        "KP3|A0|0|1|SUN|0|A|B|C|D|E|F|G",  # too many fields
        "KP3|A0|0|1|SUN|0|TENCHARS10|TMP 24C|12:00|||",  # line longer than LINE_MAX
        "KP3|A0|0|1|SUN|0|SUNNÝ|TMP 24C|12:00|||",  # non-printable-ascii byte
        "KP3|A0|0|1|MOON|0|A|B|C|D|E|",  # icon unknown to icon_from_field()
        "KP3|SUN|SUNNY|TMP 24C|12:00|UV 5|HUM 40%|AQI 42",  # legacy frame: no GEN/IDX/TOTAL
        "KP3|A0|3|3|SUN|0|A|B|C|D|E|",  # idx must be < total
        "KP3|A0|0|0|SUN|0|A|B|C|D|E|",  # total must be >= 1
        "KP3|A0|x|1|SUN|0|A|B|C|D|E|",  # non-digit IDX
        "KP3|A0||1|SUN|0|A|B|C|D|E|",  # empty IDX field
        "KP3|A0|0||SUN|0|A|B|C|D|E|",  # empty TOTAL field
        "KP3|A0|0|1|SUN||A|B|C|D|E|",  # empty LED hint
        "KP3|A0|0|1|SUN|5|A|B|C|D|E|",  # unsupported LED hint
        "KP3|A0|0|1|SUN|00|A|B|C|D|E|",  # LED hint must be one digit
    ],
)
def test_parse_live_frame_rejects_what_firmware_rejects(frame: str) -> None:
    with pytest.raises(ValueError):
        preview.parse_live_frame(frame)


def test_no_data_snapshot_matches_firmware_fallback() -> None:
    snapshot = preview.live_data_snapshot(None)
    assert snapshot == preview.LiveDataSnapshot(
        icon="WARN", led_hint=0, lines=("NO DATA", "WAITING", "", "", "", ""), has_data=False, stale=False
    )


def test_live_lines_split_between_top_and_middle_canvas() -> None:
    snapshot = preview.live_data_snapshot(FRESH_FRAME)
    top = preview.draw_top(STATE, snapshot).image
    middle = preview.draw_middle(STATE, snapshot).image

    line_h = preview.LAYOUT["KEYPOINT_LIVE_TEXT_LINE_HEIGHT"]
    top_band = (0, preview.LAYOUT["KEYPOINT_LIVE_TEXT_Y"], 70, preview.LAYOUT["KEYPOINT_LIVE_TEXT_Y"] + 3 * line_h)
    extra_band = (
        0,
        preview.LAYOUT["KEYPOINT_LIVE_EXTRA_TEXT_Y"],
        70,
        preview.LAYOUT["KEYPOINT_LIVE_EXTRA_TEXT_Y"] + 3 * line_h,
    )
    assert min(top.crop(top_band).tobytes()) == preview.BLACK
    assert min(middle.crop(extra_band).tobytes()) == preview.BLACK


def test_stale_data_stays_readable_with_segmented_health_strip() -> None:
    # LV_COLOR_DEPTH=1 cannot dim, so the firmware keeps stale text at full
    # contrast and signals staleness via the segmented health strip.
    fresh_snapshot = preview.live_data_snapshot(FRESH_FRAME)
    stale_snapshot = preview.live_data_snapshot(FRESH_FRAME, stale=True)

    assert (
        preview.draw_top(STATE, stale_snapshot).image.tobytes()
        == preview.draw_top(STATE, fresh_snapshot).image.tobytes()
    )

    health_y = preview.LAYOUT["KEYPOINT_LIVE_HEALTH_Y"]
    fresh = preview.draw_middle(STATE, fresh_snapshot).image
    stale = preview.draw_middle(STATE, stale_snapshot).image
    assert fresh.getpixel((2, health_y)) == preview.BLACK
    assert fresh.getpixel((10, health_y)) == preview.BLACK  # solid bar
    assert stale.getpixel((2, health_y)) == preview.BLACK
    assert stale.getpixel((10, health_y)) == preview.WHITE  # segment gap


def test_health_strip_is_visible_on_glass() -> None:
    glass = preview.render_left_screen(STATE, FRESH_FRAME)
    health_row = glass_y_middle(preview.LAYOUT["KEYPOINT_LIVE_HEALTH_Y"])
    assert glass.getpixel((glass_x(2), health_row)) == preview.BLACK
    assert glass.getpixel((glass_x(60), health_row)) == preview.BLACK


def test_live_text_is_right_aligned_like_firmware() -> None:
    canvas = preview.draw_top(STATE, preview.live_data_snapshot(FRESH_FRAME)).image
    # Third line "12:00" is 40px wide, right-aligned in the full-width 72px
    # column at x=0: ink starts at x=32, so the left side of its band stays
    # empty (a bare value with no label hugs the right frame).
    line_y = preview.LAYOUT["KEYPOINT_LIVE_TEXT_Y"] + 2 * preview.LAYOUT["KEYPOINT_LIVE_TEXT_LINE_HEIGHT"]
    band = (0, line_y, 70, line_y + 9)
    left_band = (0, line_y, 30, line_y + 9)
    assert min(canvas.crop(band).tobytes()) == preview.BLACK
    assert min(canvas.crop(left_band).tobytes()) == preview.WHITE


def test_title_line_renders_inverted_bar() -> None:
    # The card title (live line 0) is a filled foreground bar with the title
    # text knocked out in the background colour (the active-profile styling).
    canvas = preview.draw_top(STATE, preview.live_data_snapshot(FRESH_FRAME)).image
    width = preview.LAYOUT["KEYPOINT_LIVE_TEXT_WIDTH"]
    bar_y = preview.LAYOUT["KEYPOINT_LIVE_TITLE_BAR_Y"]
    bar_h = preview.LAYOUT["KEYPOINT_LIVE_TITLE_BAR_HEIGHT"]

    # The bar's top row (above the glyphs) is solid foreground across the full
    # width: a regular line leaves this region the white background instead.
    assert canvas.getpixel((1, bar_y)) == preview.BLACK
    assert canvas.getpixel((width - 2, bar_y)) == preview.BLACK
    # The title text is knocked out in the background colour inside the bar.
    bar_band = canvas.crop((0, bar_y, width, bar_y + bar_h))
    assert preview.WHITE in set(bar_band.tobytes())

    # A non-title line stays normal: white background in its empty left gutter.
    line1_y = preview.LAYOUT["KEYPOINT_LIVE_TEXT_Y"] + preview.LAYOUT["KEYPOINT_LIVE_TEXT_LINE_HEIGHT"]
    assert canvas.getpixel((1, line1_y + 4)) == preview.WHITE


def _top(frame: str):
    return preview.draw_top(STATE, preview.live_data_snapshot(frame)).image


def test_page_rail_only_renders_for_multipage_deck() -> None:
    page_y = preview.LAYOUT["KEYPOINT_LIVE_PAGE_Y"]
    thumb_h = preview.LAYOUT["KEYPOINT_LIVE_PAGE_THUMB_HEIGHT"]
    rail_x = preview.LAYOUT["KEYPOINT_LIVE_TEXT_X"]
    rail_w = preview.LAYOUT["KEYPOINT_LIVE_TEXT_WIDTH"]
    thumb_top = page_y - thumb_h // 2

    # A single-page deck shows no indicator at all: the band stays blank.
    single = _top("KP3|A0|0|1|CLAUDE|0|CLAUDE  |5H   76%|14:30|||")
    band = (0, thumb_top, rail_x + rail_w, thumb_top + thumb_h)
    assert min(single.crop(band).tobytes()) == preview.WHITE

    # A multi-page deck draws a full-width rail at page_y.
    first = _top("KP3|A0|0|3|CLAUDE|0|CLAUDE  |5H   76%|14:30|||")
    last = _top("KP3|A0|2|3|CLAUDE|0|CLAUDE  |5H   76%|14:30|||")
    assert first.getpixel((rail_x, page_y)) == preview.BLACK
    assert first.getpixel((rail_x + rail_w - 1, page_y)) == preview.BLACK

    # The thumb (sized 1/N) rides the rail: flush left on page 1, flush right on
    # the last page. Sample just inside each end, off the rounded corners.
    left = rail_x + 2
    right = rail_x + rail_w - 3
    assert first.getpixel((left, thumb_top)) == preview.BLACK
    assert first.getpixel((right, thumb_top)) == preview.WHITE
    assert last.getpixel((left, thumb_top)) == preview.WHITE
    assert last.getpixel((right, thumb_top)) == preview.BLACK


def test_text_wider_than_max_width_fails_fast() -> None:
    # A 9-char line (72px) exactly fills the band; a 10th char overflows it.
    canvas = preview.Canvas(preview.CANVAS_SIZE)
    with pytest.raises(ValueError, match="wider"):
        canvas.draw_text(0, 0, 72, preview.FONT_UNSCII_8, "TENCHARS10", align="left")


def test_layer_info_text_matches_status_info_panel() -> None:
    def with_layer(index: int, label: str | None):
        return preview.StatusState(85, False, "ble", 0, STATE.profile_connected, STATE.profile_bonded, index, label)

    assert preview.layer_info_text(with_layer(0, "ignored")) == "BASE"
    assert preview.layer_info_text(with_layer(2, "  SYMBOL  ")) == "SYMBOL"
    assert preview.layer_info_text(with_layer(7, None)) == "L7"
    assert preview.layer_info_text(with_layer(7, "   ")) == "L7"
    assert preview.layer_info_text(with_layer(1, "ABCDEFGHIJKLMNOPQ")) == "ABCDEFGHIJKLMNO"


def test_glass_orientation_battery_top_profiles_bottom() -> None:
    glass = preview.render_left_screen(STATE, FRESH_FRAME)

    # Battery shell outline pixel: logical top canvas (0, 2).
    assert glass.getpixel((glass_x(0), glass_y_top(2))) == preview.BLACK
    # Active profile slot fill: logical middle canvas (2, KEYPOINT_PROFILE_ROW_Y).
    row_y = preview.LAYOUT["KEYPOINT_PROFILE_ROW_Y"]
    assert glass.getpixel((glass_x(2), glass_y_middle(row_y))) == preview.BLACK
    # Layer text band near the glass bottom has ink.
    layer_band = (0, glass_y_middle(preview.LAYOUT["KEYPOINT_LAYER_TEXT_Y"]), 72, 144)
    assert min(glass.crop(layer_band).tobytes()) == preview.BLACK


def test_glass_seam_rows_stay_blank() -> None:
    # Rotation artifact (dest row 0 = background) + the blank first column of
    # the overlapping middle canvas form a seam between the two blocks.
    glass = preview.render_left_screen(STATE, FRESH_FRAME)
    assert min(glass.crop((0, 0, 72, 1)).tobytes()) == preview.WHITE
    assert min(glass.crop((0, 68, 72, 69)).tobytes()) == preview.WHITE


def test_rotation_duplicates_center_row_and_column() -> None:
    # LVGL's fixed-point -90 deg transform samples source row/col 36 twice.
    glass = preview.render_left_screen(STATE, FRESH_FRAME)
    assert glass.crop((36, 0, 37, 144)).tobytes() == glass.crop((37, 0, 38, 144)).tobytes()
    assert glass.crop((0, 36, 72, 37)).tobytes() == glass.crop((0, 37, 72, 38)).tobytes()


def test_output_symbol_matches_status_c_switch() -> None:
    def state_for(transport: str, index: int):
        return preview.StatusState(50, False, transport, index, STATE.profile_connected, STATE.profile_bonded, 0)

    assert preview.output_symbol(state_for("usb", 0)) == preview.SYMBOL_USB
    assert preview.output_symbol(state_for("ble", 0)) == preview.SYMBOL_WIFI  # connected
    assert preview.output_symbol(state_for("ble", 1)) == preview.SYMBOL_CLOSE  # bonded, offline
    assert preview.output_symbol(state_for("ble", 2)) == preview.SYMBOL_SETTINGS  # open
