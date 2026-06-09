from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

HEX_BYTE_RE = re.compile(r"0x([0-9a-fA-F]{2})")


def _extract_lvgl_int(source: str, field: str) -> int:
    match = re.search(rf"\.{re.escape(field)}\s*=\s*(\d+)", source)
    if match is None:
        raise ValueError(f"missing LVGL {field!r} field")
    return int(match.group(1))


def _extract_lvgl_bitmap_bytes(source: str, width: int, height: int) -> bytes:
    if "LV_IMG_CF_INDEXED_1BIT" not in source:
        raise ValueError("only LV_IMG_CF_INDEXED_1BIT C arrays are supported")

    data_match = re.search(r"uint8_t\s+\w+_map\[\]\s*=\s*\{(?P<body>.*?)\};", source, flags=re.DOTALL)
    if data_match is None:
        raise ValueError("missing uint8_t *_map[] initializer")

    body = data_match.group("body")
    if "#endif" in body:
        values = [int(value, 16) for value in HEX_BYTE_RE.findall(body.rsplit("#endif", 1)[1])]
    else:
        values = [int(value, 16) for value in HEX_BYTE_RE.findall(body)]
        if len(values) < 8:
            raise ValueError("missing 8-byte LVGL indexed image palette")
        values = values[8:]

    expected = ((width + 7) // 8) * height
    if len(values) != expected:
        raise ValueError(f"bitmap has {len(values)} bytes, expected {expected} for {width}x{height}")

    data_size_match = re.search(r"\.data_size\s*=\s*(\d+)", source)
    if data_size_match is not None and int(data_size_match.group(1)) != expected + 8:
        raise ValueError(f"data_size is {data_size_match.group(1)}, expected {expected + 8}")

    return bytes(values)


def _unpack_indexed_1bit(data: bytes, width: int, height: int) -> Image.Image:
    stride = (width + 7) // 8
    image = Image.new("L", (width, height), 0)

    for y in range(height):
        for byte_index in range(stride):
            value = data[y * stride + byte_index]
            for bit in range(8):
                x = byte_index * 8 + bit
                if x < width and value & (1 << (7 - bit)):
                    image.putpixel((x, y), 255)

    return image


def decode_c_array_preview(source: Path) -> Image.Image:
    c_source = source.expanduser().read_text()
    width = _extract_lvgl_int(c_source, "header.w")
    height = _extract_lvgl_int(c_source, "header.h")
    return _unpack_indexed_1bit(_extract_lvgl_bitmap_bytes(c_source, width, height), width, height)


def write_c_array_preview(source: Path, output: Path, *, scale: int = 4) -> Path:
    if scale <= 0:
        raise ValueError("scale must be positive")

    image = decode_c_array_preview(source)
    if scale > 1:
        image = image.resize((image.width * scale, image.height * scale), resample=Image.Resampling.NEAREST)

    output = output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output
