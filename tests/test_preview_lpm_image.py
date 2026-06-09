#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["pillow>=11.0"]
# ///

from __future__ import annotations

import importlib.util
import re
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


def bitmap_pixels_from_c_array(c_source: str, symbol: str, width: int, height: int) -> set[tuple[int, int]]:
    map_text = c_source[c_source.index(f"{symbol}_map[]") :]
    map_body = map_text[map_text.index("#endif") :]
    values = [int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]{2})", map_body)]
    bitmap = values[: ((width + 7) // 8) * height]
    pixels: set[tuple[int, int]] = set()

    for y in range(height):
        for byte_index in range((width + 7) // 8):
            value = bitmap[y * ((width + 7) // 8) + byte_index]
            for bit in range(8):
                x = byte_index * 8 + bit
                if x < width and value & (1 << (7 - bit)):
                    pixels.add((x, y))

    return pixels


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


def test_write_firmware_c_array_uses_logical_landscape_lvgl_format() -> None:
    preview = load_module()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "portrait.png"
        output = tmp_path / "sample.c"

        Image.new("RGB", (72, 120), "white").save(source)

        preview.write_firmware_c_array(
            source,
            output,
            symbol="sample",
            size=(72, 120),
            logical_size=(120, 72),
        )

        c_source = output.read_text()
        assert "LV_ATTRIBUTE_IMG_SAMPLE" in c_source
        assert (
            "const LV_ATTRIBUTE_MEM_ALIGN LV_ATTRIBUTE_LARGE_CONST LV_ATTRIBUTE_IMG_SAMPLE uint8_t sample_map[]"
            in c_source
        )
        assert "const lv_img_dsc_t sample" in c_source
        assert ".header.cf = LV_IMG_CF_INDEXED_1BIT" in c_source
        assert ".header.w = 120" in c_source
        assert ".header.h = 72" in c_source
        assert ".data_size = 1088" in c_source


def test_write_firmware_c_array_default_rotation_matches_existing_lpm_assets() -> None:
    preview = load_module()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "marker.png"
        output = tmp_path / "sample.c"

        image = Image.new("RGB", (2, 3), "black")
        image.putpixel((0, 0), (255, 255, 255))
        image.save(source)

        preview.write_firmware_c_array(
            source,
            output,
            symbol="sample",
            size=(2, 3),
            logical_size=(3, 2),
        )

        assert bitmap_pixels_from_c_array(output.read_text(), symbol="sample", width=3, height=2) == {(0, 1)}


if __name__ == "__main__":
    test_generate_previews_creates_expected_keyboard_sized_variants()
    test_write_firmware_c_array_uses_logical_landscape_lvgl_format()
    test_write_firmware_c_array_default_rotation_matches_existing_lpm_assets()
