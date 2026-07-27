"""Minimal LVGL v8 software-renderer simulation at LV_COLOR_DEPTH=1.

Replicates the exact pixel behavior of the LVGL build inside the KEYPOINT
firmware (ZMK v0.3.0 -> Zephyr 3.5 -> LVGL 8.3):

- blending: lv_color_mix() at 1-bit depth keeps the new color only when the
  effective opacity is > LV_OPA_50, so half-opacity draws are no-ops;
- text: lv_canvas_draw_text() glyph placement, FP4.4 advance rounding and
  left/center/right alignment;
- lines: lv_canvas_draw_line() horizontal lines exclude the end pixel;
- rotation: lv_canvas_transform() fixed-point math (sin 90 deg = 32767 >> 5),
  including its resampling artifacts (center row/col doubled, last dropped);
- glass: the canvas -> glass transform (rotate both canvases, align them on the
  LVGL screen, map that screen through the panel). It lives here once, and
  glass_pixel() answers "where does this canvas pixel land?" by probing it, so
  no caller ever restates it. Its geometry is parsed from the firmware.
"""

import re
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


# ---------------------------------------------------------------------------
# Glass: canvas -> screen -> panel, derived from the firmware sources
# ---------------------------------------------------------------------------

_SHIELD_DIR = _SCRIPT_DIR.parent / "config/boards/shields/lpm_view"

CanvasName = Literal["top", "middle"]


def _firmware_source(relative: str) -> str:
    return (_SHIELD_DIR / relative).read_text()


def _require(pattern: str, relative: str, what: str) -> re.Match[str]:
    """Read one value out of the firmware, or fail: the glass geometry has no
    fallback literal to drift back to."""
    match = re.search(pattern, _firmware_source(relative), re.S)
    if match is None:
        raise ValueError(f"{what} not found in {relative}: the glass geometry cannot be derived")
    return match


@dataclass(frozen=True, slots=True)
class GlassGeometry:
    """Everything the canvas -> glass transform needs, read from the firmware."""

    canvas_size: int  # CANVAS_SIZE, widgets/util.h
    screen_width: int  # the LVGL screen, i.e. the panel's own landscape geometry
    screen_height: int
    middle_offset: tuple[int, int]  # lv_obj_align(middle, LV_ALIGN_TOP_LEFT, x, y)

    @property
    def width(self) -> int:
        """Glass pixels across. The panel is mounted turned on its side, so the
        glass is the LVGL screen transposed: 72 wide by 144 tall."""
        return self.screen_height

    @property
    def height(self) -> int:
        return self.screen_width


def _parse_glass_geometry() -> GlassGeometry:
    canvas_size = int(_require(r"#define\s+CANVAS_SIZE\s+(\d+)", "widgets/util.h", "CANVAS_SIZE").group(1))

    node = _require(
        r'compatible\s*=\s*"jdi,lpm009m360a";(.*?)\};', "lpm_view.overlay", "the lpm009m360a display node"
    ).group(1)
    panel = {
        prop: int(match.group(1))
        for prop in ("width", "height", "rotation")
        if (match := re.search(rf"\b{prop}\s*=\s*<(\d+)>", node))
    }
    if missing := [prop for prop in ("width", "height", "rotation") if prop not in panel]:
        raise ValueError(f"display node in lpm_view.overlay has no {missing}: the glass geometry cannot be derived")
    if panel["rotation"] != 1:
        raise ValueError(f"display rotation is {panel['rotation']}: only the rotation=1 panel mapping is simulated")

    # The driver's line buffer is the same geometry seen from the panel side:
    # `width` lines of `height` bits. Disagreement means one of the two moved.
    bytes_per_line, lines = (
        int(value)
        for value in _require(
            r"uint8_t\s+buf\[(\d+)\s*\*\s*(\d+)\]", "display_driver/lpm009m360a.c", "the panel line buffer"
        ).groups()
    )
    if (lines, bytes_per_line * 8) != (panel["width"], panel["height"]):
        raise ValueError(
            f"lpm009m360a.c line buffer ({lines} lines of {bytes_per_line * 8} px) disagrees with the "
            f"devicetree geometry ({panel['width']}x{panel['height']})"
        )

    align = _require(
        r"lv_obj_align\(middle,\s*LV_ALIGN_TOP_LEFT,\s*(-?\d+),\s*(-?\d+)\)",
        "widgets/status.c",
        "the middle canvas alignment",
    )
    return GlassGeometry(
        canvas_size=canvas_size,
        screen_width=panel["width"],
        screen_height=panel["height"],
        middle_offset=(int(align.group(1)), int(align.group(2))),
    )


GLASS = _parse_glass_geometry()


def _compose_screen(top: Canvas, middle: Canvas) -> Image.Image:
    """The LVGL screen (status.c zmk_widget_status_init): both canvases rotated,
    the top one at the origin (LV_ALIGN_BOTTOM_LEFT with a canvas as tall as the
    screen), the middle one an opaque sibling drawn over the top canvas' tail
    columns at its own alignment offset."""
    screen = Image.new("L", (GLASS.screen_width, GLASS.screen_height), WHITE)
    screen.paste(rotate_canvas(top).image, (0, 0))
    screen.paste(rotate_canvas(middle).image, GLASS.middle_offset)
    return screen


def compose_glass(top: Canvas, middle: Canvas) -> Image.Image:
    """Compose the two logical canvases into the portrait image the glass shows.

    lpm009m360a rotation=1 writes LVGL (x, y) to panel line width-1-x, column y;
    the panel is mounted so content reads upright, which leaves
    glass(gx, gy) = screen(gy, glass_width - 1 - gx)."""
    screen = _compose_screen(top, middle)
    glass = Image.new("L", (GLASS.width, GLASS.height), WHITE)
    src = screen.load()
    dst = glass.load()
    for gy in range(GLASS.height):
        for gx in range(GLASS.width):
            dst[gx, gy] = src[gy, GLASS.width - 1 - gx]
    return glass


def glass_pixel(canvas: CanvasName, col: int, row: int) -> tuple[int, int]:
    """Where canvas pixel (col, row) lands on the glass.

    Probed, not restated: one lit pixel goes through the real compose_glass(),
    which is then scanned for the ink -- so this cannot disagree with what the
    preview renders. Rows and columns the rotation samples twice land twice; the
    first hit (topmost, then leftmost) is returned. Fails fast when the pixel
    never reaches the glass: the rotation drops the last rows/columns, and the
    middle canvas covers the top canvas' tail."""
    size = GLASS.canvas_size
    if not (0 <= col < size and 0 <= row < size):
        raise ValueError(f"({col}, {row}) is outside the {size}x{size} canvas")
    probe = Canvas(size)
    probe.blend(col, row, BLACK)
    blank = Canvas(size)
    glass = compose_glass(probe, blank) if canvas == "top" else compose_glass(blank, probe)
    pixels = glass.load()
    for gy in range(glass.height):
        for gx in range(glass.width):
            if pixels[gx, gy] == BLACK:
                return gx, gy
    raise ValueError(f"{canvas} canvas pixel ({col}, {row}) never reaches the glass")
