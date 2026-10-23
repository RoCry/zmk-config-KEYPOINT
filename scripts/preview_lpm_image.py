#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["pillow>=12.2"]
# ///

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

try:
    from lpm_c_array_preview import write_c_array_preview
    from lpm_palette import lvgl_palette_bytes, pack_indexed_4bit, quantize_panel
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from lpm_c_array_preview import write_c_array_preview
    from lpm_palette import lvgl_palette_bytes, pack_indexed_4bit, quantize_panel

DEFAULT_SIZE = (72, 144)
DEFAULT_LOGICAL_SIZE = (144, 72)
DEFAULT_FIRMWARE_ROTATION = "ccw"
REMOTE_RE = re.compile(r"^[A-Za-z0-9_.-]+:/")


def parse_size(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)x(\d+)", value)
    if match is None:
        raise argparse.ArgumentTypeError("size must look like WIDTHxHEIGHT, e.g. 120x72")

    width = int(match.group(1))
    height = int(match.group(2))
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("size dimensions must be positive")
    return width, height


def is_remote_path(value: str) -> bool:
    return REMOTE_RE.match(value) is not None


def default_stem(source: str | Path) -> str:
    value = str(source)
    if is_remote_path(value):
        value = value.rsplit("/", 1)[-1]
    return Path(value).stem


def resolve_input(input_path: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    if is_remote_path(input_path):
        suffix = Path(input_path.rsplit("/", 1)[-1]).suffix or ".img"
        local = output_dir / f"_source{suffix}"
        subprocess.run(["scp", input_path, str(local)], check=True)
        return local

    local = Path(input_path).expanduser()
    if not local.is_file():
        raise FileNotFoundError(f"input image not found: {local}")
    return local


def fit_image(image: Image.Image, size: tuple[int, int], focus: tuple[float, float]) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS, centering=focus)


def contain_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    contained = ImageOps.contain(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, "white")
    x = (size[0] - contained.width) // 2
    y = (size[1] - contained.height) // 2
    canvas.paste(contained, (x, y))
    return canvas


def framing_variants(
    image: Image.Image,
    size: tuple[int, int],
    focus: tuple[float, float],
    *,
    include_rotations: bool = False,
) -> list[tuple[str, Image.Image]]:
    rgb = image.convert("RGB")
    variants = [
        ("crop_face", fit_image(rgb, size=size, focus=focus)),
        ("crop_center", fit_image(rgb, size=size, focus=(0.5, 0.5))),
        ("crop_high", fit_image(rgb, size=size, focus=(0.5, 0.28))),
        ("contain", contain_image(rgb, size=size)),
    ]
    if include_rotations:
        rot90 = rgb.rotate(90, expand=True)
        rot270 = rgb.rotate(270, expand=True)
        variants.extend(
            [
                ("rot90_crop", fit_image(rot90, size=size, focus=(0.5, 0.5))),
                ("rot270_crop", fit_image(rot270, size=size, focus=(0.5, 0.5))),
            ]
        )
    return variants


