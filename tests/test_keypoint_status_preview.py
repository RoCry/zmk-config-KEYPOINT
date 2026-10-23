"""Execute firmware rendering through pinned LVGL, check literal design examples."""

from dataclasses import replace

import kp4
import preview_keypoint_status as preview
import pytest
from keypoint_native import StatusState, render_canvas, render_left_screen
from PIL import Image

BLACK, WHITE = (0, 0, 0), (255, 255, 255)
BLUE, GREEN, CYAN = (0, 0, 255), (0, 255, 0), (0, 255, 255)
RED, MAGENTA, YELLOW = (255, 0, 0), (255, 0, 255), (255, 255, 0)
STATE = StatusState(85, False, "ble", 0, (True, False, False, False), (True, True, False, False), 0)
FRAME = "KP4|A0|0|1|CLAUDE|3|003010|CLAUDE|5H  1h23m|[095]|7D     4d|[020]|"


def test_native_preview_exports_eight_color_portrait_pngs(tmp_path):
    written = preview.write_preview_set(tmp_path, scale=2)
    palette = set()
    for path in written:
        with Image.open(path) as image:
            assert image.mode == "RGB"
            assert image.size == (144, 288)
            palette.update(image.get_flattened_data())
    assert palette == {BLACK, WHITE, BLUE, GREEN, CYAN, RED, MAGENTA, YELLOW}


def test_preview_directory_regeneration_preserves_non_images(tmp_path):
    (tmp_path / "obsolete.png").write_bytes(b"old demo")
    (tmp_path / "notes.txt").write_text("keep")
    written = preview.write_preview_set(tmp_path)
    assert set(tmp_path.glob("*.png")) == set(written)
    assert (tmp_path / "notes.txt").read_text() == "keep"


def test_usage_bars_use_independent_producer_roles():
    top = render_canvas(STATE, FRAME, section="top")
    middle = render_canvas(STATE, FRAME, section="middle")
    assert top.getpixel((1, 25)) == BLACK
    assert top.getpixel((1, 57)) == YELLOW
    assert top.getpixel((34, 57)) == BLACK
    assert middle.getpixel((1, 17)) == GREEN
    assert middle.getpixel((20, 17)) == BLACK
    assert middle.getpixel((20, 18)) == BLUE


def test_generic_completion_does_not_infer_warning_from_95_percent():
    frame = "KP4|A0|0|1|CODEX|0|000000|TASK|DONE|[095]|||"
    assert render_canvas(STATE, frame, section="top").getpixel((1, 57)) == CYAN


@pytest.mark.parametrize("role,color", [(1, GREEN), (2, CYAN), (3, YELLOW), (4, RED)])
def test_semantic_text_is_colored_ink_on_black(role, color):
    frame = kp4.build_frame("CODEX", "TASK", "RESULT", row_roles=(0, role, 0, 0, 0, 0))
    row = render_canvas(STATE, frame, section="top").crop((0, 40, 72, 49))
    assert row.getpixel((0, 0)) == BLACK
    assert set(row.get_flattened_data()) == {BLACK, color}


def test_stale_retains_data_and_splits_the_small_health_mark():
    fresh = render_canvas(STATE, FRAME, section="middle")
    stale = render_canvas(STATE, FRAME, section="middle", stale=True)
    assert fresh.crop((0, 0, 72, 36)).tobytes() == stale.crop((0, 0, 72, 36)).tobytes()
    assert fresh.getpixel((69, 65)) == YELLOW
    assert stale.getpixel((69, 64)) == MAGENTA
    assert stale.getpixel((69, 65)) == BLACK


def test_no_data_has_tip_without_title_or_health():
    top = render_canvas(STATE, None, section="top")
    middle = render_canvas(STATE, None, section="middle")
    assert top.getpixel((1, 25)) == BLACK
    assert WHITE in set(top.crop((8, 31, 64, 54)).get_flattened_data())
    assert set(middle.crop((68, 64, 71, 67)).get_flattened_data()) == {BLACK}


def test_exact_rotation_places_battery_and_profiles_without_resampling():
    glass = render_left_screen(STATE, FRAME)
    top = render_canvas(STATE, FRAME, section="top")
    middle = render_canvas(STATE, FRAME, section="middle")
    # Two contiguous 72px sections: no overlap or uncovered 4px bottom strip.
    assert glass.crop((0, 0, 72, 72)).tobytes() == top.tobytes()
    assert glass.crop((0, 72, 72, 144)).tobytes() == middle.tobytes()
    assert glass.getpixel((0, 2)) == WHITE
    assert glass.getpixel((2, 126)) == CYAN
    assert set(glass.crop((0, 141, 72, 144)).get_flattened_data()) == {BLACK}


@pytest.mark.parametrize(
    "battery,charging,color", [(85, False, GREEN), (20, False, YELLOW), (10, False, RED), (40, True, CYAN)]
)
def test_battery_state_color(battery, charging, color):
    state = replace(STATE, battery=battery, charging=charging)
    assert render_canvas(state, FRAME, section="top").getpixel((3, 4)) == color


def test_page_dots_move_without_changing_card_title():
    first = kp4.build_frame("CODEX", "TASK", index=0, total=3)
    last = kp4.build_frame("CODEX", "TASK", index=2, total=3)
    left = render_canvas(STATE, first, section="top")
    right = render_canvas(STATE, last, section="top")
    assert left.getpixel((29, 21)) == CYAN
    assert left.getpixel((41, 21)) == BLACK
    assert right.getpixel((29, 21)) == BLACK
    assert right.getpixel((41, 21)) == CYAN
    assert left.crop((0, 26, 72, 34)).tobytes() == right.crop((0, 26, 72, 34)).tobytes()


@pytest.mark.parametrize("icon", kp4.ICON_NAMES)
def test_each_icon_renders_without_crash(icon):
    image = render_canvas(STATE, kp4.build_frame(icon, icon), section="top")
    occupied = set(image.crop((34, 0, 50, 16)).get_flattened_data()) - {BLACK}
    assert bool(occupied) == (icon != "NONE")


def test_old_protocol_rejected_before_rendering(tmp_path):
    with pytest.raises(ValueError):
        preview.write_frame_preview("KP3|A0|0|1|NONE|0|TITLE|||||", tmp_path / "bad.png")
