"""Value-based coverage of the KP3 contract module.

These tests assert *values* the firmware enforces, not the spelling of the C
source: every expected number comes back out of kp3, which derives it from
`live_data.h` at import. A contract change therefore moves both sides at once
or fails loudly here.
"""

import importlib.util
import shutil
import sys
from pathlib import Path

import kp3
import pytest


def valid_frame(**overrides: object) -> str:
    fields: dict[str, object] = {
        "icon": "SUN",
        "generation": 0xA0,
        "index": 0,
        "total": 1,
        "led_hint": 0,
    }
    fields.update(overrides)
    icon = fields.pop("icon")
    return kp3.build_frame(str(icon), kp3.title("HELLO"), **fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def test_contract_values_match_the_firmware_header() -> None:
    """The numbers the README and every producer must agree on."""
    assert kp3.PREFIX == "KP3|"
    assert kp3.TEXT_LINE_COUNT == 6
    assert kp3.LINE_MAX == 9
    assert kp3.PAGE_MAX == 8
    assert kp3.FRAME_MAX == 81
    assert kp3.GENERATION_FIELD_MAX == 2
    assert kp3.STALE_MS == 6 * 60 * 1000


def test_icon_enum_matches_the_acceptance_chain() -> None:
    """Nothing else checks the strcmp chain against the enum it feeds."""
    assert kp3.icon_names_from_acceptance_chain() == kp3.ICON_NAMES
    assert "CLAUDE" in kp3.ICON_NAMES and "CODEX" in kp3.ICON_NAMES


def test_led_codes_are_derived_from_the_firmware_not_declared() -> None:
    assert tuple(range(len(kp3.LED_HINT_NAMES))) == kp3.LED_CODES
    assert kp3.LED_HINT_NAMES[0] == "NONE"
    assert kp3.LED_HINT_NAMES[-1] == "ERROR"


def test_page_field_width_can_hold_the_page_max() -> None:
    assert kp3.PAGE_MAX < 10**kp3.PAGE_FIELD_MAX


def test_the_frozen_contract_matches_the_firmware_it_was_taken_from() -> None:
    """Vendored copies read the snapshot; it must not drift from the C."""
    assert kp3.CONTRACT_SNAPSHOT.read_text() == kp3.freeze(), (
        f"regenerate it: uv run --no-project python {kp3.__file__} --freeze"
    )


def test_kp3_works_vendored_without_a_firmware_checkout(tmp_path: Path) -> None:
    """The rcink producer ships kp3 with no firmware tree beside it."""
    for name in ("kp3.py", "kp3_contract.json"):
        shutil.copy(Path(kp3.__file__).with_name(name), tmp_path / name)

    spec = importlib.util.spec_from_file_location("kp3_vendored", tmp_path / "kp3.py")
    assert spec is not None and spec.loader is not None
    vendored = importlib.util.module_from_spec(spec)
    sys.modules["kp3_vendored"] = vendored  # slotted @dataclass needs this registered
    spec.loader.exec_module(vendored)

    assert not vendored.CONTRACT_HEADER.is_file(), "the copy must not see the firmware"
    assert vendored.LINE_MAX == kp3.LINE_MAX
    assert vendored.FRAME_MAX == kp3.FRAME_MAX
    assert vendored.ICON_NAMES == kp3.ICON_NAMES
    assert vendored.claude_card("1h23m", 22, "4d", 41, led_hint=0) == kp3.claude_card("1h23m", 22, "4d", 41, led_hint=0)


# ---------------------------------------------------------------------------
# Parser: acceptance
# ---------------------------------------------------------------------------


def test_parse_returns_the_fields_the_firmware_keeps() -> None:
    frame = kp3.build_frame("CLAUDE", "L1", "L2", "L3", "L4", "L5", "L6", generation=0x1F, index=2, total=3, led_hint=4)
    parsed = kp3.parse(frame)
    assert parsed.generation == 0x1F
    assert (parsed.index, parsed.total) == (2, 3)
    assert parsed.icon == "CLAUDE"
    assert parsed.led_hint == 4
    assert parsed.lines == ("L1", "L2", "L3", "L4", "L5", "L6")


def test_parse_accepts_bytes_and_str_alike() -> None:
    frame = valid_frame()
    assert kp3.parse(frame) == kp3.parse(frame.encode())


@pytest.mark.parametrize("icon", kp3.ICON_NAMES)
def test_every_enum_icon_is_accepted(icon: str) -> None:
    assert kp3.parse(valid_frame(icon=icon)).icon == icon


@pytest.mark.parametrize("led", kp3.LED_CODES)
def test_every_led_code_is_accepted(led: int) -> None:
    assert kp3.parse(valid_frame(led_hint=led)).led_hint == led


def test_full_page_range_is_accepted() -> None:
    for index in range(kp3.PAGE_MAX):
        assert kp3.parse(valid_frame(index=index, total=kp3.PAGE_MAX)).index == index


def test_empty_lines_are_accepted() -> None:
    assert kp3.parse(kp3.build_frame("NONE")).lines == ("",) * kp3.TEXT_LINE_COUNT


# ---------------------------------------------------------------------------
# Parser: the firmware's rejection set
# ---------------------------------------------------------------------------


def _grammar_frame(gen: str, index: str, total: str, icon: str, led: str, lines: list[str]) -> str:
    """Assemble a frame field-by-field, bypassing the builders' validation."""
    return kp3.PREFIX + "|".join([gen, index, total, icon, led, *lines])


LINES = ["A"] * kp3.TEXT_LINE_COUNT


@pytest.mark.parametrize(
    ("reason", "frame"),
    [
        ("bad prefix", "KP2|" + valid_frame().removeprefix(kp3.PREFIX)),
        ("no prefix", "hello"),
        ("empty", ""),
        ("lowercase generation", _grammar_frame("a0", "0", "1", "SUN", "0", LINES)),
        ("short generation", _grammar_frame("A", "0", "1", "SUN", "0", LINES)),
        ("long generation", _grammar_frame("A0F", "0", "1", "SUN", "0", LINES)),
        ("non-hex generation", _grammar_frame("GG", "0", "1", "SUN", "0", LINES)),
        ("empty generation", _grammar_frame("", "0", "1", "SUN", "0", LINES)),
        ("total zero", _grammar_frame("A0", "0", "0", "SUN", "0", LINES)),
        ("total above page max", _grammar_frame("A0", "0", "9", "SUN", "0", LINES)),
        ("index equals total", _grammar_frame("A0", "1", "1", "SUN", "0", LINES)),
        ("index above total", _grammar_frame("A0", "3", "2", "SUN", "0", LINES)),
        ("empty index", _grammar_frame("A0", "", "1", "SUN", "0", LINES)),
        ("empty total", _grammar_frame("A0", "0", "", "SUN", "0", LINES)),
        ("non-decimal index", _grammar_frame("A0", "x", "1", "SUN", "0", LINES)),
        ("unknown icon", _grammar_frame("A0", "0", "1", "MOON", "0", LINES)),
        ("empty icon", _grammar_frame("A0", "0", "1", "", "0", LINES)),
        ("lowercase icon", _grammar_frame("A0", "0", "1", "sun", "0", LINES)),
        ("led hint out of range", _grammar_frame("A0", "0", "1", "SUN", "5", LINES)),
        ("empty led hint", _grammar_frame("A0", "0", "1", "SUN", "", LINES)),
        ("two-digit led hint", _grammar_frame("A0", "0", "1", "SUN", "01", LINES)),
        ("missing line field", _grammar_frame("A0", "0", "1", "SUN", "0", LINES[:-1])),
        ("extra line field", _grammar_frame("A0", "0", "1", "SUN", "0", [*LINES, "X"])),
        ("trailing separator", _grammar_frame("A0", "0", "1", "SUN", "0", LINES) + "|"),
        (
            "over-long line",
            _grammar_frame("A0", "0", "1", "SUN", "0", ["B" * (kp3.LINE_MAX + 1), *LINES[1:]]),
        ),
        (
            "over-long icon",
            _grammar_frame("A0", "0", "1", "S" * (kp3.ICON_MAX + 1), "0", LINES),
        ),
        (
            "non-printable byte",
            _grammar_frame("A0", "0", "1", "SUN", "0", ["\x01", *LINES[1:]]),
        ),
        (
            "delete byte",
            _grammar_frame("A0", "0", "1", "SUN", "0", ["\x7f", *LINES[1:]]),
        ),
    ],
)
def test_parser_rejects_what_the_firmware_rejects(reason: str, frame: str) -> None:
    with pytest.raises(kp3.FrameError):
        kp3.parse(frame)
    assert reason  # the id is the point of the case


def test_oversize_frames_are_rejected() -> None:
    oversize = _grammar_frame("A0", "0", "1", "S" * kp3.ICON_MAX, "0", ["Z" * kp3.LINE_MAX] * kp3.TEXT_LINE_COUNT)
    assert len(oversize) == kp3.FRAME_MAX
    with pytest.raises(kp3.FrameError):
        kp3.parse(oversize + "!")


def test_a_pipe_in_a_line_cannot_smuggle_a_field() -> None:
    with pytest.raises(kp3.FrameError):
        kp3.parse(_grammar_frame("A0", "0", "1", "SUN", "0", ["A|B", *LINES[1:]]))


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def test_maximal_frame_measures_exactly_the_derived_frame_max() -> None:
    """The FRAME_MAX macro's arithmetic, checked against a real frame.

    No accepted icon spelling is ICON_MAX long, so the widest *valid* frame is
    shorter than the grammar's ceiling by exactly that slack.
    """
    widest = _grammar_frame(
        "F" * kp3.GENERATION_FIELD_MAX,
        "7",
        "8",
        "S" * kp3.ICON_MAX,
        "4",
        ["Z" * kp3.LINE_MAX] * kp3.TEXT_LINE_COUNT,
    )
    assert len(widest) == kp3.FRAME_MAX

    longest_icon = max(kp3.ICON_NAMES, key=len)
    widest_valid = kp3.build_frame(
        longest_icon,
        *["Z" * kp3.LINE_MAX] * kp3.TEXT_LINE_COUNT,
        generation=0xFF,
        index=kp3.PAGE_MAX - 1,
        total=kp3.PAGE_MAX,
        led_hint=kp3.LED_CODES[-1],
    )
    assert len(widest_valid) == kp3.FRAME_MAX - (kp3.ICON_MAX - len(longest_icon))


def test_kv_and_title_pad_to_the_derived_line_width() -> None:
    kv_line = kp3.kv("5H", "1h23m")
    assert len(kv_line) == kp3.LINE_MAX
    assert kv_line.startswith("5H") and kv_line.endswith("1h23m")

    assert len(kp3.title("CLAUDE")) == kp3.LINE_MAX
    assert kp3.title("CLAUDE").startswith("CLAUDE")


def test_bar_is_a_fixed_width_percentage_row() -> None:
    assert kp3.bar(7) == "[007]"
    assert kp3.bar(100) == "[100]"


def test_builders_refuse_what_does_not_fit() -> None:
    with pytest.raises(kp3.FrameError):
        kp3.kv("LABEL", "VALUE1234")
    with pytest.raises(kp3.FrameError):
        kp3.title("X" * (kp3.LINE_MAX + 1))
    with pytest.raises(kp3.FrameError):
        kp3.build_frame("SUN", *["x"] * (kp3.TEXT_LINE_COUNT + 1))
    with pytest.raises(kp3.FrameError):
        kp3.build_frame("SUN", generation=0x100)


def test_build_frame_rejects_frames_the_firmware_would_reject() -> None:
    """Builders validate their own output, so a bad deck fails at the source."""
    with pytest.raises(kp3.FrameError):
        kp3.build_frame("SUN", total=kp3.PAGE_MAX + 1)
    with pytest.raises(kp3.FrameError):
        kp3.build_frame("SUN", index=1, total=1)
    with pytest.raises(kp3.FrameError):
        kp3.build_frame("MOON")
    with pytest.raises(kp3.FrameError):
        kp3.build_frame("SUN", "X" * (kp3.LINE_MAX + 1))


def test_usage_cards_fill_the_full_line_width() -> None:
    frame = kp3.claude_card("1h23m", 22, "4d", 41, led_hint=0, generation=0xA0)
    parsed = kp3.parse(frame)
    assert parsed.icon == "CLAUDE"
    assert parsed.lines[0] == "CLAUDE".ljust(kp3.LINE_MAX)
    assert parsed.lines[1] == kp3.kv("5H", "1h23m")
    assert parsed.lines[2] == kp3.bar(22)
    assert parsed.lines[5] == ""

    codex = kp3.parse(kp3.codex_card("12m", 78, "2d", 54, led_hint=2))
    assert codex.icon == "CODEX"
    assert codex.led_hint == 2
