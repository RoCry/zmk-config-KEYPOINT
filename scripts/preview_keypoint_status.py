#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["pillow>=11.0"]
# ///

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

CANVAS_SIZE = 72
SCREEN_WIDTH = 144
SCREEN_HEIGHT = 72
RIGHT_CANVAS_X = 68
BACKGROUND = 255
FOREGROUND = 0
STALE_FOREGROUND = 150

LIVE_ICON_SIZE = 8
LIVE_ICON_X = 2
LIVE_ICON_Y = 56
LIVE_TEXT_X = 3
LIVE_TEXT_Y = 18
LIVE_TEXT_WIDTH = 67
LIVE_TEXT_LINE_HEIGHT = 12
LIVE_DIVIDER_Y = 67
LIVE_HEALTH_Y = 70
LIVE_HEALTH_X = 2
LIVE_HEALTH_WIDTH = 68

PROFILE_SLOT_WIDTH = 15
PROFILE_SLOT_HEIGHT = 14
PROFILE_CORNER_SIZE = 4
PROFILE_MARK_SIZE = 3
PROFILE_MARK_X_OFFSET = 10
PROFILE_MARK_Y_OFFSET = 9
PROFILE_ROW_Y = 43
PROFILE_SLOT_X = (2, 20, 38, 56)
PROFILE_SLOT_Y = (PROFILE_ROW_Y, PROFILE_ROW_Y, PROFILE_ROW_Y, PROFILE_ROW_Y)

LAYER_TEXT_X = 2
LAYER_TEXT_Y = 61
LAYER_TEXT_WIDTH = 68

STALE_COMPONENT_PREVIEW_FILES = (
    "live_ok.png",
    "live_stale.png",
    "live_empty.png",
    "profile_layer.png",
    "status_contact_sheet.png",
    "layer_base.png",
    "layer_symbol.png",
    "profile_grid.png",
)

HealthState = Literal["ok", "stale", "empty"]


@dataclass(frozen=True, slots=True)
class LiveDataPreview:
    icon: str
    lines: tuple[str, str, str]
    health: HealthState


@dataclass(frozen=True, slots=True)
class ProfilePreview:
    connected: bool
    bonded: bool


ICONS: dict[str, tuple[str, ...]] = {
    "NONE": ("00000000",) * LIVE_ICON_SIZE,
    "SUN": (
        "00100100",
        "00011000",
        "10111101",
        "01111110",
        "01111110",
        "10111101",
        "00011000",
        "00100100",
    ),
    "CLOUD": (
        "00000000",
        "00111000",
        "01111100",
        "11111110",
        "11111110",
        "01111100",
        "00000000",
        "00000000",
    ),
    "RAIN": (
        "00111000",
        "01111100",
        "11111110",
        "01111100",
        "00000000",
        "01001000",
        "10010000",
        "00100100",
    ),
    "TEMP": (
        "00110000",
        "01001000",
        "01001000",
        "01001000",
        "01001000",
        "10000100",
        "10000100",
        "01111000",
    ),
    "WARN": (
        "00010000",
        "00111000",
        "00111000",
        "01101100",
        "01101100",
        "11111110",
        "11101110",
        "11111110",
    ),
    "CODE": (
        "10000010",
        "01000100",
        "00101000",
        "00010000",
        "00101000",
        "01000100",
        "10000010",
        "00010000",
    ),
    "TIME": (
        "00111100",
        "01000010",
        "10010001",
        "10010001",
        "10011101",
        "10000001",
        "01000010",
        "00111100",
    ),
    "CODEX": (
        "00111100",
        "01011010",
        "10100101",
        "10111101",
        "10111101",
        "10100101",
        "01011010",
        "00111100",
    ),
    "CLAUDE": (
        "00010000",
        "00010000",
        "01010100",
        "00111000",
        "11111110",
        "00111000",
        "01010100",
        "00010000",
    ),
}


def font() -> ImageFont.ImageFont:
    return ImageFont.load_default()


def new_canvas() -> Image.Image:
    return Image.new("L", (CANVAS_SIZE, CANVAS_SIZE), BACKGROUND)


def new_screen() -> Image.Image:
    return Image.new("L", (SCREEN_WIDTH, SCREEN_HEIGHT), BACKGROUND)


def draw_rect_outline(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, height: int, fill: int) -> None:
    draw.rectangle((x, y, x + width - 1, y + height - 1), outline=fill)


