#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""The KP3 contract: one derived home for the frame grammar.

Every contract value here is parsed out of the firmware C sources at import
time -- nothing is restated. `live_data.h` owns the macros and the icon /
LED-hint enums; the widget `.c` sources own the acceptance chains that decide
which icon and LED spellings a GATT write may carry. If the firmware moves,
this module either follows it or fails loudly at import; it never drifts
quietly.

Grammar (see CONTEXT.md for the vocabulary):

    KP3|GEN|IDX|TOTAL|ICON|LED|L1|L2|L3|L4|L5|L6

`parse()` is the single Python KP3 parser and rejects exactly what
`keypoint_live_data_parse()` rejects. `build_frame()` and the `kv` / `title` /
`bar` / card helpers are the single set of builders -- the preview, the BLE
demo sender, the diagnose probe and the rcink producer all go through them so
producer and firmware cannot disagree about the wire.

Stdlib only, on purpose: CI installs no BLE or CLI dependencies, so this
module has to be importable from any test.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parent.parent
WIDGETS_DIR: Final = ROOT / "config/boards/shields/lpm_view/widgets"
CONTRACT_HEADER: Final = WIDGETS_DIR / "live_data.h"
#: Frozen contract for vendored copies that ship without the firmware tree.
CONTRACT_SNAPSHOT: Final = Path(__file__).resolve().with_name("kp3_contract.json")


class ContractError(RuntimeError):
    """The firmware sources no longer support a value this module derives."""


class FrameError(ValueError):
    """A frame the firmware's GATT write handler would reject."""


# ---------------------------------------------------------------------------
# Derived seam: read the contract out of the firmware C
# ---------------------------------------------------------------------------


def _header_source() -> str:
    return CONTRACT_HEADER.read_text()


def _widget_c_sources() -> list[str]:
    """Every .c under the display shield's widgets dir, deepest first.

    The acceptance chains live in whichever implementation file currently
    holds the parser; searching the directory keeps this seam attached to the
    behaviour rather than to a filename.
    """
    return [path.read_text() for path in sorted(WIDGETS_DIR.rglob("*.c"))]


def _macro_ints(source: str) -> dict[str, int]:
    return {
        name: int(value) for name, value in re.findall(r"^#define\s+KEYPOINT_LIVE_DATA_(\w+)\s+(\d+)", source, re.M)
    }


def _macro_int(macros: dict[str, int], name: str) -> int:
    if name not in macros:
        raise ContractError(f"#define KEYPOINT_LIVE_DATA_{name} not found in {CONTRACT_HEADER}")
    return macros[name]


def _parse_prefix(source: str) -> str:
    match = re.search(r'#define\s+KEYPOINT_LIVE_DATA_PREFIX\s+"([^"]+)"', source)
    if match is None:
        raise ContractError("KEYPOINT_LIVE_DATA_PREFIX not found")
    return match.group(1)


_ARITHMETIC: Final[dict[type[ast.operator], object]] = {
    ast.Add: int.__add__,
    ast.Sub: int.__sub__,
    ast.Mult: int.__mul__,
    ast.FloorDiv: int.__floordiv__,
    ast.LShift: int.__lshift__,
    ast.RShift: int.__rshift__,
}


def _eval_int_expression(expression: str) -> int:
    """Evaluate a fully-substituted C integer expression."""

    def visit(node: ast.AST) -> int:
        match node:
            case ast.Expression(body=body):
                return visit(body)
            case ast.Constant(value=int() as value):
                return value
            case ast.UnaryOp(op=ast.USub(), operand=operand):
                return -visit(operand)
            case ast.BinOp(left=left, op=op, right=right) if type(op) in _ARITHMETIC:
                return _ARITHMETIC[type(op)](visit(left), visit(right))  # type: ignore[operator]
        raise ContractError(f"unsupported token in derived expression: {ast.dump(node)}")

    # C integer division truncates; the macros only ever divide exact multiples.
    normalised = " ".join(expression.replace("/", "//").split())
    return visit(ast.parse(normalised, mode="eval"))


def _parse_frame_max(source: str, prefix: str, macros: dict[str, int]) -> int:
    """Evaluate the KEYPOINT_LIVE_DATA_FRAME_MAX macro rather than restating it."""
    match = re.search(r"#define\s+KEYPOINT_LIVE_DATA_FRAME_MAX((?:[^\n\\]*\\\s*\n)*[^\n]*)", source)
    if match is None:
        raise ContractError("KEYPOINT_LIVE_DATA_FRAME_MAX not found")

    expression = re.sub(r"\\\s*\n", " ", match.group(1))
    # sizeof("KP3|") counts the NUL terminator the C macro then subtracts.
    expression = expression.replace("sizeof(KEYPOINT_LIVE_DATA_PREFIX)", str(len(prefix) + 1))
    expression = re.sub(
        r"KEYPOINT_LIVE_DATA_(\w+)",
        lambda m: str(_macro_int(macros, m.group(1))),
        expression,
    )
    return _eval_int_expression(expression)


