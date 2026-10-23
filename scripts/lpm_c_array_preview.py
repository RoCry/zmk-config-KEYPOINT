from __future__ import annotations

import re
from pathlib import Path

from PIL import Image


def _extract_lvgl_int(source: str, field: str) -> int:
    match = re.search(rf"\.{re.escape(field)}\s*=\s*(\d+)", source)
    if match is None:
        raise ValueError(f"missing LVGL {field!r} field")
    return int(match.group(1))


def _select_palette_branch(body: str, *, widget_inverted: bool) -> str:
    active = True
    stack: list[tuple[bool, bool]] = []
    selected: list[str] = []
    for line in body.splitlines():
        directive = line.strip()
        if directive.startswith("#if"):
            if directive != "#if CONFIG_NICE_VIEW_WIDGET_INVERTED":
                raise ValueError(f"unsupported image preprocessor directive: {directive}")
            stack.append((active, False))
            active = active and widget_inverted
        elif directive == "#else":
            if not stack or stack[-1][1]:
                raise ValueError("unexpected or repeated #else in image palette")
            parent, _ = stack[-1]
            stack[-1] = (parent, True)
            active = parent and not widget_inverted
        elif directive == "#endif":
            if not stack:
                raise ValueError("unexpected #endif in image palette")
            active, _ = stack.pop()
        elif directive.startswith("#"):
            raise ValueError(f"unsupported image preprocessor directive: {directive}")
        elif active:
            selected.append(line)
    if stack:
        raise ValueError("unterminated #if in image palette")
    return "\n".join(selected)


def decode_c_array_preview(source: Path, *, widget_inverted: bool = False) -> Image.Image:
    """Decode actual LVGL BGRA palettes, without an implicit color inversion."""
    c_source = source.expanduser().read_text()
    width = _extract_lvgl_int(c_source, "header.w")
    height = _extract_lvgl_int(c_source, "header.h")
    if width <= 0 or height <= 0:
        raise ValueError("LVGL image dimensions must be positive")
    format_match = re.search(r"\.header\.cf\s*=\s*LV_IMG_CF_INDEXED_([124])BIT\b", c_source)
    if format_match is None:
        raise ValueError("expected LVGL INDEXED_1BIT, INDEXED_2BIT or INDEXED_4BIT format")
    bits = int(format_match.group(1))
    data_match = re.search(r"uint8_t\s+\w+_map\[\]\s*=\s*\{(.*?)\};", c_source, flags=re.DOTALL)
    if data_match is None:
        raise ValueError("missing uint8_t *_map[] initializer")
    body = _select_palette_branch(data_match.group(1), widget_inverted=widget_inverted)
    body = re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.DOTALL)
    tokens = [token.strip() for token in body.split(",") if token.strip()]
    if any(re.fullmatch(r"0x[0-9a-fA-F]{1,2}|\d{1,3}", token) is None for token in tokens):
        raise ValueError("image initializer must contain literal byte values")
    values = [int(token, 16 if token.lower().startswith("0x") else 10) for token in tokens]
    if any(value > 255 for value in values):
        raise ValueError("image initializer contains a value outside byte range")
    palette_size = 4 * (1 << bits)
    stride = (width * bits + 7) // 8
    expected = palette_size + stride * height
    if len(values) != expected:
        raise ValueError(f"image has {len(values)} bytes, expected {expected} for {width}x{height} indexed{bits}")
    declared_size = _extract_lvgl_int(c_source, "data_size")
    if declared_size != expected:
        raise ValueError(f"data_size is {declared_size}, expected {expected}")
    colors = [(values[i + 2], values[i + 1], values[i], values[i + 3]) for i in range(0, palette_size, 4)]
    image = Image.new("RGBA", (width, height))
    for y in range(height):
        for x in range(width):
            byte = values[palette_size + y * stride + (x * bits) // 8]
            index = (byte >> (8 - bits - (x * bits) % 8)) & ((1 << bits) - 1)
            image.putpixel((x, y), colors[index])
    return image


def write_c_array_preview(source: Path, output: Path, *, scale: int = 4, widget_inverted: bool = False) -> Path:
    if scale <= 0:
        raise ValueError("scale must be positive")
    image = decode_c_array_preview(source, widget_inverted=widget_inverted)
    if scale > 1:
        image = image.resize((image.width * scale, image.height * scale), resample=Image.Resampling.NEAREST)
    output = output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output
