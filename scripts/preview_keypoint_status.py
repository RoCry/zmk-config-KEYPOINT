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
    -> util.c rotate_canvas (LVGL v8 fixed-point -90 deg transform with its
       resampling artifacts: row/col 36 doubled, last row/col dropped)
    -> 144x72 LVGL screen composition (the middle canvas overlaps the top
       canvas' last 4 columns; canvas rows >= 66 never reach the glass)
    -> lpm009m360a rotation=1 panel mapping: the visible 72x144 portrait
       image (top block: battery/output/live lines 1-3/icon, bottom block:
       live lines 4-6, health strip, profiles + layer).

Icon bitmaps, layout constants and the KP3 live-data contract are parsed
from the firmware sources so the preview cannot drift from them. The LVGL
renderer behavior lives in keypoint_lvgl_sim.py; exact font glyph tables in
keypoint_lvgl_fonts.py. RT cases feed demo KP3 frames through the same
parser the firmware uses for the BLE GATT write.

Producers: the KP3 wire protocol and line-layout conventions are documented
in send_keypoint_live_demo.py. To check a candidate frame visually, run
  uv run scripts/preview_keypoint_status.py --frame 'KP3|A0|0|1|SUN|0|...'
which validates it like the firmware would and renders the resulting glass.
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from keypoint_lvgl_sim import (  # noqa: E402
    BLACK,
    FONT_MONTSERRAT_16,
    FONT_UNSCII_8,
    WHITE,
    Canvas,
    Indexed2BitImage,
    rotate_canvas,
)

ROOT = _SCRIPT_DIR.parent
WIDGETS_DIR = ROOT / "config/boards/shields/lpm_view/widgets"

LVGL_SCREEN_WIDTH = 144
LVGL_SCREEN_HEIGHT = 72
MIDDLE_CANVAS_X = 68  # lv_obj_align(middle, LV_ALIGN_TOP_LEFT, 68, 0) in status.c
GLASS_WIDTH = 72
GLASS_HEIGHT = 144

# LV_SYMBOL_* codepoints used by status.c draw_top().
SYMBOL_USB = ""
SYMBOL_WIFI = ""
SYMBOL_CLOSE = ""
SYMBOL_SETTINGS = ""

Transport = Literal["usb", "ble"]


# ---------------------------------------------------------------------------
# Firmware source parsing (single source of truth for layout + contract)
# ---------------------------------------------------------------------------


def _read_widget_source(name: str) -> str:
    return (WIDGETS_DIR / name).read_text()


def _parse_layout_defines() -> dict[str, int]:
    defines: dict[str, int] = {}
    for source_name in ("status_layout.h", "util.h"):
        for name, value in re.findall(r"#define\s+(\w+)\s+(-?\d+)\s*$", _read_widget_source(source_name), re.M):
            defines[name] = int(value)
    for required in ("CANVAS_SIZE", "KEYPOINT_LIVE_ICON_SIZE", "KEYPOINT_PROFILE_ROW_Y"):
        if required not in defines:
            raise ValueError(f"missing #define {required} in widget headers")
    return defines


LAYOUT = _parse_layout_defines()
CANVAS_SIZE = LAYOUT["CANVAS_SIZE"]
PROFILE_COUNT = LAYOUT["KEYPOINT_STATUS_PROFILE_COUNT"]


def _parse_icon_bitmaps() -> dict[str, tuple[str, ...]]:
    source = _read_widget_source("status_layout.h")
    size = LAYOUT["KEYPOINT_LIVE_ICON_SIZE"]
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


def _parse_icon_names() -> tuple[str, ...]:
    """Icon identifiers accepted by enum keypoint_live_data_icon."""
    source = _read_widget_source("live_data.h")
    block_match = re.search(r"enum keypoint_live_data_icon\s*\{(.*?)\};", source, re.S)
    if block_match is None:
        raise ValueError("enum keypoint_live_data_icon not found")
    names = tuple(dict.fromkeys(re.findall(r"KEYPOINT_LIVE_DATA_ICON_([A-Z]+)", block_match.group(1))))
    if "NONE" not in names:
        raise ValueError("keypoint_live_data_icon parse failed")
    missing = [name for name in names if name != "NONE" and name not in ICONS]
    if missing:
        raise ValueError(f"icons accepted by live_data.c without bitmaps: {missing}")
    return names


ICON_NAMES = _parse_icon_names()


def _parse_live_data_contract() -> tuple[str, int, int, int, int, int]:
    source = _read_widget_source("live_data.h")
    prefix_match = re.search(r'#define KEYPOINT_LIVE_DATA_PREFIX "([^"]+)"', source)
    if prefix_match is None:
        raise ValueError("KEYPOINT_LIVE_DATA_PREFIX not found")
    values = {name: int(value) for name, value in re.findall(r"#define KEYPOINT_LIVE_DATA_(\w+) (\d+)", source)}
    return (
        prefix_match.group(1),
        values["GENERATION_FIELD_MAX"],
        values["ICON_MAX"],
        values["LED_HINT_FIELD_MAX"],
        values["TEXT_LINE_COUNT"],
        values["LINE_MAX"],
    )


(
    LIVE_PREFIX,
    LIVE_GENERATION_FIELD_MAX,
    LIVE_ICON_MAX,
    LIVE_LED_HINT_FIELD_MAX,
    LIVE_LINE_COUNT,
    LIVE_LINE_MAX,
) = _parse_live_data_contract()
# GEN + two single-digit page fields precede ICON; one single-digit LED hint follows it.
LIVE_PAGE_FIELD_MAX = 1  # MAX_PAGES = 8 -> idx 0..7, total 1..8 (one digit)
LIVE_FRAME_MAX = (
    len(LIVE_PREFIX)
    + (LIVE_GENERATION_FIELD_MAX + 1)
    + (LIVE_PAGE_FIELD_MAX + 1) * 2
    + (LIVE_LED_HINT_FIELD_MAX + 1)
    + LIVE_ICON_MAX
    + (LIVE_LINE_COUNT * LIVE_LINE_MAX)
    + LIVE_LINE_COUNT
)


def _parse_profile_slot_origins() -> tuple[tuple[int, int], ...]:
    source = _read_widget_source("status_info_panel.h")
    block_match = re.search(r"slot_offsets\[[^]]*\]\[2\]\s*=\s*\{(.*?)\};", source, re.S)
    if block_match is None:
        raise ValueError("slot_offsets not found in status_info_panel.h")
    origins = []
    for x_text, y_text in re.findall(r"\{(\w+),\s*(\w+)\}", block_match.group(1)):
        origins.append((LAYOUT.get(x_text) or int(x_text), LAYOUT[y_text]))
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
# Live data (live_data.c port)
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


def parse_live_frame(frame: str | bytes) -> tuple[int, int, int, str, int, tuple[str, ...]]:
    """Port of keypoint_live_data_parse(); raises ValueError where the firmware
    rejects the GATT write with BT_ATT_ERR_VALUE_NOT_ALLOWED. Frame grammar:
    KP3|GEN|IDX|TOTAL|ICON|LED|L1|..|L6."""
    data = frame.encode() if isinstance(frame, str) else frame
    if len(data) > LIVE_FRAME_MAX:
        raise ValueError(f"frame longer than {LIVE_FRAME_MAX} bytes")
    prefix = LIVE_PREFIX.encode()
    if not data.startswith(prefix):
        raise ValueError(f"frame must start with {LIVE_PREFIX!r}")

    # Fields after the prefix:
    # 0=GEN, 1=IDX, 2=TOTAL, 3=ICON, 4=LED, 5..(4+LINE_COUNT)=lines.
    fields = data[len(prefix) :].split(b"|")
    expected = 5 + LIVE_LINE_COUNT
    if len(fields) != expected:
        raise ValueError(f"expected {expected} fields, got {len(fields)}")

    generation_field = fields[0].decode("latin-1")
    if len(generation_field) != LIVE_GENERATION_FIELD_MAX or not all(
        ch in "0123456789ABCDEF" for ch in generation_field
    ):
        raise ValueError(f"bad generation {generation_field!r}")
    generation = int(generation_field, 16)

    if not (fields[1].isdigit() and fields[2].isdigit()):
        raise ValueError("IDX/TOTAL must be decimal digits")
    if len(fields[1]) > LIVE_PAGE_FIELD_MAX or len(fields[2]) > LIVE_PAGE_FIELD_MAX:
        raise ValueError("IDX/TOTAL exceed one digit")
    idx, total = int(fields[1]), int(fields[2])
    if total < 1 or not (0 <= idx < total):
        raise ValueError(f"bad page idx={idx} total={total}")

    icon_field = fields[3].decode("latin-1")
    if len(icon_field) > LIVE_ICON_MAX or icon_field not in ICON_NAMES:
        raise ValueError(f"unknown icon {icon_field!r}")

    led_field = fields[4].decode("latin-1")
    if len(led_field) != LIVE_LED_HINT_FIELD_MAX or led_field not in {"0", "1", "2", "3", "4"}:
        raise ValueError(f"bad LED hint {led_field!r}")
    led_hint = int(led_field)

    lines = []
    for raw in fields[5:]:
        if len(raw) > LIVE_LINE_MAX or any(not (0x20 <= b <= 0x7E) for b in raw):
            raise ValueError(f"bad line field {raw!r}")
        lines.append(raw.decode("ascii"))
    return generation, idx, total, icon_field, led_hint, tuple(lines)


def live_data_snapshot(frame: str | None, stale: bool = False) -> LiveDataSnapshot:
    """keypoint_live_data_snapshot_get(): WARN/NO DATA before the first frame,
    stale keeps the last payload (which 1-bit rendering then hides)."""
    if frame is None:
        lines = ("NO DATA", "WAITING") + ("",) * (LIVE_LINE_COUNT - 2)
        return LiveDataSnapshot("WARN", 0, lines, has_data=False, stale=False)
    generation, idx, total, icon, led_hint, lines = parse_live_frame(frame)
    return LiveDataSnapshot(
        icon, led_hint, lines, has_data=True, stale=stale, generation=generation, view_index=idx, total_pages=total
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
    x = LAYOUT["KEYPOINT_LIVE_TEXT_X"]
    w = LAYOUT["KEYPOINT_LIVE_TEXT_WIDTH"]
    if len(line) == 5 and line[0] == "[" and line[4] == "]" and line[1:4].isdigit():
        pct = int(line[1:4])
        if 0 <= pct <= 100:
            bar_y = y + 2
            bar_h = 8
            inner_w = w - 2  # 65px fill area
            fill_w = pct * inner_w // 100
            _draw_rect_outline(canvas, x, bar_y, w, bar_h, BLACK)
            if fill_w > 0:
                canvas.fill_rect(x + 1, bar_y + 1, fill_w, bar_h - 2, BLACK)
            return
    canvas.draw_text(x, y, w, FONT_UNSCII_8, line, align="right")


def draw_live_data_panel(canvas: Canvas, snapshot: LiveDataSnapshot) -> None:
    """Top-canvas part of the live panel: icon + lines 1..TOP_LINE_COUNT.

    Stale data stays at full contrast: LV_COLOR_DEPTH=1 cannot dim, so the
    firmware signals staleness via the segmented health strip instead."""
    if snapshot.icon != "NONE":
        for row, bits in enumerate(ICONS[snapshot.icon]):
            for col, bit in enumerate(bits):
                if bit == "1":
                    canvas.fill_rect(
                        LAYOUT["KEYPOINT_LIVE_ICON_X"] + col,
                        LAYOUT["KEYPOINT_LIVE_ICON_Y"] + row,
                        1,
                        1,
                        BLACK,
                    )

    for index, line in enumerate(snapshot.lines[: LAYOUT["KEYPOINT_LIVE_TOP_LINE_COUNT"]]):
        _draw_live_line(canvas, line, LAYOUT["KEYPOINT_LIVE_TEXT_Y"] + index * LAYOUT["KEYPOINT_LIVE_TEXT_LINE_HEIGHT"])

    _draw_live_data_page_rail(canvas, snapshot)


def _draw_live_data_page_rail(canvas: Canvas, snapshot: LiveDataSnapshot) -> None:
    """Port of draw_live_data_page_rail() in status.c: a scrollbar rail (which
    doubles as a status/data divider) with a thumb sized 1/total_pages riding it
    at view_index. Floor-division page->pixel math matches the firmware exactly."""
    if not (snapshot.has_data and snapshot.total_pages > 1):
        return

    x = LAYOUT["KEYPOINT_LIVE_TEXT_X"]
    w = LAYOUT["KEYPOINT_LIVE_TEXT_WIDTH"]
    y = LAYOUT["KEYPOINT_LIVE_PAGE_Y"]
    h = LAYOUT["KEYPOINT_LIVE_PAGE_THUMB_HEIGHT"]

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
    """Middle-canvas part of the live panel: lines TOP_LINE_COUNT+1.. + health strip."""
    for index, line in enumerate(snapshot.lines[LAYOUT["KEYPOINT_LIVE_TOP_LINE_COUNT"] :]):
        _draw_live_line(
            canvas, line, LAYOUT["KEYPOINT_LIVE_EXTRA_TEXT_Y"] + index * LAYOUT["KEYPOINT_LIVE_TEXT_LINE_HEIGHT"]
        )

    # Health strip geometry from status.c draw_live_data_health_strip().
    health_y = LAYOUT["KEYPOINT_LIVE_HEALTH_Y"]
    health_h = LAYOUT["KEYPOINT_LIVE_HEALTH_HEIGHT"]
    if not snapshot.has_data:
        canvas.fill_rect(30, health_y, 13, health_h, BLACK)
    elif snapshot.stale:
        for segment_x in (2, 18, 34, 50, 64):
            canvas.fill_rect(segment_x, health_y, 6, health_h, BLACK)
    else:
        canvas.fill_rect(
            LAYOUT["KEYPOINT_LIVE_HEALTH_X"], health_y, LAYOUT["KEYPOINT_LIVE_HEALTH_WIDTH"], health_h, BLACK
        )


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
    slot_w = LAYOUT["KEYPOINT_PROFILE_SLOT_WIDTH"]
    slot_h = LAYOUT["KEYPOINT_PROFILE_SLOT_HEIGHT"]
    corner = LAYOUT["KEYPOINT_PROFILE_CORNER_SIZE"]
    mark = LAYOUT["KEYPOINT_PROFILE_MARK_SIZE"]
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

    mark_x = x + LAYOUT["KEYPOINT_PROFILE_MARK_X_OFFSET"]
    mark_y = y + LAYOUT["KEYPOINT_PROFILE_MARK_Y_OFFSET"]
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
        LAYOUT["KEYPOINT_LAYER_TEXT_X"],
        LAYOUT["KEYPOINT_LAYER_TEXT_Y"],
        LAYOUT["KEYPOINT_LAYER_TEXT_WIDTH"],
        FONT_UNSCII_8,
        layer_info_text(state),
        align="center",
    )
    return canvas


# ---------------------------------------------------------------------------
# Screen composition + glass view
# ---------------------------------------------------------------------------


def render_lvgl_screen(state: StatusState, snapshot: LiveDataSnapshot) -> Image.Image:
    """The 144x72 LVGL screen: both rotated canvases; the middle canvas is an
    opaque sibling drawn over the top canvas' last 4 columns."""
    screen = Image.new("L", (LVGL_SCREEN_WIDTH, LVGL_SCREEN_HEIGHT), WHITE)
    screen.paste(rotate_canvas(draw_top(state, snapshot)).image, (0, 0))
    screen.paste(rotate_canvas(draw_middle(state, snapshot)).image, (MIDDLE_CANVAS_X, 0))
    return screen


def glass_view(screen: Image.Image) -> Image.Image:
    """lpm009m360a rotation=1 maps LVGL (x, y) to panel line 143-x, column y;
    the panel is mounted so content reads upright: a 72x144 portrait image with
    glass(gx, gy) = lvgl(gy, 71 - gx). Top block: live data, bottom: profiles."""
    out = Image.new("L", (GLASS_WIDTH, GLASS_HEIGHT), WHITE)
    src = screen.load()
    dst = out.load()
    for gy in range(GLASS_HEIGHT):
        for gx in range(GLASS_WIDTH):
            dst[gx, gy] = src[gy, GLASS_WIDTH - 1 - gx]
    return out


def render_left_screen(state: StatusState, frame: str | None, stale: bool = False) -> Image.Image:
    return glass_view(render_lvgl_screen(state, live_data_snapshot(frame, stale=stale)))


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


def _kv(label: str, value: str) -> str:
    """Pad LABEL + value to a full LINE_MAX-wide line (monospace font ->
    labels form a left column, values a right column). Mirrors the kv()
    helper in send_keypoint_live_demo.py."""
    if len(label) + len(value) >= LIVE_LINE_MAX:
        raise ValueError(f"kv({label!r}, {value!r}) does not fit {LIVE_LINE_MAX} chars with a gap")
    return f"{label}{' ' * (LIVE_LINE_MAX - len(label) - len(value))}{value}"


def _card(
    icon: str,
    *lines: str,
    generation: int = 0xA0,
    idx: int = 0,
    total: int = 1,
    led_hint: int = 0,
) -> str:
    """Build a KP3 frame; missing lines are sent empty."""
    if len(lines) > LIVE_LINE_COUNT:
        raise ValueError(f"at most {LIVE_LINE_COUNT} lines, got {len(lines)}")
    padded = lines + ("",) * (LIVE_LINE_COUNT - len(lines))
    return f"{LIVE_PREFIX}{generation:02X}|{idx}|{total}|{icon}|{led_hint}|" + "|".join(padded)


DEMO_CASES: tuple[PreviewCase, ...] = (
    PreviewCase(
        name="rt_sun_base",
        state=StatusState(85, False, "ble", 0, _PROFILES_CONNECTED, _PROFILES_BONDED, 0),
        frame=_card(
            "SUN", "SUNNY".ljust(8), _kv("TMP", "24C"), "12:00", _kv("UV", "5"), _kv("HUM", "40%"), _kv("AQI", "42")
        ),
    ),
    PreviewCase(
        name="rt_claude_usb_charging",
        state=StatusState(47, True, "usb", 0, _PROFILES_CONNECTED, _PROFILES_BONDED, 1, "LOWER"),
        frame=_card(
            "CLAUDE",
            "CLAUDE".ljust(8),
            _kv("5H", "22%"),
            "14:32",
            _kv("WK", "41%"),
            _kv("CTX", "64%"),
            _kv("TOK", "81K"),
            led_hint=2,
        ),
    ),
    PreviewCase(
        # Bonded but disconnected active profile -> LV_SYMBOL_CLOSE; stale data
        # stays readable, the segmented health strip flags the staleness.
        name="rt_codex_stale",
        state=StatusState(72, False, "ble", 1, _PROFILES_CONNECTED, _PROFILES_BONDED, 0),
        frame=_card(
            "CODEX", "CODEX".ljust(8), _kv("5H", "58%"), "09:30", _kv("7D", "45%"), _kv("RST", "3H"), _kv("CTX", "12%")
        ),
        stale=True,
    ),
    PreviewCase(
        # Every line at the full 8-char width, layer label from L7 fallback.
        name="rt_storm_max_width",
        state=StatusState(100, True, "ble", 0, _PROFILES_CONNECTED, _PROFILES_BONDED, 7),
        frame=_card(
            "RAIN",
            "STORM".ljust(8),
            _kv("TMP", "14C"),
            "18:05:33",
            _kv("RAIN", "9MM"),
            _kv("GUST", "19M"),
            _kv("VIS", "2KM"),
        ),
    ),
    PreviewCase(
        # Only 3 of 6 lines used -> the extra block stays empty.
        name="rt_temp_short",
        state=StatusState(64, False, "ble", 0, _PROFILES_CONNECTED, _PROFILES_BONDED, 0),
        frame=_card("TEMP", "INDOOR".ljust(8), _kv("IN", "25C"), "22:10"),
    ),
    PreviewCase(
        # Open (unbonded) active profile -> LV_SYMBOL_SETTINGS; no frame ever
        # received -> WARN / NO DATA / WAITING with the short health bar.
        name="no_data_open_profile",
        state=StatusState(15, False, "ble", 2, _PROFILES_CONNECTED, _PROFILES_BONDED, 2, "SYMBOL"),
    ),
)

STALE_PREVIEW_FILES = (
    # Renamed cases.
    "left_screen_rt_rain_max_width.png",
    # Pre-glass-simulation outputs.
    "screen_ok_base.png",
    "screen_stale_lower.png",
    "screen_empty_symbol.png",
    # Component-era outputs.
    "live_ok.png",
    "live_stale.png",
    "live_empty.png",
    "profile_layer.png",
    "status_contact_sheet.png",
    "layer_base.png",
    "layer_symbol.png",
    "profile_grid.png",
    "status_full_screen.png",
)


def scale_image(image: Image.Image, scale: int) -> Image.Image:
    if scale <= 1:
        return image
    return image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)


def write_preview_set(output_dir: Path, scale: int = 4) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale_name in STALE_PREVIEW_FILES:
        (output_dir / stale_name).unlink(missing_ok=True)

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
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/status-preview"))
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