def _parse_enum_names(source: str, enum: str, member_prefix: str) -> tuple[str, ...]:
    match = re.search(rf"enum\s+{enum}\s*\{{(.*?)\}};", source, re.S)
    if match is None:
        raise ContractError(f"enum {enum} not found in {CONTRACT_HEADER}")
    names = tuple(dict.fromkeys(re.findall(rf"{member_prefix}([A-Z0-9_]+)", match.group(1))))
    if not names:
        raise ContractError(f"enum {enum} has no members")
    return names


def _parse_acceptance_chain(function: str) -> tuple[str, ...]:
    """The strcmp() spellings one `*_from_field()` helper accepts, in order."""
    for source in _widget_c_sources():
        match = re.search(rf"static int {function}\((.*?)\n}}", source, re.S)
        if match is not None:
            return tuple(re.findall(r'strcmp\(field,\s*"([^"]*)"\)\s*==\s*0', match.group(1)))
    raise ContractError(f"{function}() not found under {WIDGETS_DIR}")


_MACRO_NAMES: Final = (
    "GENERATION_FIELD_MAX",
    "ICON_MAX",
    "LED_HINT_FIELD_MAX",
    "TEXT_LINE_COUNT",
    "LINE_MAX",
    "PAGE_MAX",
    "PAGE_FIELD_MAX",
    "STALE_MS",
)


def derive_from_firmware() -> dict[str, object]:
    """Read the whole contract out of the firmware C sources."""
    header = _header_source()
    macros = _macro_ints(header)
    prefix = _parse_prefix(header)
    return {
        "prefix": prefix,
        **{name.lower(): _macro_int(macros, name) for name in _MACRO_NAMES},
        "frame_max": _parse_frame_max(header, prefix, macros),
        "icon_names": list(_parse_enum_names(header, "keypoint_live_data_icon", "KEYPOINT_LIVE_DATA_ICON_")),
        "led_hint_names": list(
            _parse_enum_names(header, "keypoint_live_data_led_hint", "KEYPOINT_LIVE_DATA_LED_HINT_")
        ),
        "icon_acceptance_chain": list(_parse_acceptance_chain("icon_from_field")),
        "led_acceptance_chain": list(_parse_acceptance_chain("led_hint_from_field")),
    }


def _load_contract() -> dict[str, object]:
    """Derive from the firmware when it is present, else from the frozen copy.

    kp3 is vendored into producers that have no firmware checkout (see the
    rcink reference producer). `--freeze` writes the snapshot beside this
    module; a test in this repo regenerates it and fails on any difference, so
    the frozen copy cannot drift away from the C it was taken from.
    """
    if CONTRACT_HEADER.is_file():
        return derive_from_firmware()
    if CONTRACT_SNAPSHOT.is_file():
        return json.loads(CONTRACT_SNAPSHOT.read_text())
    raise ContractError(f"no contract source: neither {CONTRACT_HEADER} nor {CONTRACT_SNAPSHOT} exists")


_CONTRACT: Final = _load_contract()

PREFIX: Final[str] = str(_CONTRACT["prefix"])
GENERATION_FIELD_MAX: Final[int] = int(_CONTRACT["generation_field_max"])  # type: ignore[arg-type]
ICON_MAX: Final[int] = int(_CONTRACT["icon_max"])  # type: ignore[arg-type]
LED_HINT_FIELD_MAX: Final[int] = int(_CONTRACT["led_hint_field_max"])  # type: ignore[arg-type]
TEXT_LINE_COUNT: Final[int] = int(_CONTRACT["text_line_count"])  # type: ignore[arg-type]
LINE_MAX: Final[int] = int(_CONTRACT["line_max"])  # type: ignore[arg-type]
PAGE_MAX: Final[int] = int(_CONTRACT["page_max"])  # type: ignore[arg-type]
PAGE_FIELD_MAX: Final[int] = int(_CONTRACT["page_field_max"])  # type: ignore[arg-type]
STALE_MS: Final[int] = int(_CONTRACT["stale_ms"])  # type: ignore[arg-type]
FRAME_MAX: Final[int] = int(_CONTRACT["frame_max"])  # type: ignore[arg-type]

