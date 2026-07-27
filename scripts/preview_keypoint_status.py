#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["pillow>=11.0"]
# ///
"""Pixel-exact preview of the KEYPOINT left-hand (central) status screen.

Simulates the firmware rendering pipeline instead of approximating it:

  status.c draw_top/draw_middle (two logical 72x72 canvases: battery +
  endpoint symbol + live lines 1-3 + icon, then live lines 4-6 + health
  strip + BLE profile grid + layer info)
    -> LVGL 1-bit blending (LV_COLOR_DEPTH=1 turns opacity into a >50%
       threshold, which is why the firmware never dims stale data and
       signals staleness via the segmented health strip instead)
    -> keypoint_lvgl_sim.compose_glass(): rotation (util.c rotate_canvas with
       its resampling artifacts), 144x72 screen composition (the middle canvas
       overlaps the top canvas' last 4 columns; canvas rows >= 66 never reach
       the glass) and the lpm009m360a rotation=1 panel mapping, giving the
       visible 72x144 portrait image (top block: battery/output/live lines
       1-3/icon, bottom block: live lines 4-6, health strip, profiles + layer).

Icon bitmaps and layout constants are parsed from the firmware sources so
the preview cannot drift from them; the KP3 contract (grammar, parser, card
builders) comes from kp3.py, which derives it the same way. The LVGL
renderer behavior and the canvas -> glass transform (including the glass
geometry, also derived from the firmware) live in keypoint_lvgl_sim.py;
exact font glyph tables in keypoint_lvgl_fonts.py. Demo cases feed KP3
frames built by kp3 through the same parser the firmware uses for the BLE
GATT write.

Producers: the KP3 wire protocol and line-layout conventions are documented
in kp3.py. To check a candidate frame visually, run
  uv run scripts/preview_keypoint_status.py --frame 'KP3|A0|0|1|SUN|0|...'
which validates it like the firmware would and renders the resulting glass.

--output-dir belongs to the preview: `write_preview_set()` regenerates it,
dropping any PNG left there by an earlier (or renamed) demo set.
"""

import argparse
import dataclasses
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import kp3  # noqa: E402
from keypoint_lvgl_sim import (  # noqa: E402
    BLACK,
    FONT_MONTSERRAT_16,
    FONT_UNSCII_8,
    GLASS,
    WHITE,
    Canvas,
    Indexed2BitImage,
    compose_glass,
)

ROOT = _SCRIPT_DIR.parent
WIDGETS_DIR = ROOT / "config/boards/shields/lpm_view/widgets"

# LV_SYMBOL_* codepoints used by status.c draw_top().
SYMBOL_USB = ""
SYMBOL_WIFI = ""
SYMBOL_CLOSE = ""
SYMBOL_SETTINGS = ""

Transport = Literal["usb", "ble"]


# ---------------------------------------------------------------------------
# Firmware source parsing (single source of truth for the screen geometry)
# ---------------------------------------------------------------------------


def _read_widget_source(name: str) -> str:
    return (WIDGETS_DIR / name).read_text()


@dataclass(frozen=True, slots=True)
class Layout:
    """Status-screen geometry, read out of status_layout.h and util.h.

    Every field is one `#define` with the `KEYPOINT_` prefix dropped and the
    name lowercased. Declaring them makes the set the preview depends on
    explicit: a define the firmware renames or removes fails the import
    instead of silently rendering at the wrong coordinates.

    Canvas size is not here: it belongs to the glass, so the sim derives it.
    """

    status_profile_count: int

    live_icon_size: int
    live_icon_scale: int
    live_icon_x: int
    live_icon_y: int

    live_text_x: int
    live_text_y: int
    live_text_width: int
    live_text_line_height: int

    live_title_bar_y: int
    live_title_bar_height: int
    live_tip_y: int

    live_page_y: int
    live_page_thumb_height: int

    live_top_line_count: int
    live_extra_text_y: int
    live_health_x: int
    live_health_y: int
    live_health_width: int
    live_health_height: int

    live_bar_margin_y: int
    live_bar_height: int
    live_bar_border: int

    profile_slot_width: int
    profile_slot_height: int
    profile_corner_size: int
    profile_mark_size: int
    profile_mark_x_offset: int
    profile_mark_y_offset: int
    profile_row_y: int

    layer_text_x: int
    layer_text_y: int
    layer_text_width: int


