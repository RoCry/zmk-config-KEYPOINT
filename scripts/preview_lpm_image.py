#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["pillow>=11.0"]
# ///

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

DEFAULT_SIZE = (72, 120)
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


def to_gray(image: Image.Image) -> Image.Image:
    return ImageOps.grayscale(image)


def to_contrast_gray(image: Image.Image) -> Image.Image:
    gray = ImageOps.autocontrast(to_gray(image), cutoff=2)
    return ImageEnhance.Contrast(gray).enhance(1.35)


def quantize_gray(image: Image.Image, levels: int, dither: bool) -> Image.Image:
    if levels < 2:
        raise ValueError("levels must be >= 2")

    gray = to_contrast_gray(image)
    dither_mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE

    if levels == 2:
        return gray.convert("1", dither=dither_mode)

    palette = Image.new("P", (1, 1))
    values = [round(i * 255 / (levels - 1)) for i in range(levels)]
    palette_values: list[int] = []
    for value in values:
        palette_values.extend([value, value, value])
    palette_values.extend([0] * (768 - len(palette_values)))
    palette.putpalette(palette_values)

    return gray.convert("RGB").quantize(palette=palette, dither=dither_mode).convert("L")


def draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str) -> None:
    draw.text(xy, text, fill=0)


def write_contact_sheet(variants: list[tuple[str, Image.Image]], output: Path) -> Path:
    tile_w, tile_h = variants[0][1].size
    padding = 10
    label_h = 14
    cols = 3
    rows = (len(variants) + cols - 1) // cols
    sheet_w = cols * tile_w + (cols + 1) * padding
    sheet_h = rows * (tile_h + label_h) + (rows + 1) * padding

    sheet = Image.new("L", (sheet_w, sheet_h), 255)
    draw = ImageDraw.Draw(sheet)

    for index, (name, variant) in enumerate(variants):
        row = index // cols
        col = index % cols
        x = padding + col * (tile_w + padding)
        y = padding + row * (tile_h + label_h + padding)
        sheet.paste(variant.convert("L"), (x, y))
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
        ("gray", to_gray(fitted)),
        ("contrast", to_contrast_gray(fitted)),
        ("4level", quantize_gray(fitted, levels=4, dither=False)),
        ("4level_dither", quantize_gray(fitted, levels=4, dither=True)),
        ("1bit_dither", quantize_gray(fitted, levels=2, dither=True)),
    ]

    written: list[Path] = []
    frame_previews = [(frame_name, to_contrast_gray(frame)) for frame_name, frame in frames]
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
    parser = argparse.ArgumentParser(
        description="Create keyboard-sized grayscale preview PNGs. Does not write C arrays."
    )
    parser.add_argument("--input", required=True, help="Local image path or remote form host:/abs/path")
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
        help="Device preview size, default 72x120 portrait",
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
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

    for path in written:
        print(path)


if __name__ == "__main__":
    main()