def symbol_macro(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", symbol).strip("_").upper()


def select_named_image(variants: list[tuple[str, Image.Image]], name: str) -> Image.Image:
    for variant_name, image in variants:
        if variant_name == name:
            return image
    names = ", ".join(variant_name for variant_name, _ in variants)
    raise ValueError(f"unknown image variant {name!r}; expected one of: {names}")


def rotate_for_firmware(image: Image.Image, rotation: str) -> Image.Image:
    match rotation:
        case "cw":
            return image.transpose(Image.Transpose.ROTATE_270)
        case "ccw":
            return image.transpose(Image.Transpose.ROTATE_90)
        case "none":
            return image.copy()
        case _:
            raise ValueError("firmware rotation must be one of: cw, ccw, none")


def format_hex_bytes(data: bytes, indent: str = "    ", per_line: int = 16) -> str:
    lines: list[str] = []
    for start in range(0, len(data), per_line):
        chunk = data[start : start + per_line]
        lines.append(indent + ", ".join(f"0x{value:02x}" for value in chunk) + ",")
    return "\n".join(lines)


def write_firmware_c_array(
    source: Path,
    output: Path,
    *,
    symbol: str,
    size: tuple[int, int] = DEFAULT_SIZE,
    logical_size: tuple[int, int] = DEFAULT_LOGICAL_SIZE,
    focus: tuple[float, float] = (0.5, 0.38),
    frame: str = "crop_face",
    rotation: str = DEFAULT_FIRMWARE_ROTATION,
    dither: bool = False,
) -> Path:
    if re.fullmatch(r"[A-Za-z_]\w*", symbol) is None:
        raise ValueError("firmware symbol must be a C identifier")
    with Image.open(source) as original:
        frames = framing_variants(original, size=size, focus=focus)
        portrait = select_named_image(frames, frame)

    dithered = quantize_panel(portrait, dither=dither)
    logical = rotate_for_firmware(dithered, rotation)
    if logical.size != logical_size:
        raise ValueError(
            f"firmware image became {logical.size[0]}x{logical.size[1]}, expected {logical_size[0]}x{logical_size[1]}"
        )

    pixel_bytes = pack_indexed_4bit(logical)
    macro = symbol_macro(symbol)
    data = lvgl_palette_bytes() + pixel_bytes
    source_text = f"""#include <lvgl.h>

/* Source: {source.name}; SHA-256: {hashlib.sha256(source.read_bytes()).hexdigest()}
 * Portrait {size[0]}x{size[1]}, {frame}, focus {focus[0]:g},{focus[1]:g}; rotation {rotation}.
 * RGB111 quantization: {"Floyd-Steinberg" if dither else "nearest palette, no dithering"}. */

#ifndef LV_ATTRIBUTE_MEM_ALIGN
#define LV_ATTRIBUTE_MEM_ALIGN
#endif

#ifndef LV_ATTRIBUTE_IMG_{macro}
#define LV_ATTRIBUTE_IMG_{macro}
#endif

const LV_ATTRIBUTE_MEM_ALIGN LV_ATTRIBUTE_LARGE_CONST LV_ATTRIBUTE_IMG_{macro} uint8_t {symbol}_map[] = {{
    /* RGB111 palette: black, blue, green, cyan, red, magenta, yellow, white.
     * LVGL BGRA entries; unused indices 8..15 are opaque black. */
{format_hex_bytes(data)}
}};

const lv_img_dsc_t {symbol} = {{
    .header.cf = LV_IMG_CF_INDEXED_4BIT,
    .header.always_zero = 0,
    .header.reserved = 0,
    .header.w = {logical_size[0]},
    .header.h = {logical_size[1]},
    .data_size = {len(data)},
    .data = {symbol}_map,
}};
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(source_text)
    return output


def draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str) -> None:
    draw.text(xy, text, fill="black")


def write_contact_sheet(variants: list[tuple[str, Image.Image]], output: Path) -> Path:
    tile_w, tile_h = variants[0][1].size
    tile_w = max(tile_w, 100)
    padding = 10
    label_h = 14
    cols = 3
    rows = (len(variants) + cols - 1) // cols
    sheet_w = cols * tile_w + (cols + 1) * padding
    sheet_h = rows * (tile_h + label_h) + (rows + 1) * padding

    sheet = Image.new("RGB", (sheet_w, sheet_h), "white")
    draw = ImageDraw.Draw(sheet)

    for index, (name, variant) in enumerate(variants):
        row = index // cols
        col = index % cols
        x = padding + col * (tile_w + padding)
        y = padding + row * (tile_h + label_h + padding)
        sheet.paste(variant.convert("RGB"), (x, y))
        draw_label(draw, (x, y + tile_h + 2), name)

    sheet.save(output)
    return output


def write_scaled_preview(source: Path, output: Path, scale: int) -> Path:
    if scale <= 1:
        return source

    with Image.open(source) as image:
        scaled = image.resize((image.width * scale, image.height * scale), resample=Image.Resampling.NEAREST)
        scaled.save(output)
    return output


def generate_previews(
    source: Path,
    output_dir: Path,
    *,
    size: tuple[int, int] = DEFAULT_SIZE,
    stem: str | None = None,
    focus: tuple[float, float] = (0.5, 0.38),
    contact_scale: int = 4,
    include_rotations: bool = False,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    name = stem or source.stem

    with Image.open(source) as original:
        frames = framing_variants(original, size=size, focus=focus, include_rotations=include_rotations)
        fitted = frames[0][1]

    variants = [
        ("source_rgb", fitted),
        ("8color", quantize_panel(fitted, dither=False)),
        ("8color_dither", quantize_panel(fitted)),
    ]

    written: list[Path] = []
    frame_previews = [(frame_name, quantize_panel(frame)) for frame_name, frame in frames]
    for frame_name, image in frame_previews:
        path = output_dir / f"{name}_frame_{frame_name}.png"
        image.save(path)
        written.append(path)

    framing_contact_sheet = write_contact_sheet(frame_previews, output_dir / f"{name}_framing_contact_sheet.png")
    written.append(framing_contact_sheet)
    if contact_scale > 1:
        written.append(
            write_scaled_preview(
                framing_contact_sheet,
                output_dir / f"{name}_framing_contact_sheet_x{contact_scale}.png",
                contact_scale,
            )
        )

    for variant_name, image in variants:
        path = output_dir / f"{name}_{variant_name}.png"
        image.save(path)
        written.append(path)

    contact_sheet = write_contact_sheet(variants, output_dir / f"{name}_contact_sheet.png")
    written.append(contact_sheet)
    if contact_scale > 1:
        written.append(
            write_scaled_preview(
                contact_sheet,
                output_dir / f"{name}_contact_sheet_x{contact_scale}.png",
                contact_scale,
            )
        )
    return written


def copy_for_preview(input_path: str, output_dir: Path) -> Path:
    source = resolve_input(input_path, output_dir)
    if source.parent == output_dir and source.name.startswith("_source"):
        return source

    copied = output_dir / f"_source{source.suffix}"
    shutil.copy2(source, copied)
    return copied


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create RGB111 eight-color previews and optional LVGL C arrays.")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", help="Local image path or remote form host:/abs/path")
    input_group.add_argument("--c-input", type=Path, help="Existing LVGL indexed 1/2/4-bit C array to decode")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tmp/lpm_image_previews"),
        help="Directory for preview PNGs",
    )
    parser.add_argument(
        "--size",
        type=parse_size,
        default=DEFAULT_SIZE,
        help="Device preview size, default 72x144 fullscreen portrait",
    )
    parser.add_argument("--stem", help="Output filename stem")
    parser.add_argument(
        "--focus-x",
        type=float,
        default=0.5,
        help="Crop focus x between 0.0 and 1.0, default 0.5",
    )
    parser.add_argument(
        "--focus-y",
        type=float,
        default=0.38,
        help="Crop focus y between 0.0 and 1.0, default 0.38 for portrait avatars",
    )
    parser.add_argument(
        "--contact-scale",
        type=int,
        default=4,
        help="Nearest-neighbor scale for the enlarged contact sheet, default 4",
    )
    parser.add_argument(
        "--include-rotations",
        action="store_true",
        help="Also write 90/270 degree rotation candidates for display-orientation debugging",
    )
    parser.add_argument("--firmware-c-out", type=Path, help="Optional output path for a LVGL INDEXED_4BIT C array")
    parser.add_argument("--firmware-symbol", help="C symbol name for --firmware-c-out, default: --stem/input stem")
    parser.add_argument(
        "--firmware-logical-size",
        type=parse_size,
        default=DEFAULT_LOGICAL_SIZE,
        help="Logical LVGL image size for firmware output, default 144x72",
    )
    parser.add_argument(
        "--firmware-frame",
        default="crop_face",
        help="Framing variant for firmware output, default crop_face",
    )
    parser.add_argument(
        "--firmware-rotation",
        choices=["cw", "ccw", "none"],
        default=DEFAULT_FIRMWARE_ROTATION,
        help=f"Rotate portrait preview into firmware logical image, default {DEFAULT_FIRMWARE_ROTATION}",
    )
    parser.add_argument(
        "--dither",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable Floyd–Steinberg dithering; default is clean, undithered color blocks",
    )
    parser.add_argument("--c-preview-out", type=Path, help="Output PNG path for --c-input")
    parser.add_argument(
        "--c-preview-scale",
        type=int,
        default=4,
        help="Nearest-neighbor scale for --c-input preview, default 4",
    )
    parser.add_argument(
        "--widget-inverted",
        action="store_true",
        help="Select CONFIG_NICE_VIEW_WIDGET_INVERTED palette branch in legacy C inputs",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.c_input is not None:
        if args.c_preview_out is None:
            raise SystemExit("--c-preview-out is required with --c-input")
        print(
            write_c_array_preview(
                args.c_input,
                args.c_preview_out,
                scale=args.c_preview_scale,
                widget_inverted=args.widget_inverted,
            )
        )
        return

    if not (0.0 <= args.focus_x <= 1.0 and 0.0 <= args.focus_y <= 1.0):
        raise SystemExit("--focus-x and --focus-y must be between 0.0 and 1.0")

    output_dir = args.output_dir.expanduser()
    source = copy_for_preview(args.input, output_dir)
    stem = args.stem or default_stem(args.input)
    written = generate_previews(
        source,
        output_dir,
        size=args.size,
        stem=stem,
        focus=(args.focus_x, args.focus_y),
        contact_scale=args.contact_scale,
        include_rotations=args.include_rotations,
    )
    if args.firmware_c_out is not None:
        symbol = args.firmware_symbol or stem
        written.append(
            write_firmware_c_array(
                source,
                args.firmware_c_out.expanduser(),
                symbol=symbol,
                size=args.size,
                logical_size=args.firmware_logical_size,
                focus=(args.focus_x, args.focus_y),
                frame=args.firmware_frame,
                rotation=args.firmware_rotation,
                dither=args.dither,
            )
        )

    for path in written:
        print(path)


if __name__ == "__main__":
    main()