def _parse_layout() -> Layout:
    defines: dict[str, int] = {}
    for source_name in ("status_layout.h", "util.h"):
        for name, value in re.findall(r"#define\s+(\w+)\s+(-?\d+)\s*$", _read_widget_source(source_name), re.M):
            defines[name.removeprefix("KEYPOINT_").lower()] = int(value)
    names = [field.name for field in dataclasses.fields(Layout)]
    if missing := [name for name in names if name not in defines]:
        raise ValueError(f"missing #define(s) in widget headers: {missing}")
    return Layout(**{name: defines[name] for name in names})


LAYOUT = _parse_layout()
CANVAS_SIZE = GLASS.canvas_size
PROFILE_COUNT = LAYOUT.status_profile_count


def _parse_icon_bitmaps() -> dict[str, tuple[str, ...]]:
    source = _read_widget_source("status_layout.h")
    size = LAYOUT.live_icon_size
    icons: dict[str, tuple[str, ...]] = {}
    for match in re.finditer(r"static const char icon_(\w+)\[[^]]*\]\[[^]]*\]\s*=\s*\{(.*?)\};", source, re.S):
        rows = tuple(re.findall(r'"([01]+)"', match.group(2)))
        if len(rows) != size or any(len(row) != size for row in rows):
            raise ValueError(f"icon_{match.group(1)} is not {size}x{size}")
        icons[match.group(1).upper()] = rows
    if not icons:
        raise ValueError("no icon bitmaps found in status_layout.h")
    return icons


ICONS = _parse_icon_bitmaps()


def _require_icon_bitmaps() -> None:
    """Bitmaps are a preview concern, but the icon set is the contract's:
    anything kp3 accepts on the wire must be drawable here."""
    missing = [name for name in kp3.ICON_NAMES if name != "NONE" and name not in ICONS]
    if missing:
        raise ValueError(f"icons accepted by the KP3 contract without a bitmap in status_layout.h: {missing}")


_require_icon_bitmaps()


def _layout_coord(token: str) -> int:
    """Resolve one entry of a C coordinate table: a literal or a layout macro."""
    if token.lstrip("-").isdigit():
        return int(token)
    return getattr(LAYOUT, token.removeprefix("KEYPOINT_").lower())


def _parse_profile_slot_origins() -> tuple[tuple[int, int], ...]:
    source = _read_widget_source("status_info_panel.h")
    block_match = re.search(r"slot_offsets\[[^]]*\]\[2\]\s*=\s*\{(.*?)\};", source, re.S)
    if block_match is None:
        raise ValueError("slot_offsets not found in status_info_panel.h")
    origins = [
        (_layout_coord(x_text), _layout_coord(y_text))
        for x_text, y_text in re.findall(r"\{(\w+),\s*(\w+)\}", block_match.group(1))
    ]
    if len(origins) != PROFILE_COUNT:
        raise ValueError(f"expected {PROFILE_COUNT} profile slots, found {len(origins)}")
    return tuple(origins)


PROFILE_SLOT_ORIGINS = _parse_profile_slot_origins()


def _parse_bolt_image() -> Indexed2BitImage:
    """bolt.c charging glyph (LV_IMG_CF_INDEXED_2BIT)."""
    source = _read_widget_source("bolt.c")
    width = int(re.search(r"\.header\.w = (\d+)", source).group(1))
    height = int(re.search(r"\.header\.h = (\d+)", source).group(1))
    body = re.search(r"bolt_map\[\]\s*=\s*\{(.*?)\};", source, re.S).group(1)
    raw = bytes(int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]{1,2})", body))
    stride = (width * 2 + 7) // 8
    pixels = raw[-stride * height :]
    # Last palette block before the bitmap = the non-inverted (#else) palette,
    # 4 BGRA entries. At LV_COLOR_DEPTH=1 any bright channel maps to white.
    palette_raw = raw[-stride * height - 16 : -stride * height]
    palette = []
    for index in range(4):
        b, g, r, a = palette_raw[index * 4 : index * 4 + 4]
        palette.append((WHITE if (r | g | b) & 0x80 else BLACK, a))
    return width, height, tuple(palette), pixels


BOLT_IMAGE = _parse_bolt_image()


# ---------------------------------------------------------------------------
# Live data read model (live_data.c snapshot; the grammar lives in kp3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiveDataSnapshot:
    icon: str
    led_hint: int
    lines: tuple[str, ...]
    has_data: bool
    stale: bool
    generation: int = 0
    view_index: int = 0
    total_pages: int = 1


