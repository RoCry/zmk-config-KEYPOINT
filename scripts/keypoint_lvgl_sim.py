"""Minimal LVGL v8 software-renderer simulation at LV_COLOR_DEPTH=1.

Replicates the exact pixel behavior of the LVGL build inside the KEYPOINT
firmware (ZMK v0.3.0 -> Zephyr 3.5 -> LVGL 8.3):

- blending: lv_color_mix() at 1-bit depth keeps the new color only when the
  effective opacity is > LV_OPA_50, so half-opacity draws are no-ops;
- text: lv_canvas_draw_text() glyph placement, FP4.4 advance rounding and
  left/center/right alignment;
- lines: lv_canvas_draw_line() horizontal lines exclude the end pixel;
- rotation: lv_canvas_transform() fixed-point math (sin 90 deg = 32767 >> 5),
  including its resampling artifacts (center row/col doubled, last dropped).
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from keypoint_lvgl_fonts import MONTSERRAT_16, UNSCII_8  # noqa: E402

LV_OPA_MIN = 2
LV_OPA_50 = 0x7F
LV_OPA_MAX = 253
LV_OPA_COVER = 0xFF

WHITE = 255  # LVGL_BACKGROUND (non-inverted build)
BLACK = 0  # LVGL_FOREGROUND

Align = Literal["left", "center", "right"]

# lv_draw_sw_letter.c opacity tables for the glyph bit depths we use.
_BPP_OPA_TABLES = {
    1: (0, 255),
    4: tuple(range(0, 256, 17)),
}

# (width, height, palette[(color, opa)], byte-aligned 2bpp rows)
Indexed2BitImage = tuple[int, int, tuple[tuple[int, int], ...], bytes]


@dataclass(frozen=True, slots=True)
class LvGlyph:
    adv_w_fp4: int
    box_w: int
    box_h: int
    ofs_x: int
    ofs_y: int
    bitmap: bytes


@dataclass(frozen=True, slots=True)
class LvFont:
    line_height: int
    base_line: int
    bpp: int
    glyphs: dict[int, LvGlyph]

    @classmethod
    def from_table(cls, table: dict) -> "LvFont":
        glyphs = {
            codepoint: LvGlyph(adv, bw, bh, ox, oy, bytes.fromhex(hex_bitmap))
            for codepoint, (adv, bw, bh, ox, oy, hex_bitmap) in table["glyphs"].items()
        }
        return cls(table["line_height"], table["base_line"], table["bpp"], glyphs)

    def glyph(self, char: str) -> LvGlyph:
        glyph = self.glyphs.get(ord(char))
        if glyph is None:
            raise ValueError(f"U+{ord(char):04X} ({char!r}) missing from font")
        return glyph

    def advance(self, char: str) -> int:
        # lv_font_get_glyph_dsc_fmt_txt(): adv_w is FP4.4, rounded to pixels.
        return (self.glyph(char).adv_w_fp4 + (1 << 3)) >> 4

    def text_width(self, text: str) -> int:
        return sum(self.advance(char) for char in text)


FONT_UNSCII_8 = LvFont.from_table(UNSCII_8)
FONT_MONTSERRAT_16 = LvFont.from_table(MONTSERRAT_16)


class Canvas:
    """A square LVGL canvas at LV_COLOR_DEPTH=1 (PIL 'L', pixel values 0/255)."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.image = Image.new("L", (size, size), WHITE)
        self._px = self.image.load()

    def blend(self, x: int, y: int, color: int, opa: int = LV_OPA_COVER, mask: int = 0xFF) -> None:
        if not (0 <= x < self.size and 0 <= y < self.size):
            return
        if opa >= LV_OPA_MAX:
            effective = mask
        elif mask >= LV_OPA_MAX:
            effective = opa
        else:
            effective = (mask * opa) >> 8
        if effective > LV_OPA_50:
            self._px[x, y] = color

    def fill_rect(self, x: int, y: int, w: int, h: int, color: int, opa: int = LV_OPA_COVER) -> None:
        """lv_canvas_draw_rect() with a plain bg-fill descriptor (radius 0)."""
        if opa <= LV_OPA_MIN:
            return
        for py in range(y, y + h):
            for px in range(x, x + w):
                self.blend(px, py, color, opa)

    def hline(self, x1: int, x2: int, y: int, color: int, opa: int = LV_OPA_COVER) -> None:
        """lv_canvas_draw_line(), width 1: LVGL excludes the end x pixel."""
        if opa <= LV_OPA_MIN:
            return
        for px in range(min(x1, x2), max(x1, x2)):
            self.blend(px, y, color, opa)

    def draw_text(
        self,
        x: int,
        y: int,
        max_w: int,
        font: LvFont,
        text: str,
        align: Align,
        color: int = BLACK,
        opa: int = LV_OPA_COVER,
    ) -> None:
        """lv_canvas_draw_text() for single-line text (the firmware never wraps)."""
        if not text:
            return
        width = font.text_width(text)
        if width > max_w:
            raise ValueError(f"text {text!r} is {width}px, wider than {max_w}px: firmware would wrap")
        if align == "right":
            pen_x = x + max_w - width
        elif align == "center":
            pen_x = x + (max_w - width) // 2
        else:
            pen_x = x
        opa_table = _BPP_OPA_TABLES[font.bpp]
        for char in text:
            glyph = font.glyph(char)
            glyph_x = pen_x + glyph.ofs_x
            glyph_y = y + (font.line_height - font.base_line) - glyph.box_h - glyph.ofs_y
            for row in range(glyph.box_h):
                for col in range(glyph.box_w):
                    bit = (row * glyph.box_w + col) * font.bpp
                    value = (glyph.bitmap[bit >> 3] >> (8 - font.bpp - (bit & 7))) & ((1 << font.bpp) - 1)
                    self.blend(glyph_x + col, glyph_y + row, color, opa, mask=opa_table[value])
            pen_x += font.advance(char)

    def draw_indexed_2bit(self, x: int, y: int, image: Indexed2BitImage) -> None:
        """lv_canvas_draw_img() for an LV_IMG_CF_INDEXED_2BIT asset."""
        width, height, palette, pixels = image
        stride = (width * 2 + 7) // 8
        for row in range(height):
            for col in range(width):
                bit = col * 2
                index = (pixels[row * stride + (bit >> 3)] >> (6 - (bit & 7))) & 0x3
                color, alpha = palette[index]
                self.blend(x + col, y + row, color, mask=alpha)


def rotate_canvas(canvas: Canvas) -> Canvas:
    """util.c rotate_canvas(): lv_canvas_transform(angle=-900, zoom=none,
    pivot=(size/2, size/2 - 1), no antialias), replicating LVGL v8 fixed-point
    math (sin 90 deg = 32767 >> 5 = 1023). Reproduces the hardware artifacts:
    source row/col size/2 sampled twice, last row/col dropped, dest col/row 0
    left as background."""
    sinma, cosma = 1023, 0
    size = canvas.size
    pivot_x, pivot_y = size // 2, size // 2 - 1
    src = canvas.image.load()
    out = Canvas(size)
    dst = out.image.load()
    for y in range(size):
        for x in range(size):
            xt = x - pivot_x
            yt = y - pivot_y
            xs_int = (((cosma * xt - sinma * yt) >> 2) + pivot_x * 256) >> 8
            ys_int = (((sinma * xt + cosma * yt) >> 2) + pivot_y * 256) >> 8
            if 0 <= xs_int < size and 0 <= ys_int < size:
                dst[x, y] = src[xs_int, ys_int]
    return out