ICON_NAMES: Final[tuple[str, ...]] = tuple(_CONTRACT["icon_names"])  # type: ignore[arg-type]
LED_HINT_NAMES: Final[tuple[str, ...]] = tuple(_CONTRACT["led_hint_names"])  # type: ignore[arg-type]
#: Wire spelling -> enum ordinal, as `led_hint_from_field()` maps them.
LED_HINTS: Final[dict[str, int]] = dict(
    zip(_CONTRACT["led_acceptance_chain"], range(len(LED_HINT_NAMES)), strict=True)  # type: ignore[arg-type]
)
LED_CODES: Final[tuple[int, ...]] = tuple(LED_HINTS.values())

#: The number of decimal fields between the prefix and the text lines.
_HEADER_FIELD_COUNT: Final = 5
FIELD_COUNT: Final[int] = _HEADER_FIELD_COUNT + TEXT_LINE_COUNT

_GENERATION_DIGITS: Final = "0123456789ABCDEF"
_GENERATION_MAX: Final = 16**GENERATION_FIELD_MAX - 1


def icon_names_from_acceptance_chain() -> tuple[str, ...]:
    """Icon spellings `icon_from_field()` accepts, from the C strcmp chain."""
    return tuple(_CONTRACT["icon_acceptance_chain"])  # type: ignore[arg-type]


def _validate_contract() -> None:
    chain = icon_names_from_acceptance_chain()
    if chain != ICON_NAMES:
        raise ContractError(f"icon enum and icon_from_field() disagree: enum={ICON_NAMES} chain={chain}")
    if tuple(LED_HINTS) != tuple(str(code) for code in range(len(LED_HINT_NAMES))):
        raise ContractError(f"led_hint_from_field() does not spell the enum ordinals: {tuple(LED_HINTS)}")
    if PAGE_MAX >= 10**PAGE_FIELD_MAX:
        raise ContractError(f"PAGE_MAX={PAGE_MAX} does not fit in PAGE_FIELD_MAX={PAGE_FIELD_MAX} digit(s)")


_validate_contract()


# ---------------------------------------------------------------------------
# Parser -- rejects exactly what keypoint_live_data_parse() rejects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Frame:
    """One accepted KP3 frame, parsed into the fields the firmware keeps."""

    generation: int
    index: int
    total: int
    icon: str
    led_hint: int
    lines: tuple[str, ...]


def _field_width(field: int) -> int:
    match field:
        case 0:
            return GENERATION_FIELD_MAX
        case 1 | 2:
            return PAGE_FIELD_MAX
        case 3:
            return ICON_MAX
        case 4:
            return LED_HINT_FIELD_MAX
        case _:
            return LINE_MAX


def parse(frame: str | bytes) -> Frame:
    """Parse a KP3 frame, raising FrameError wherever the firmware would
    answer the GATT write with BT_ATT_ERR_VALUE_NOT_ALLOWED.

    Mirrors keypoint_live_data_parse()'s single pass over the payload: field
    widths are enforced per character, so an over-long field is rejected even
    when the total frame still fits.
    """
    data = frame.encode("latin-1") if isinstance(frame, str) else bytes(frame)
    if len(data) > FRAME_MAX:
        raise FrameError(f"frame is {len(data)} bytes, max {FRAME_MAX}")

    prefix = PREFIX.encode()
    if not data.startswith(prefix):
        raise FrameError(f"frame must start with {PREFIX!r}")

    fields: list[bytearray] = [bytearray()]
    for offset, byte in enumerate(data[len(prefix) :], start=len(prefix)):
        field = len(fields) - 1
        column = len(fields[field])

        if byte == ord("|"):
            if field >= FIELD_COUNT - 1:
                raise FrameError(f"too many fields (separator at byte {offset})")
            if field == 0 and column != GENERATION_FIELD_MAX:
                raise FrameError("GEN must be exactly two uppercase hex digits")
            if field in (1, 2) and column == 0:
                raise FrameError("IDX and TOTAL must not be empty")
            if field == 4 and column != LED_HINT_FIELD_MAX:
                raise FrameError("LED hint must be exactly one digit")
            fields.append(bytearray())
            continue

        if column >= _field_width(field):
            raise FrameError(f"field {field} longer than {_field_width(field)} chars")
        if field == 0 and chr(byte) not in _GENERATION_DIGITS:
            raise FrameError("GEN accepts uppercase hex digits only")
        if field in (1, 2) and not ord("0") <= byte <= ord("9"):
            raise FrameError("IDX and TOTAL accept decimal digits only")
        if field >= 3 and not 0x20 <= byte <= 0x7E:
            raise FrameError(f"non-printable byte {byte:#04x} in field {field}")
        fields[field].append(byte)

    if len(fields) != FIELD_COUNT:
        raise FrameError(f"expected {FIELD_COUNT} fields, got {len(fields)}")

    index = int(fields[1])
    total = int(fields[2])
    if not 1 <= total <= PAGE_MAX:
        raise FrameError(f"TOTAL={total} outside 1..{PAGE_MAX}")
    if index >= total:
        raise FrameError(f"IDX={index} not below TOTAL={total}")

    icon = fields[3].decode("ascii")
    if icon not in ICON_NAMES:
        raise FrameError(f"unknown icon {icon!r}")

    led_field = fields[4].decode("ascii")
    if led_field not in LED_HINTS:
        raise FrameError(f"unknown LED hint {led_field!r}")

    return Frame(
        generation=int(fields[0], 16),
        index=index,
        total=total,
        icon=icon,
        led_hint=LED_HINTS[led_field],
        lines=tuple(bytes(line).decode("ascii") for line in fields[_HEADER_FIELD_COUNT:]),
    )