def live_data_snapshot(frame: str | None, stale: bool = False) -> LiveDataSnapshot:
    """keypoint_live_data_snapshot_get(): WARN/NO DATA before the first frame,
    stale keeps the last payload (which 1-bit rendering then hides).

    Frames go through kp3.parse(), so the preview refuses exactly what the
    firmware's GATT write handler refuses."""
    if frame is None:
        lines = ("NO DATA", "WAITING") + ("",) * (kp3.TEXT_LINE_COUNT - 2)
        return LiveDataSnapshot("WARN", 0, lines, has_data=False, stale=False)
    parsed = kp3.parse(frame)
    return LiveDataSnapshot(
        parsed.icon,
        parsed.led_hint,
        parsed.lines,
        has_data=True,
        stale=stale,
        generation=parsed.generation,
        view_index=parsed.index,
        total_pages=parsed.total,
    )


# ---------------------------------------------------------------------------
# Status state + widget drawing (status.c / util.c / status_info_panel.h port)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatusState:
    battery: int
    charging: bool
    transport: Transport
    active_profile_index: int
    profile_connected: tuple[bool, ...]
    profile_bonded: tuple[bool, ...]
    layer_index: int
    layer_label: str | None = None

    def __post_init__(self) -> None:
        if not (0 <= self.battery <= 100):
            raise ValueError(f"battery {self.battery} out of range")
        if len(self.profile_connected) != PROFILE_COUNT or len(self.profile_bonded) != PROFILE_COUNT:
            raise ValueError(f"profile states must have {PROFILE_COUNT} entries")
        if not (0 <= self.active_profile_index < PROFILE_COUNT):
            raise ValueError(f"active profile {self.active_profile_index} out of range")


