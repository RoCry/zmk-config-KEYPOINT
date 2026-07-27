import importlib.util
import tempfile
from pathlib import Path

import keypoint_lvgl_sim as sim
import kp3
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


def test_write_preview_set_writes_portrait_glass_screenshots() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp)

        written = preview.write_preview_set(output_dir, scale=2)

        names = {path.name for path in written}
        assert names == {f"left_screen_{case.name}.png" for case in preview.DEMO_CASES}
        assert {path.name for path in output_dir.iterdir()} == names

        for path in written:
            with Image.open(path) as image:
                assert image.mode == "L"
                assert image.size == (sim.GLASS.width * 2, sim.GLASS.height * 2)


def test_write_preview_set_regenerates_the_whole_directory() -> None:
    # Output from a renamed or deleted demo case must not survive a rerun --
    # the directory is regenerated, not incrementally pruned by name.
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp)
        (output_dir / "left_screen_renamed_case.png").write_bytes(b"stale")
        (output_dir / "status_contact_sheet.png").write_bytes(b"stale")
        keep = output_dir / "notes.txt"
        keep.write_text("not mine to delete")

        written = preview.write_preview_set(output_dir, scale=2)

        assert {path.name for path in output_dir.glob("*.png")} == {path.name for path in written}
        assert keep.read_text() == "not mine to delete"


def test_write_frame_preview_renders_and_validates_producer_frames() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "frame.png"
        assert preview.write_frame_preview(FRESH_FRAME, output, scale=2) == output
        with Image.open(output) as image:
            assert image.size == (sim.GLASS.width * 2, sim.GLASS.height * 2)

        with pytest.raises(ValueError):
            preview.write_frame_preview("KP2|SUN|TOO|FEW|FIELDS", Path(tmp) / "bad.png")


def test_snapshot_carries_the_parsed_frame_including_deck_position() -> None:
    # The grammar itself is kp3's to police (tests/test_kp3_contract.py); what
    # the preview owns is handing kp3's Frame to the renderer intact.
    snapshot = preview.live_data_snapshot("KP3|A1|1|3|CLAUDE|2|CLAUDE   |5H    76%|14:30|||")
    assert (snapshot.generation, snapshot.view_index, snapshot.total_pages) == (0xA1, 1, 3)
    assert (snapshot.icon, snapshot.led_hint) == ("CLAUDE", 2)
    assert snapshot.lines[0] == "CLAUDE   "
    assert snapshot.has_data and not snapshot.stale


def test_every_contract_icon_can_be_drawn() -> None:
    # Bitmaps are the preview's own concern, but the icon set is the contract's:
    # an icon the wire accepts with no bitmap would render as a blank corner.
    assert set(kp3.ICON_NAMES) - {"NONE"} <= set(preview.ICONS)
    for icon in kp3.ICON_NAMES:
        preview.draw_top(STATE, preview.live_data_snapshot(kp3.build_frame(icon, "X")))


def test_no_data_snapshot_matches_firmware_fallback() -> None:
    snapshot = preview.live_data_snapshot(None)
    assert snapshot == preview.LiveDataSnapshot(
        icon="WARN", led_hint=0, lines=("NO DATA", "WAITING", "", "", "", ""), has_data=False, stale=False
    )


def test_no_data_renders_centered_tip_not_live_grid() -> None:
    # Before any frame arrives the screen shows a centred hint, not the live
    # data UI: no inverted title bar, no right-aligned columns, no health strip.
    snapshot = preview.live_data_snapshot(None)
    top = preview.draw_top(STATE, snapshot).image
    middle = preview.draw_middle(STATE, snapshot).image
    width = preview.LAYOUT.live_text_width

    # No inverted title bar: the bar's top row stays the background colour.
    assert top.getpixel((1, preview.LAYOUT.live_title_bar_y)) == preview.WHITE

    # The hint is centred: both side gutters stay empty, the middle has ink.
    tip_y = preview.LAYOUT.live_tip_y
    assert min(top.crop((0, tip_y, 8, tip_y + 9)).tobytes()) == preview.WHITE
    assert min(top.crop((width - 8, tip_y, width, tip_y + 9)).tobytes()) == preview.WHITE
    assert preview.BLACK in set(top.crop((8, tip_y, width - 8, tip_y + 9)).tobytes())

    # No health strip while there is no data.
    health_y = preview.LAYOUT.live_health_y
    health_h = preview.LAYOUT.live_health_height
    assert min(middle.crop((0, health_y, width, health_y + health_h)).tobytes()) == preview.WHITE