# ---------------------------------------------------------------------------
# Builders -- the only way anything in this repo puts a frame on the wire
# ---------------------------------------------------------------------------


def kv(label: str, value: str) -> str:
    """Pad LABEL + value to a full-width line.

    The glass font is monospace, so full-width lines turn the card into a
    LINE_MAX x TEXT_LINE_COUNT character grid: labels form a left column
    flush against the frame, values a right column.
    """
    if len(label) + len(value) >= LINE_MAX:
        raise FrameError(f"kv({label!r}, {value!r}) does not fit {LINE_MAX} chars with a gap")
    return f"{label}{' ' * (LINE_MAX - len(label) - len(value))}{value}"


def title(text: str) -> str:
    """Left-anchor a card title across the full line width."""
    if len(text) > LINE_MAX:
        raise FrameError(f"title {text!r} longer than {LINE_MAX} chars")
    return text.ljust(LINE_MAX)


def bar(pct: int) -> str:
    """A [NNN] progress row."""
    if not 0 <= pct <= 999:
        raise FrameError(f"bar percentage {pct} outside 0..999")
    return f"[{pct:03d}]"


def build_frame(
    icon: str,
    *lines: str,
    generation: int = 0,
    index: int = 0,
    total: int = 1,
    led_hint: int = 0,
) -> str:
    """Build one KP3 frame; missing lines are sent empty.

    The result is round-tripped through `parse()`, so a builder can never emit
    something the firmware would reject.
    """
    if len(lines) > TEXT_LINE_COUNT:
        raise FrameError(f"at most {TEXT_LINE_COUNT} lines, got {len(lines)}")
    if not 0 <= generation <= _GENERATION_MAX:
        raise FrameError(f"generation {generation} outside 0..{_GENERATION_MAX}")

    padded = lines + ("",) * (TEXT_LINE_COUNT - len(lines))
    frame = f"{PREFIX}{generation:0{GENERATION_FIELD_MAX}X}|{index}|{total}|{icon}|{led_hint}|" + "|".join(padded)
    parse(frame)
    return frame


def usage_card(
    icon: str,
    heading: str,
    five_hour_window: str,
    five_hour_pct: int,
    seven_day_window: str,
    seven_day_pct: int,
    *,
    led_hint: int,
    generation: int = 0,
    index: int = 0,
    total: int = 1,
) -> str:
    """The rate-limit card shape the reference producer emits.

    Title, then a countdown-to-reset row and a utilisation bar per window
    (5H then 7D), with the last line empty. Keeping the shape here is what
    lets the preview's demo deck byte-match the producer's real output.
    """
    return build_frame(
        icon,
        title(heading),
        kv("5H", five_hour_window),
        bar(five_hour_pct),
        kv("7D", seven_day_window),
        bar(seven_day_pct),
        generation=generation,
        index=index,
        total=total,
        led_hint=led_hint,
    )


def claude_card(*args, **kwargs) -> str:
    """`usage_card()` for the CLAUDE deck page."""
    return usage_card("CLAUDE", "CLAUDE", *args, **kwargs)


def codex_card(*args, **kwargs) -> str:
    """`usage_card()` for the CODEX deck page."""
    return usage_card("CODEX", "CODEX", *args, **kwargs)


def freeze() -> str:
    """Serialise the firmware-derived contract for vendored copies."""
    return json.dumps(derive_from_firmware(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["--freeze"]:
        CONTRACT_SNAPSHOT.write_text(freeze())
        print(f"wrote {CONTRACT_SNAPSHOT}")
    else:
        print(freeze(), end="")
