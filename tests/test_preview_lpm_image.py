#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["pillow>=11.0"]
# ///

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "preview_lpm_image.py"


def load_module():
    spec = importlib.util.spec_from_file_location("preview_lpm_image", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_generate_previews_creates_expected_keyboard_sized_variants() -> None:
    preview = load_module()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "portrait.png"
        output = tmp_path / "out"

        img = Image.new("RGB", (735, 1024), "white")
        for y in range(img.height):
            tone = int(255 * y / (img.height - 1))
            for x in range(img.width):
                img.putpixel((x, y), (tone, tone // 2, 255 - tone))
        img.save(source)

        written = preview.generate_previews(source, output, size=(72, 120), stem="sample")

        names = {path.name for path in written}
        assert {
            "sample_gray.png",
            "sample_contrast.png",
            "sample_4level.png",
            "sample_4level_dither.png",
            "sample_1bit_dither.png",
            "sample_contact_sheet.png",
            "sample_contact_sheet_x4.png",
            "sample_frame_crop_face.png",
            "sample_frame_crop_center.png",
            "sample_frame_contain.png",
            "sample_framing_contact_sheet.png",
            "sample_framing_contact_sheet_x4.png",
        } <= names
        assert "sample_frame_rot90_crop.png" not in names
        assert "sample_frame_rot270_crop.png" not in names

        for path in written:
            with Image.open(path) as produced:
                if path.name.endswith("_contact_sheet_x4.png") or path.name.endswith("_framing_contact_sheet_x4.png"):
                    assert produced.size[0] > 72 * 4
                    assert produced.size[1] > 120 * 4
                elif path.name.endswith("_contact_sheet.png") or path.name.endswith("_framing_contact_sheet.png"):
                    assert produced.size[0] > 72
                    assert produced.size[1] > 120
                else:
                    assert produced.size == (72, 120)
                    assert produced.mode in {"L", "1"}


if __name__ == "__main__":
    test_generate_previews_creates_expected_keyboard_sized_variants()