def draw_battery(canvas: Canvas, state: StatusState) -> None:
    """util.c draw_battery(): 29x12 shell, fill = (battery + 2) / 4, nub, bolt."""
    canvas.fill_rect(0, 2, 29, 12, BLACK)
    canvas.fill_rect(1, 3, 27, 10, WHITE)
    canvas.fill_rect(2, 4, (state.battery + 2) // 4, 8, BLACK)
    canvas.fill_rect(30, 5, 3, 6, BLACK)
    canvas.fill_rect(31, 6, 1, 4, WHITE)
    if state.charging:
        canvas.draw_indexed_2bit(9, -1, BOLT_IMAGE)


def output_symbol(state: StatusState) -> str:
    if state.transport == "usb":
        return SYMBOL_USB
    if state.profile_bonded[state.active_profile_index]:
        if state.profile_connected[state.active_profile_index]:
            return SYMBOL_WIFI
        return SYMBOL_CLOSE
    return SYMBOL_SETTINGS


def _draw_live_line(canvas: Canvas, line: str, y: int) -> None:
    """Render one live-data line. [NNN] tokens (bar encoding) draw a progress
    rectangle; all other lines draw right-aligned unscii-8 text."""
    x = LAYOUT.live_text_x
    w = LAYOUT.live_text_width
    if len(line) == 5 and line[0] == "[" and line[4] == "]" and line[1:4].isdigit():
        pct = int(line[1:4])
        if 0 <= pct <= 100:
            bar_margin_y = LAYOUT.live_bar_margin_y
            bar_h = LAYOUT.live_bar_height
            bar_border = LAYOUT.live_bar_border
            inner_w = w - 2 * bar_border
            fill_w = pct * inner_w // 100
            bar_y = y + bar_margin_y
            _draw_rect_outline(canvas, x, bar_y, w, bar_h, BLACK)
            if fill_w > 0:
                canvas.fill_rect(x + 1, bar_y + 1, fill_w, bar_h - 2, BLACK)
            return
    canvas.draw_text(x, y, w, FONT_UNSCII_8, line, align="right")


def _draw_title_bar(canvas: Canvas, title: str) -> None:
    """Port of draw_live_data_title(): the card title (live line 0) renders
    inverted -- a filled bar with the text knocked out in the background colour
    and centred, like the active-profile slot. The producer pads the title to
    align its data columns, so trim it before centring."""
    text = title.strip()
    if not text:
        return
    x = LAYOUT.live_text_x
    w = LAYOUT.live_text_width
    canvas.fill_rect(x, LAYOUT.live_title_bar_y, w, LAYOUT.live_title_bar_height, BLACK)
    canvas.draw_text(x, LAYOUT.live_text_y, w, FONT_UNSCII_8, text, align="center", color=WHITE)


def _draw_tip(canvas: Canvas, lines: tuple[str, ...]) -> None:
    """Port of draw_live_data_title()'s sibling draw_live_data_tip(): the
    no-data hint is plain centred text on the top canvas -- none of the
    live-data styling (no inverted title, columns, page rail or health strip)."""
    x = LAYOUT.live_text_x
    w = LAYOUT.live_text_width
    for index, line in enumerate(lines[: LAYOUT.live_top_line_count]):
        if not line:
            continue
        y = LAYOUT.live_tip_y + index * LAYOUT.live_text_line_height
        canvas.draw_text(x, y, w, FONT_UNSCII_8, line, align="center")


def draw_live_data_panel(canvas: Canvas, snapshot: LiveDataSnapshot) -> None:
    """Top-canvas part of the live panel: icon + lines 1..TOP_LINE_COUNT.

    Stale data stays at full contrast: LV_COLOR_DEPTH=1 cannot dim, so the
    firmware signals staleness via the segmented health strip instead."""
    if not snapshot.has_data:
        _draw_tip(canvas, snapshot.lines)
        return

    if snapshot.icon != "NONE":
        scale = LAYOUT.live_icon_scale
        for row, bits in enumerate(ICONS[snapshot.icon]):
            for col, bit in enumerate(bits):
                if bit == "1":
                    canvas.fill_rect(
                        LAYOUT.live_icon_x + col * scale,
                        LAYOUT.live_icon_y + row * scale,
                        scale,
                        scale,
                        BLACK,
                    )

    top_lines = snapshot.lines[: LAYOUT.live_top_line_count]
    _draw_title_bar(canvas, top_lines[0])
    for index, line in enumerate(top_lines[1:], start=1):
        _draw_live_line(canvas, line, LAYOUT.live_text_y + index * LAYOUT.live_text_line_height)

    _draw_live_data_page_rail(canvas, snapshot)


def _draw_live_data_page_rail(canvas: Canvas, snapshot: LiveDataSnapshot) -> None:
    """Port of draw_live_data_page_rail() in status.c: a scrollbar rail (which
    doubles as a status/data divider) with a thumb sized 1/total_pages riding it
    at view_index. Floor-division page->pixel math matches the firmware exactly."""
    if not (snapshot.has_data and snapshot.total_pages > 1):
        return

    x = LAYOUT.live_text_x
    w = LAYOUT.live_text_width
    y = LAYOUT.live_page_y
    h = LAYOUT.live_page_thumb_height

    canvas.fill_rect(x, y, w, 1, BLACK)  # rail / track

    tx = x + snapshot.view_index * w // snapshot.total_pages
    tx_next = x + (snapshot.view_index + 1) * w // snapshot.total_pages
    tw = tx_next - tx
    ty = y - h // 2

    canvas.fill_rect(tx, ty, tw, h, BLACK)  # thumb
    for corner_x in (tx, tx + tw - 1):  # round the four corners
        canvas.fill_rect(corner_x, ty, 1, 1, WHITE)
        canvas.fill_rect(corner_x, ty + h - 1, 1, 1, WHITE)


def draw_live_data_extra(canvas: Canvas, snapshot: LiveDataSnapshot) -> None:
    """Middle-canvas part of the live panel: lines TOP_LINE_COUNT+1.. + health
    strip. The no-data state renders only the centred tip on the top canvas, so
    this whole block is skipped until a deck exists."""
    if not snapshot.has_data:
        return

    for index, line in enumerate(snapshot.lines[LAYOUT.live_top_line_count :]):
        _draw_live_line(canvas, line, LAYOUT.live_extra_text_y + index * LAYOUT.live_text_line_height)

    # Health strip geometry from status.c draw_live_data_health_strip().
    health_y = LAYOUT.live_health_y
    health_h = LAYOUT.live_health_height
    if snapshot.stale:
        for segment_x in (0, 16, 33, 50, 66):
            canvas.fill_rect(segment_x, health_y, 6, health_h, BLACK)
    else:
        canvas.fill_rect(LAYOUT.live_health_x, health_y, LAYOUT.live_health_width, health_h, BLACK)


def draw_top(state: StatusState, snapshot: LiveDataSnapshot) -> Canvas:
    canvas = Canvas(CANVAS_SIZE)
    draw_battery(canvas, state)
    canvas.draw_text(0, 0, CANVAS_SIZE, FONT_MONTSERRAT_16, output_symbol(state), align="right")
    draw_live_data_panel(canvas, snapshot)
    return canvas


def _draw_rect_outline(canvas: Canvas, x: int, y: int, w: int, h: int, color: int) -> None:
    canvas.fill_rect(x, y, w, 1, color)
    canvas.fill_rect(x, y + h - 1, w, 1, color)
    canvas.fill_rect(x, y, 1, h, color)
    canvas.fill_rect(x + w - 1, y, 1, h, color)


def _draw_profile_slot(canvas: Canvas, state: StatusState, index: int, x: int, y: int) -> None:
    slot_w = LAYOUT.profile_slot_width
    slot_h = LAYOUT.profile_slot_height
    corner = LAYOUT.profile_corner_size
    mark = LAYOUT.profile_mark_size
    active = index == state.active_profile_index
    connected = state.profile_connected[index]
    bonded = state.profile_bonded[index]

    if active:
        canvas.fill_rect(x, y, slot_w, slot_h, BLACK)
    elif bonded:
        _draw_rect_outline(canvas, x, y, slot_w, slot_h, BLACK)
    else:
        right = x + slot_w - 1
        bottom = y + slot_h - 1
        canvas.fill_rect(x, y, corner, 1, BLACK)
        canvas.fill_rect(x, y, 1, corner, BLACK)
        canvas.fill_rect(right - corner + 1, y, corner, 1, BLACK)
        canvas.fill_rect(right, y, 1, corner, BLACK)
        canvas.fill_rect(x, bottom, corner, 1, BLACK)
        canvas.fill_rect(x, bottom - corner + 1, 1, corner, BLACK)
        canvas.fill_rect(right - corner + 1, bottom, corner, 1, BLACK)
        canvas.fill_rect(right, bottom - corner + 1, 1, corner, BLACK)

    ink = WHITE if active else BLACK
    canvas.draw_text(x + 1, y + 1, 9, FONT_UNSCII_8, str(index + 1), align="left", color=ink)

    mark_x = x + LAYOUT.profile_mark_x_offset
    mark_y = y + LAYOUT.profile_mark_y_offset
    if connected:
        canvas.fill_rect(mark_x, mark_y, mark, mark, ink)
    elif bonded:
        _draw_rect_outline(canvas, mark_x, mark_y, mark, mark, ink)
    else:
        center = mark // 2
        canvas.fill_rect(mark_x + center, mark_y, 1, mark, ink)
        canvas.fill_rect(mark_x, mark_y + center, mark, 1, ink)


def layer_info_text(state: StatusState) -> str:
    """layer_info_text() in status_info_panel.h, incl. its 16-byte fallback buffer."""
    if state.layer_index == 0:
        return "BASE"
    if state.layer_label is not None:
        label = state.layer_label.strip()[:15]
        if label:
            return label
    return f"L{state.layer_index}"


def draw_middle(state: StatusState, snapshot: LiveDataSnapshot) -> Canvas:
    canvas = Canvas(CANVAS_SIZE)
    draw_live_data_extra(canvas, snapshot)
    for index, (x, y) in enumerate(PROFILE_SLOT_ORIGINS):
        _draw_profile_slot(canvas, state, index, x, y)
    canvas.draw_text(
        LAYOUT.layer_text_x,
        LAYOUT.layer_text_y,
        LAYOUT.layer_text_width,
        FONT_UNSCII_8,
        layer_info_text(state),
        align="center",
    )
    return canvas


# ---------------------------------------------------------------------------
# Glass rendering
# ---------------------------------------------------------------------------


def render_left_screen(state: StatusState, frame: str | None, stale: bool = False) -> Image.Image:
    """The portrait glass image: draw both canvases, then hand them to the sim,
    which owns the canvas -> glass transform (rotation, alignment, panel map).
    Top block: live data, bottom block: profiles + layer."""
    snapshot = live_data_snapshot(frame, stale=stale)
    return compose_glass(draw_top(state, snapshot), draw_middle(state, snapshot))


# ---------------------------------------------------------------------------
# Demo cases + CLI
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreviewCase:
    name: str
    state: StatusState
    frame: str | None = None
    stale: bool = False


_PROFILES_CONNECTED = (True, False, False, False)
_PROFILES_BONDED = (True, True, False, False)

#: Generation the demo deck is stamped with; any two-hex-digit value will do.
_DEMO_GENERATION = 0xA0

# The KEYPOINT keyboard only ever shows the claude + codex usage cards built by
# rcink (producer/rcink/keypoint_cards.py, CARD_ORDER = ("claude", "codex")),
# whose shape kp3.usage_card() owns: title + a window row (countdown to reset)
# and a [bar] utilisation row per window (5H/7D), with L6 empty -- no timestamp
# line (show_timestamp=False), no weather. The countdown strings below follow
# rcink's fmt_countdown (NOW / 12m / 1h23m / 18h / 4d).
DEMO_CASES: tuple[PreviewCase, ...] = (
    PreviewCase(
        # Fresh claude card, low usage, BLE connected on the base layer.
        name="claude_fresh",
        state=StatusState(78, False, "ble", 0, _PROFILES_CONNECTED, _PROFILES_BONDED, 0),
        frame=kp3.claude_card("1h23m", 22, "4d", 41, led_hint=0, generation=_DEMO_GENERATION),
    ),
    PreviewCase(
        # Codex card, one window into the attention band (>=75%) -> LED hint 2,
        # USB charging on the lower layer.
        name="codex_attention",
        state=StatusState(47, True, "usb", 0, _PROFILES_CONNECTED, _PROFILES_BONDED, 1, "LOWER"),
        frame=kp3.codex_card("12m", 78, "2d", 54, led_hint=2, generation=_DEMO_GENERATION),
    ),
    PreviewCase(
        # Claude near the 5H limit: countdown reads NOW, bars near full, warning.
        name="claude_warning",
        state=StatusState(93, False, "ble", 0, _PROFILES_CONNECTED, _PROFILES_BONDED, 0),
        frame=kp3.claude_card("NOW", 96, "18h", 89, led_hint=3, generation=_DEMO_GENERATION),
    ),
    PreviewCase(
        # Bonded but disconnected active profile -> LV_SYMBOL_CLOSE; stale data
        # stays readable, the segmented health strip flags the staleness.
        name="codex_stale",
        state=StatusState(64, False, "ble", 1, _PROFILES_CONNECTED, _PROFILES_BONDED, 0),
        frame=kp3.codex_card("3h5m", 45, "5d", 12, led_hint=0, generation=_DEMO_GENERATION),
        stale=True,
    ),
    PreviewCase(
        # The real two-card deck (claude + codex): viewing page 2/2 shows the
        # page rail with the thumb riding to the right.
        name="claude_codex_deck",
        state=StatusState(78, False, "ble", 0, _PROFILES_CONNECTED, _PROFILES_BONDED, 0),
        frame=kp3.codex_card("1h5m", 33, "6d", 8, led_hint=0, generation=_DEMO_GENERATION, index=1, total=2),
    ),
    PreviewCase(
        # Open (unbonded) active profile -> LV_SYMBOL_SETTINGS; no frame ever
        # received -> centered NO DATA / WAITING tip.
        name="no_data_waiting",
        state=StatusState(15, False, "ble", 2, _PROFILES_CONNECTED, _PROFILES_BONDED, 2, "SYMBOL"),
    ),
)


def scale_image(image: Image.Image, scale: int) -> Image.Image:
    if scale <= 1:
        return image
    return image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)


