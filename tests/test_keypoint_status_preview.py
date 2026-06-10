import importlib.util
import tempfile
from pathlib import Path

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


def test_status_preview_writes_representative_canvases() -> None:
    preview = load_module()

    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp)
        written = preview.write_preview_set(output_dir, scale=2)

        names = {path.name for path in written}
        assert {
            "live_ok.png",
            "live_stale.png",
            "live_empty.png",
            "profile_layer.png",
            "status_contact_sheet.png",
        } <= names

        for name in names:
            with Image.open(output_dir / name) as image:
                assert image.mode == "L"
                assert image.size[0] >= preview.CANVAS_SIZE
                assert image.size[1] >= preview.CANVAS_SIZE


def test_live_data_health_strip_distinguishes_ok_stale_and_empty() -> None:
    preview = load_module()

    ok = preview.draw_live_data_canvas(
        preview.LiveDataPreview(icon="SUN", lines=("SUNNY", "TMP 24C", "12:00"), health="ok")
    )
    stale = preview.draw_live_data_canvas(
        preview.LiveDataPreview(icon="SUN", lines=("SUNNY", "TMP 24C", "12:00"), health="stale")
    )
    empty = preview.draw_live_data_canvas(
        preview.LiveDataPreview(icon="WARN", lines=("NO DATA", "WAITING", ""), health="empty")
    )

    assert ok.getpixel((2, preview.LIVE_HEALTH_Y)) == preview.FOREGROUND
    assert ok.getpixel((35, preview.LIVE_HEALTH_Y)) == preview.FOREGROUND
    assert ok.getpixel((69, preview.LIVE_HEALTH_Y)) == preview.FOREGROUND

    assert stale.getpixel((2, preview.LIVE_HEALTH_Y)) == preview.STALE_FOREGROUND
    assert stale.getpixel((10, preview.LIVE_HEALTH_Y)) == preview.BACKGROUND
    assert stale.getpixel((20, preview.LIVE_HEALTH_Y)) == preview.STALE_FOREGROUND

    assert empty.getpixel((2, preview.LIVE_HEALTH_Y)) == preview.BACKGROUND
    assert empty.getpixel((35, preview.LIVE_HEALTH_Y)) == preview.FOREGROUND


def test_live_data_preview_uses_expanded_vertical_area() -> None:
    preview = load_module()

    assert preview.LIVE_TEXT_Y <= 18
    assert preview.LIVE_TEXT_LINE_HEIGHT >= 12
    assert preview.LIVE_ICON_Y >= 56
    assert preview.LIVE_DIVIDER_Y >= 67
    assert preview.LIVE_HEALTH_Y >= 70


def test_profile_layer_preview_keeps_profiles_small_and_layer_visible() -> None:
    preview = load_module()

    assert preview.PROFILE_SLOT_WIDTH <= 18
    assert preview.PROFILE_SLOT_HEIGHT <= 18
    assert preview.PROFILE_MARK_SIZE <= 4
    assert preview.PROFILE_SLOT_Y[0] >= 40
    assert preview.PROFILE_SLOT_Y[0] + preview.PROFILE_SLOT_HEIGHT < preview.LAYER_TEXT_Y
    assert preview.LAYER_TEXT_Y >= 60

    image = preview.draw_profile_layer_canvas(
        (
            preview.ProfilePreview(connected=True, bonded=True),
            preview.ProfilePreview(connected=False, bonded=True),
            preview.ProfilePreview(connected=False, bonded=False),
            preview.ProfilePreview(connected=False, bonded=False),
        ),
        active_index=0,
        layer_label="LOWER",
    )

    assert image.getpixel((preview.PROFILE_SLOT_X[0] + 1, preview.PROFILE_SLOT_Y[0] + 1)) == preview.FOREGROUND
    assert image.getpixel((preview.PROFILE_SLOT_X[0] + 11, preview.PROFILE_SLOT_Y[0] + 11)) == preview.BACKGROUND
    assert image.getpixel((preview.PROFILE_SLOT_X[1] + 1, preview.PROFILE_SLOT_Y[1] + 1)) == preview.BACKGROUND
    assert image.getpixel((preview.PROFILE_SLOT_X[1], preview.PROFILE_SLOT_Y[1])) == preview.FOREGROUND
    assert image.getpixel((preview.PROFILE_SLOT_X[2] + 11, preview.PROFILE_SLOT_Y[2] + 11)) == preview.FOREGROUND
    assert image.getpixel((preview.LAYER_TEXT_X, preview.LAYER_TEXT_Y - 1)) == preview.BACKGROUND
    layer_crop = image.crop((0, preview.LAYER_TEXT_Y, preview.CANVAS_SIZE, preview.CANVAS_SIZE))
    assert min(layer_crop.tobytes()) < preview.BACKGROUND
