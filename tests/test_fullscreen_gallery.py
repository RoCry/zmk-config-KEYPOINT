"""Gallery assets obey the physical 72x144 fullscreen and RGB111 contract."""

import hashlib
import json
from pathlib import Path

import pytest
from lpm_c_array_preview import decode_c_array_preview
from PIL import Image

PICTURES = Path(__file__).resolve().parents[1] / "config/boards/shields/lpm_view/widgets/picture"
ASSETS = sorted(PICTURES.glob("*.c"))
RGB111 = {
    (0, 0, 0, 255),
    (0, 0, 255, 255),
    (0, 255, 0, 255),
    (0, 255, 255, 255),
    (255, 0, 0, 255),
    (255, 0, 255, 255),
    (255, 255, 0, 255),
    (255, 255, 255, 255),
}


@pytest.mark.parametrize("asset", ASSETS, ids=lambda path: path.stem)
def test_gallery_fills_logical_144_by_72_without_scaling(asset):
    # The mounted 72x144 glass is represented by an exact quarter-turn asset.
    assert decode_c_array_preview(asset).size == (144, 72)


@pytest.mark.parametrize("asset", ASSETS, ids=lambda path: path.stem)
def test_gallery_uses_only_opaque_panel_colors(asset):
    assert set(decode_c_array_preview(asset).get_flattened_data()) <= RGB111


@pytest.mark.parametrize("asset", ASSETS, ids=lambda path: path.stem)
def test_export_matches_user_approved_d_preview_pixels(asset):
    # Frozen from the four D PNGs reviewed and selected by the user, before
    # regenerating C assets. Independent of the exporter/quantizer constants.
    approved = json.loads((Path(__file__).parent / "fixtures/gallery_d.json").read_text())
    portrait = decode_c_array_preview(asset).convert("RGB").transpose(Image.Transpose.ROTATE_270)
    assert hashlib.sha256(portrait.tobytes()).hexdigest() == approved[asset.stem]
