#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["pillow>=11.0"]
# ///

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from lpm_c_array_preview import write_c_array_preview
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from lpm_c_array_preview import write_c_array_preview

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_ROOT = ROOT / "config/boards/shields/lpm_view/widgets"
DEFAULT_OUTPUT_DIR = ROOT / "tmp/lpm_c_previews"


def has_lpm_image_array(source: Path) -> bool:
    return "LV_IMG_CF_INDEXED_1BIT" in source.read_text()


def find_lpm_c_arrays(input_root: Path) -> list[Path]:
    if not input_root.is_dir():
        raise FileNotFoundError(f"input root not found: {input_root}")
    return sorted(path for path in input_root.rglob("*.c") if has_lpm_image_array(path))


def output_path_for(source: Path, output_dir: Path, scale: int) -> Path:
    return output_dir / f"{source.stem}_from_c_x{scale}.png"


def write_all_previews(input_root: Path, output_dir: Path, *, scale: int = 4, invert: bool = True) -> list[Path]:
    if scale <= 0:
        raise ValueError("scale must be positive")

    sources = find_lpm_c_arrays(input_root)
    if not sources:
        raise ValueError(f"no LVGL INDEXED_1BIT C arrays found under {input_root}")

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    seen_outputs: set[Path] = set()
    for source in sources:
        output = output_path_for(source, output_dir, scale)
        if output in seen_outputs:
            raise ValueError(f"duplicate output filename for {source}: {output.name}")
        seen_outputs.add(output)
        written.append(write_c_array_preview(source, output, scale=scale, invert=invert))

    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Decode all LPM LVGL C image arrays into human-preview PNGs.")
    parser.add_argument(
        "--input-root",
        type=Path,
        default=DEFAULT_INPUT_ROOT,
        help=f"Root to scan recursively for C arrays, default {DEFAULT_INPUT_ROOT}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for PNG previews, default {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument("--scale", type=int, default=4, help="Nearest-neighbor preview scale, default 4")
    parser.add_argument(
        "--raw-bits", action="store_true", help="Do not invert pixels; show stored bitmap bits directly"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    written = write_all_previews(
        args.input_root.expanduser(),
        args.output_dir.expanduser(),
        scale=args.scale,
        invert=not args.raw_bits,
    )
    for path in written:
        print(path)
    print(f"Wrote {len(written)} preview(s) to {args.output_dir.expanduser()}")


if __name__ == "__main__":
    main()
