"""Panel RGB111 colors and LVGL 8 indexed image encoding."""

from PIL import Image

PANEL_PALETTE = (
    (0, 0, 0),
    (0, 0, 255),
    (0, 255, 0),
    (0, 255, 255),
    (255, 0, 0),
    (255, 0, 255),
    (255, 255, 0),
    (255, 255, 255),
)


def quantize_panel(image: Image.Image, *, dither: bool = True) -> Image.Image:
    """Quantize RGB directly; Floyd–Steinberg approximates intermediate colors."""
    palette = Image.new("P", (1, 1))
    palette.putpalette([channel for color in PANEL_PALETTE for channel in color] + [0] * 744)
    mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    indexed = image.convert("RGB").quantize(palette=palette, dither=mode)
    # Pillow may choose a duplicate black slot; canonical indices stay in 0..7.
    return indexed.point([index if index < 8 else 0 for index in range(256)])


def pack_indexed_4bit(image: Image.Image) -> bytes:
    """LVGL rows are byte-aligned, left pixel in the high nibble."""
    if image.mode != "P":
        raise ValueError("4-bit packing requires an indexed P image")
    packed = bytearray()
    for y in range(image.height):
        for x in range(0, image.width, 2):
            high = image.getpixel((x, y))
            low = image.getpixel((x + 1, y)) if x + 1 < image.width else 0
            if not 0 <= high <= 7 or not 0 <= low <= 7:
                raise ValueError("panel palette indices must be in 0..7")
            packed.append((high << 4) | low)
    return bytes(packed)


def lvgl_palette_bytes() -> bytes:
    """LVGL indexed4 reserves 16 BGRA entries; unused entries are opaque black."""
    return bytes(channel for r, g, b in (*PANEL_PALETTE, *((0, 0, 0),) * 8) for channel in (b, g, r, 255))