def test_live_lines_split_between_top_and_middle_canvas() -> None:
    snapshot = preview.live_data_snapshot(FRESH_FRAME)
    top = preview.draw_top(STATE, snapshot).image
    middle = preview.draw_middle(STATE, snapshot).image

    line_h = preview.LAYOUT.live_text_line_height
    top_band = (0, preview.LAYOUT.live_text_y, 70, preview.LAYOUT.live_text_y + 3 * line_h)
    extra_band = (
        0,
        preview.LAYOUT.live_extra_text_y,
        70,
        preview.LAYOUT.live_extra_text_y + 3 * line_h,
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

    health_y = preview.LAYOUT.live_health_y
    fresh = preview.draw_middle(STATE, fresh_snapshot).image
    stale = preview.draw_middle(STATE, stale_snapshot).image
    assert fresh.getpixel((2, health_y)) == preview.BLACK
    assert fresh.getpixel((10, health_y)) == preview.BLACK  # solid bar
    assert stale.getpixel((2, health_y)) == preview.BLACK
    assert stale.getpixel((10, health_y)) == preview.WHITE  # segment gap


def test_health_strip_is_visible_on_glass() -> None:
    glass = preview.render_left_screen(STATE, FRESH_FRAME)
    health_y = preview.LAYOUT.live_health_y
    for col in (2, 60):
        assert glass.getpixel(sim.glass_pixel("middle", col, health_y)) == preview.BLACK


def test_live_text_is_right_aligned_like_firmware() -> None:
    canvas = preview.draw_top(STATE, preview.live_data_snapshot(FRESH_FRAME)).image
    # Third line "12:00" is 40px wide, right-aligned in the full-width 72px
    # column at x=0: ink starts at x=32, so the left side of its band stays
    # empty (a bare value with no label hugs the right frame).
    line_y = preview.LAYOUT.live_text_y + 2 * preview.LAYOUT.live_text_line_height
    band = (0, line_y, 70, line_y + 9)
    left_band = (0, line_y, 30, line_y + 9)
    assert min(canvas.crop(band).tobytes()) == preview.BLACK
    assert min(canvas.crop(left_band).tobytes()) == preview.WHITE


def test_title_line_renders_inverted_bar() -> None:
    # The card title (live line 0) is a filled foreground bar with the title
    # text knocked out in the background colour (the active-profile styling).
    canvas = preview.draw_top(STATE, preview.live_data_snapshot(FRESH_FRAME)).image
    width = preview.LAYOUT.live_text_width
    bar_y = preview.LAYOUT.live_title_bar_y
    bar_h = preview.LAYOUT.live_title_bar_height

    # The bar's top row (above the glyphs) is solid foreground across the full
    # width: a regular line leaves this region the white background instead.
    assert canvas.getpixel((1, bar_y)) == preview.BLACK
    assert canvas.getpixel((width - 2, bar_y)) == preview.BLACK
    # The title text is knocked out in the background colour inside the bar.
    bar_band = canvas.crop((0, bar_y, width, bar_y + bar_h))
    assert preview.WHITE in set(bar_band.tobytes())

    # The title is centred: the knocked-out glyphs' side margins match.
    glyph_row = bar_y + bar_h // 2
    whites = [x for x in range(width) if canvas.getpixel((x, glyph_row)) == preview.WHITE]
    assert whites, "expected knocked-out title glyphs"
    assert abs(whites[0] - (width - 1 - whites[-1])) <= 2

    # A non-title line stays normal: white background in its empty left gutter.
    line1_y = preview.LAYOUT.live_text_y + preview.LAYOUT.live_text_line_height
    assert canvas.getpixel((1, line1_y + 4)) == preview.WHITE


def _top(frame: str):
    return preview.draw_top(STATE, preview.live_data_snapshot(frame)).image


def test_page_rail_only_renders_for_multipage_deck() -> None:
    page_y = preview.LAYOUT.live_page_y
    thumb_h = preview.LAYOUT.live_page_thumb_height
    rail_x = preview.LAYOUT.live_text_x
    rail_w = preview.LAYOUT.live_text_width
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


def test_glass_pixel_probe_is_hand_derived_on_purpose() -> None:
    # The one place in this suite that states the canvas -> glass transform
    # itself. Every other glass assertion asks sim.glass_pixel(), which probes
    # the real composition -- without this probe the suite would only ever check
    # the transform by re-applying it, and a wrong rotation would stay green.
    #
    # Worked out by hand from the firmware, for the top-left corner of the
    # battery shell (util.c draw_battery fills 29x12 from top canvas (0, 2), so
    # canvas (0, 2) is set and canvas (0, 1) right above it is background):
    #   1. rotate_canvas() turns the 72x72 canvas -90 deg about (36, 35), so
    #      canvas row r lands in screen column r + 1 (r <= 35; the fixed-point
    #      sampling doubles row 35 and drops the last two rows) and canvas
    #      column c lands in screen row 71 - c (c <= 36)
    #      -> canvas (col 0, row 2) is at LVGL screen (x=3, y=71).
    #   2. the top canvas is aligned at the screen origin, so no offset applies.
    #   3. lpm009m360a rotation=1 plus the panel's mounting show screen (x, y)
    #      at glass (71 - y, x) -> glass (0, 3), with canvas (0, 1) at glass
    #      (0, 2) directly above it.
    glass = preview.render_left_screen(STATE, FRESH_FRAME)
    assert glass.getpixel((0, 3)) == preview.BLACK
    assert glass.getpixel((0, 2)) == preview.WHITE


def test_glass_orientation_battery_top_profiles_bottom() -> None:
    # Where each canvas pixel lands is the sim's answer to give (glass_pixel
    # probes the composition); what this pins is which block ends up where.
    glass = preview.render_left_screen(STATE, FRESH_FRAME)

    # Battery shell outline pixel: logical top canvas (0, 2).
    assert glass.getpixel(sim.glass_pixel("top", 0, 2)) == preview.BLACK
    # Active profile slot fill: logical middle canvas (2, KEYPOINT_PROFILE_ROW_Y).
    assert glass.getpixel(sim.glass_pixel("middle", 2, preview.LAYOUT.profile_row_y)) == preview.BLACK
    # Layer text band near the glass bottom has ink.
    _, layer_top = sim.glass_pixel("middle", 0, preview.LAYOUT.layer_text_y)
    assert min(glass.crop((0, layer_top, sim.GLASS.width, sim.GLASS.height)).tobytes()) == preview.BLACK


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