def write_preview_set(output_dir: Path, scale: int = 4) -> list[Path]:
    """Regenerate the whole preview set.

    Every PNG already in the directory is dropped first: the directory holds
    nothing but this renderer's output, so renaming or removing a demo case
    cannot leave a stale image behind pretending to be current.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for previous in output_dir.glob("*.png"):
        if previous.is_file():
            previous.unlink()

    written: list[Path] = []
    for case in DEMO_CASES:
        image = render_left_screen(case.state, case.frame, stale=case.stale)
        output = output_dir / f"left_screen_{case.name}.png"
        scale_image(image, scale).save(output)
        written.append(output)
    return written


def write_frame_preview(frame: str, output: Path, scale: int = 4, stale: bool = False) -> Path:
    """Producer helper: validate one KP3 frame and render the resulting glass."""
    image = render_left_screen(DEMO_CASES[0].state, frame, stale=stale)
    output.parent.mkdir(parents=True, exist_ok=True)
    scale_image(image, scale).save(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Render pixel-exact KEYPOINT left-screen (72x144 glass) previews.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tmp/status-preview"),
        help="Where the PNGs land. The demo set regenerates it: every PNG already there is dropped first.",
    )
    parser.add_argument("--scale", type=int, default=4)
    parser.add_argument("--frame", help="Render this single KP3 frame instead of the demo set.")
    parser.add_argument("--stale", action="store_true", help="Render --frame in the stale state.")
    args = parser.parse_args()

    if args.frame:
        print(write_frame_preview(args.frame, args.output_dir / "left_screen_frame.png", args.scale, args.stale))
        return

    for path in write_preview_set(args.output_dir, scale=args.scale):
        print(path)


if __name__ == "__main__":
    main()