def draw_plus_marker(draw: ImageDraw.ImageDraw, x: int, y: int, fill: int) -> None:
    center = PROFILE_MARK_SIZE // 2
    draw.rectangle((x + center, y, x + center, y + PROFILE_MARK_SIZE - 1), fill=fill)
    draw.rectangle((x, y + center, x + PROFILE_MARK_SIZE - 1, y + center), fill=fill)


def draw_corner_slot(draw: ImageDraw.ImageDraw, x: int, y: int, fill: int) -> None:
    corner = PROFILE_CORNER_SIZE
    right = x + PROFILE_SLOT_WIDTH - 1
    bottom = y + PROFILE_SLOT_HEIGHT - 1
    draw.rectangle((x, y, x + corner - 1, y), fill=fill)
    draw.rectangle((x, y, x, y + corner - 1), fill=fill)
    draw.rectangle((right - corner + 1, y, right, y), fill=fill)
    draw.rectangle((right, y, right, y + corner - 1), fill=fill)
    draw.rectangle((x, bottom, x + corner - 1, bottom), fill=fill)
    draw.rectangle((x, bottom - corner + 1, x, bottom), fill=fill)
    draw.rectangle((right - corner + 1, bottom, right, bottom), fill=fill)
    draw.rectangle((right, bottom - corner + 1, right, bottom), fill=fill)


def draw_bitmap_icon(draw: ImageDraw.ImageDraw, icon: str, fill: int) -> None:
    for row, bits in enumerate(ICONS[icon]):
        for column, bit in enumerate(bits):
            if bit == "1":
                x = LIVE_ICON_X + column
                y = LIVE_ICON_Y + row
                draw.point((x, y), fill=fill)


def draw_health_strip(draw: ImageDraw.ImageDraw, health: HealthState) -> None:
    if health == "ok":
        draw.rectangle(
            (LIVE_HEALTH_X, LIVE_HEALTH_Y, LIVE_HEALTH_X + LIVE_HEALTH_WIDTH - 1, LIVE_HEALTH_Y + 1),
            fill=FOREGROUND,
        )
        return

    if health == "stale":
        for start in (2, 18, 34, 50, 64):
            draw.rectangle((start, LIVE_HEALTH_Y, min(start + 5, 69), LIVE_HEALTH_Y + 1), fill=STALE_FOREGROUND)
        return

    draw.rectangle((30, LIVE_HEALTH_Y, 42, LIVE_HEALTH_Y + 1), fill=FOREGROUND)


def draw_live_data_canvas(state: LiveDataPreview) -> Image.Image:
    image = new_canvas()
    draw = ImageDraw.Draw(image)
    fill = STALE_FOREGROUND if state.health == "stale" else FOREGROUND

    draw_bitmap_icon(draw, state.icon, fill=fill)
    for index, line in enumerate(state.lines):
        draw.text(
            (LIVE_TEXT_X, LIVE_TEXT_Y + (index * LIVE_TEXT_LINE_HEIGHT)),
            line[:8],
            fill=fill,
            font=font(),
        )

    draw.line((0, LIVE_DIVIDER_Y, 70, LIVE_DIVIDER_Y), fill=fill)
    draw_health_strip(draw, state.health)
    return image


def draw_profile_slot(
    draw: ImageDraw.ImageDraw, profile: ProfilePreview, active: bool, x: int, y: int, label: str
) -> None:
    if active:
        draw.rectangle((x, y, x + PROFILE_SLOT_WIDTH - 1, y + PROFILE_SLOT_HEIGHT - 1), fill=FOREGROUND)
        text_fill = BACKGROUND
        mark_fill = BACKGROUND
    else:
        text_fill = FOREGROUND
        mark_fill = FOREGROUND
        if profile.bonded:
            draw_rect_outline(draw, x, y, PROFILE_SLOT_WIDTH, PROFILE_SLOT_HEIGHT, fill=FOREGROUND)
        else:
            draw_corner_slot(draw, x, y, fill=FOREGROUND)

    draw.text((x + 1, y + 1), label, fill=text_fill, font=font())

    mark_x = x + PROFILE_MARK_X_OFFSET
    mark_y = y + PROFILE_MARK_Y_OFFSET
    if profile.connected:
        draw.rectangle((mark_x, mark_y, mark_x + PROFILE_MARK_SIZE - 1, mark_y + PROFILE_MARK_SIZE - 1), fill=mark_fill)
    elif profile.bonded:
        draw_rect_outline(draw, mark_x, mark_y, PROFILE_MARK_SIZE, PROFILE_MARK_SIZE, fill=mark_fill)
    else:
        draw_plus_marker(draw, mark_x, mark_y, fill=mark_fill)


