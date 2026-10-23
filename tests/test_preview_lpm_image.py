#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["pillow>=12.2", "pytest>=8.0"]
# ///

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lpm_c_array_preview import decode_c_array_preview  # noqa: E402
from lpm_palette import lvgl_palette_bytes, pack_indexed_4bit, quantize_panel  # noqa: E402
from preview_lpm_image import generate_previews, write_firmware_c_array  # noqa: E402


def pixels(image: Image.Image) -> list[object]:
    return [image.getpixel((x, y)) for y in range(image.height) for x in range(image.width)]


def fixture_array(tmp_path: Path, *, bits: int, width: int, body: str, size: int) -> Path:
    path = tmp_path / "fixture.c"
    path.write_text(
        f"uint8_t fixture_map[] = {{\n{body}\n}};\n"
        f"const lv_img_dsc_t fixture = {{.header.cf = LV_IMG_CF_INDEXED_{bits}BIT, "
        f".header.w = {width}, .header.h = 1, .data_size = {size}}};\n"
    )
    return path


def test_lvgl_bgra_palette_and_odd_width_packing_have_literal_goldens() -> None:
    # RGB111 order, independently written LVGL BGRA bytes; 16 slots required.
    assert lvgl_palette_bytes() == bytes.fromhex(
        "000000ff ff0000ff 00ff00ff ffff00ff "
        "0000ffff ff00ffff 00ffffff ffffffff "
        "000000ff 000000ff 000000ff 000000ff "
        "000000ff 000000ff 000000ff 000000ff"
    )
    image = Image.new("P", (3, 2))
    image.putdata([4, 2, 1, 7, 3, 5])
    assert pack_indexed_4bit(image) == bytes.fromhex("42 10 73 50")


def test_quantization_preserves_rgb_primary_colors_and_dithers_midtones() -> None:
    image = Image.new("RGB", (4, 1))
    image.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)])
    assert pixels(quantize_panel(image)) == [4, 2, 1, 6]
    # Hand-calculated FS oracle: gray 128 distributes quantization error into
    # alternating white and black; there is no grayscale preprocessing.
    gray = Image.new("RGB", (2, 2), (128, 128, 128))
    assert pixels(quantize_panel(gray)) == [7, 0, 0, 7]


def test_four_bit_decoder_reads_literal_bgra_and_row_padding(tmp_path: Path) -> None:
    palette = "0x11,0x22,0x33,0x44, 0xaa,0xbb,0xcc,0xdd," + "0,0,0,255," * 14
    path = fixture_array(tmp_path, bits=4, width=3, body=palette + "0x10,0x10,", size=66)
    assert pixels(decode_c_array_preview(path)) == [
        (204, 187, 170, 221),
        (51, 34, 17, 68),
        (204, 187, 170, 221),
    ]


def test_two_bit_decoder_uses_actual_four_entry_palette(tmp_path: Path) -> None:
    path = fixture_array(
        tmp_path,
        bits=2,
        width=4,
        body="0,0,0,255, 0,0,255,255, 0,255,0,255, 255,0,0,255, 0x1b,",
        size=17,
    )
    assert pixels(decode_c_array_preview(path)) == [
        (0, 0, 0, 255),
        (255, 0, 0, 255),
        (0, 255, 0, 255),
        (0, 0, 255, 255),
    ]


def test_legacy_conditional_palette_selects_branch_without_global_inversion(tmp_path: Path) -> None:
    path = fixture_array(
        tmp_path,
        bits=1,
        width=2,
        body=(
            "#if CONFIG_NICE_VIEW_WIDGET_INVERTED\n"
            "255,255,255,255, 0,0,0,255,\n"
            "#else\n0,0,0,255, 255,255,255,255,\n#endif\n0x40,"
        ),
        size=9,
    )
    assert pixels(decode_c_array_preview(path)) == [(0, 0, 0, 255), (255, 255, 255, 255)]
    assert pixels(decode_c_array_preview(path, widget_inverted=True)) == [(255, 255, 255, 255), (0, 0, 0, 255)]


@pytest.mark.parametrize(
    ("body", "size", "error"),
    [
        ("0,0,0,255,255,255,255,255,", 9, "image has 8 bytes"),
        ("0,0,0,255,255,255,255,255,0,", 10, "data_size is 10"),
        ("0,0,0,255,255,255,255,255,256,", 9, "outside byte range"),
        ("#if UNKNOWN\n0,\n#endif", 9, "unsupported image preprocessor"),
        ("#if CONFIG_NICE_VIEW_WIDGET_INVERTED\n0,", 9, "unterminated #if"),
    ],
)
def test_decoder_fails_clearly_on_malformed_arrays(tmp_path: Path, body: str, size: int, error: str) -> None:
    path = fixture_array(tmp_path, bits=1, width=2, body=body, size=size)
    with pytest.raises(ValueError, match=error):
        decode_c_array_preview(path)


def test_export_rotates_rgb_marker_ccw_and_preserves_natural_color(tmp_path: Path) -> None:
    source = tmp_path / "marker.png"
    image = Image.new("RGB", (2, 3), "black")
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((1, 2), (0, 0, 255))
    image.save(source)
    output = tmp_path / "marker.c"
    write_firmware_c_array(source, output, symbol="marker", size=(2, 3), logical_size=(3, 2))
    assert pixels(decode_c_array_preview(output)) == [
        (0, 0, 0, 255),
        (0, 0, 0, 255),
        (0, 0, 255, 255),
        (255, 0, 0, 255),
        (0, 0, 0, 255),
        (0, 0, 0, 255),
    ]
    assert "CONFIG_NICE_VIEW_WIDGET_INVERTED" not in output.read_text()


def test_preview_cli_exports_color_comparison_and_decodes_asset(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (72, 120), "red").save(source)
    written = generate_previews(source, tmp_path / "out", stem="sample")
    names = {path.name for path in written}
    assert {"sample_source_rgb.png", "sample_8color.png", "sample_8color_dither.png"} <= names
    with Image.open(tmp_path / "out" / "sample_contact_sheet.png") as comparison:
        assert comparison.mode == "RGB"
        assert comparison.getpixel((10, 10)) == (255, 0, 0)
    asset = tmp_path / "sample.c"
    write_firmware_c_array(source, asset, symbol="sample")
    preview = tmp_path / "decoded.png"
    subprocess.run(
        [
            "uv",
            "run",
            "--offline",
            str(ROOT / "scripts/preview_lpm_image.py"),
            "--c-input",
            str(asset),
            "--c-preview-out",
            str(preview),
            "--c-preview-scale",
            "1",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    with Image.open(preview) as decoded:
        assert decoded.size == (144, 72)
        assert decoded.getpixel((0, 0)) == (255, 0, 0, 255)


def test_firmware_export_defaults_to_flat_palette_without_midtonal_noise(tmp_path: Path) -> None:
    source = tmp_path / "gray.png"
    Image.new("RGB", (72, 144), (100, 100, 100)).save(source)
    asset = tmp_path / "gray.c"
    write_firmware_c_array(source, asset, symbol="gray")
    assert set(decode_c_array_preview(asset).get_flattened_data()) == {(0, 0, 0, 255)}


def test_batch_preview_includes_fullscreen_portrait(tmp_path: Path) -> None:
    output = tmp_path / "batch"
    subprocess.run(
        [
            "uv",
            "run",
            "--offline",
            str(ROOT / "scripts/preview_all_lpm_c_arrays.py"),
            "--output-dir",
            str(output),
            "--scale",
            "1",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "al_pacino_from_c_x1.png" in {path.name for path in output.glob("*.png")}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
