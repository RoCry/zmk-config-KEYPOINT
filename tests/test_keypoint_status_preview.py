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
            "profile_grid.png",
            "layer_base.png",
            "layer_symbol.png",
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


def test_profile_grid_preview_encodes_active_connected_bonded_and_open_states() -> None:
    preview = load_module()

    image = preview.draw_profile_grid_canvas(
        (
            preview.ProfilePreview(connected=True, bonded=True),
            preview.ProfilePreview(connected=False, bonded=True),
            preview.ProfilePreview(connected=False, bonded=False),
            preview.ProfilePreview(connected=False, bonded=False),
        ),
        active_index=0,
    )

    assert image.getpixel((preview.PROFILE_SLOT_X[0] + 1, preview.PROFILE_SLOT_Y[0] + 1)) == preview.FOREGROUND
    assert image.getpixel((preview.PROFILE_SLOT_X[0] + 23, preview.PROFILE_SLOT_Y[0] + 9)) == preview.BACKGROUND
    assert image.getpixel((preview.PROFILE_SLOT_X[1] + 1, preview.PROFILE_SLOT_Y[1] + 1)) == preview.BACKGROUND
    assert image.getpixel((preview.PROFILE_SLOT_X[1], preview.PROFILE_SLOT_Y[1])) == preview.FOREGROUND
    assert image.getpixel((preview.PROFILE_SLOT_X[2] + 23, preview.PROFILE_SLOT_Y[2] + 9)) == preview.FOREGROUND