def draw_profile_grid_canvas(profiles: tuple[ProfilePreview, ...], active_index: int) -> Image.Image:
    if len(profiles) != 4:
        raise ValueError("expected exactly four profile previews")

    image = new_canvas()
    draw = ImageDraw.Draw(image)
    for index, profile in enumerate(profiles):
        draw_profile_slot(
            draw,
            profile=profile,
            active=index == active_index,
            x=PROFILE_SLOT_X[index],
            y=PROFILE_SLOT_Y[index],
            label=str(index + 1),
        )
    return image


def draw_layer_info_canvas(label: str) -> Image.Image:
    image = new_canvas()
    draw = ImageDraw.Draw(image)
    draw_layer_info(draw, label=label)
    return image


def draw_layer_info(draw: ImageDraw.ImageDraw, label: str) -> None:
    text = label.strip()[:8]
    bbox = draw.textbbox((0, 0), text, font=font())
    text_width = bbox[2] - bbox[0]
    draw.text(
        (
            LAYER_TEXT_X + (LAYER_TEXT_WIDTH - text_width) // 2,
            LAYER_TEXT_Y,
        ),
        text,
        fill=FOREGROUND,
        font=font(),
    )


def draw_profile_layer_canvas(profiles: tuple[ProfilePreview, ...], active_index: int, layer_label: str) -> Image.Image:
    image = draw_profile_grid_canvas(profiles=profiles, active_index=active_index)
    draw_layer_info(ImageDraw.Draw(image), label=layer_label)
    return image


def draw_full_screen_preview(
    live: LiveDataPreview,
    profiles: tuple[ProfilePreview, ...],
    active_index: int,
    layer_label: str,
) -> Image.Image:
    screen = new_screen()
    screen.paste(draw_live_data_canvas(live), (0, 0))
    screen.paste(
        draw_profile_layer_canvas(profiles=profiles, active_index=active_index, layer_label=layer_label),
        (RIGHT_CANVAS_X, 0),
    )
    return screen


def scale_image(image: Image.Image, scale: int) -> Image.Image:
    if scale <= 1:
        return image
    return image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)


def write_full_screen_page(images: list[tuple[str, Image.Image]], output: Path, scale: int) -> Path:
    tile_width = SCREEN_WIDTH * scale
    tile_height = SCREEN_HEIGHT * scale
    label_height = 12 * scale
    padding = 6 * scale
    width = tile_width + (padding * 2)
    height = (len(images) * (tile_height + label_height)) + ((len(images) + 1) * padding)
    sheet = Image.new("L", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(sheet)

    for index, (name, image) in enumerate(images):
        x = padding
        y = padding + index * (tile_height + label_height + padding)
        sheet.paste(scale_image(image, scale), (x, y))
        draw.text((x, y + tile_height + 1), name, fill=FOREGROUND, font=font())

    sheet.save(output)
    return output


def write_preview_set(output_dir: Path, scale: int = 4) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale_name in STALE_COMPONENT_PREVIEW_FILES:
        (output_dir / stale_name).unlink(missing_ok=True)

    profiles = (
        ProfilePreview(connected=True, bonded=True),
        ProfilePreview(connected=False, bonded=True),
        ProfilePreview(connected=False, bonded=False),
        ProfilePreview(connected=False, bonded=False),
    )
    samples = [
        (
            "ok / base",
            draw_full_screen_preview(
                live=LiveDataPreview(icon="SUN", lines=("SUNNY", "TMP 24C", "12:00"), health="ok"),
                profiles=profiles,
                active_index=0,
                layer_label="BASE",
            ),
        ),
        (
            "stale / lower",
            draw_full_screen_preview(
                live=LiveDataPreview(icon="CODEX", lines=("CODEX", "7D 45%", "12:00"), health="stale"),
                profiles=profiles,
                active_index=1,
                layer_label="LOWER",
            ),
        ),
        (
            "empty / symbol",
            draw_full_screen_preview(
                live=LiveDataPreview(icon="WARN", lines=("NO DATA", "WAITING", ""), health="empty"),
                profiles=profiles,
                active_index=0,
                layer_label="SYMBOL",
            ),
        ),
    ]

    return [write_full_screen_page(samples, output_dir / "status_full_screen.png", scale=scale)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the KEYPOINT 144x72 status UI preview page.")
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/status-preview"))
    parser.add_argument("--scale", type=int, default=4)
    args = parser.parse_args()

    for path in write_preview_set(args.output_dir, scale=args.scale):
        print(path)


if __name__ == "__main__":
    main()
