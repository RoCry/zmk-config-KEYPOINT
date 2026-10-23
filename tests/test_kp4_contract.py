"""Value-based coverage of the KP4 contract module.

These tests assert *values* the firmware enforces, not the spelling of the C
source: every expected number comes back out of kp4, which derives it from
`live_data.h` at import. A contract change therefore moves both sides at once
or fails loudly here.
"""

import importlib.util
import shutil
import sys
from pathlib import Path

import kp4
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
    return kp4.build_frame(str(icon), kp4.title("HELLO"), **fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def test_contract_values_match_the_firmware_header() -> None:
    """The numbers the README and every producer must agree on."""
    assert kp4.PREFIX == "KP4|"
    assert kp4.TEXT_LINE_COUNT == 6
    assert kp4.LINE_MAX == 9
    assert kp4.PAGE_MAX == 8
    assert kp4.FRAME_MAX == 88
    assert kp4.GENERATION_FIELD_MAX == 2
    assert kp4.STALE_MS == 6 * 60 * 1000


def test_icon_enum_matches_the_acceptance_chain() -> None:
    """Nothing else checks the strcmp chain against the enum it feeds."""
    assert kp4.icon_names_from_acceptance_chain() == kp4.ICON_NAMES
    assert "CLAUDE" in kp4.ICON_NAMES and "CODEX" in kp4.ICON_NAMES


def test_led_codes_are_derived_from_the_firmware_not_declared() -> None:
    assert tuple(range(len(kp4.LED_HINT_NAMES))) == kp4.LED_CODES
    assert kp4.LED_HINT_NAMES[0] == "NONE"
    assert kp4.LED_HINT_NAMES[-1] == "ERROR"


def test_page_field_width_can_hold_the_page_max() -> None:
    assert kp4.PAGE_MAX < 10**kp4.PAGE_FIELD_MAX


def test_the_frozen_contract_matches_the_firmware_it_was_taken_from() -> None:
    """Vendored copies read the snapshot; it must not drift from the C."""
    assert kp4.CONTRACT_SNAPSHOT.read_text() == kp4.freeze(), (
        f"regenerate it: uv run --no-project python {kp4.__file__} --freeze"
    )


def test_kp4_works_vendored_without_a_firmware_checkout(tmp_path: Path) -> None:
    """The rcink producer ships kp4 with no firmware tree beside it."""
    for name in ("kp4.py", "kp4_contract.json"):
        shutil.copy(Path(kp4.__file__).with_name(name), tmp_path / name)

    spec = importlib.util.spec_from_file_location("kp4_vendored", tmp_path / "kp4.py")
    assert spec is not None and spec.loader is not None
    vendored = importlib.util.module_from_spec(spec)
    sys.modules["kp4_vendored"] = vendored  # slotted @dataclass needs this registered
    spec.loader.exec_module(vendored)

    assert not vendored.CONTRACT_HEADER.is_file(), "the copy must not see the firmware"
    assert vendored.LINE_MAX == kp4.LINE_MAX
    assert vendored.FRAME_MAX == kp4.FRAME_MAX
    assert vendored.ICON_NAMES == kp4.ICON_NAMES
    assert vendored.claude_card("1h23m", 22, "4d", 41, led_hint=0) == kp4.claude_card("1h23m", 22, "4d", 41, led_hint=0)


# ---------------------------------------------------------------------------
# Parser: acceptance
# ---------------------------------------------------------------------------


def test_parse_returns_the_fields_the_firmware_keeps() -> None:
    frame = kp4.build_frame("CLAUDE", "L1", "L2", "L3", "L4", "L5", "L6", generation=0x1F, index=2, total=3, led_hint=4)
    parsed = kp4.parse(frame)
    assert parsed.generation == 0x1F
    assert (parsed.index, parsed.total) == (2, 3)
    assert parsed.icon == "CLAUDE"
    assert parsed.led_hint == 4
    assert parsed.lines == ("L1", "L2", "L3", "L4", "L5", "L6")


def test_parse_accepts_bytes_and_str_alike() -> None:
    frame = valid_frame()
    assert kp4.parse(frame) == kp4.parse(frame.encode())


@pytest.mark.parametrize("icon", kp4.ICON_NAMES)
def test_every_enum_icon_is_accepted(icon: str) -> None:
    assert kp4.parse(valid_frame(icon=icon)).icon == icon


@pytest.mark.parametrize("led", kp4.LED_CODES)
def test_every_led_code_is_accepted(led: int) -> None:
    assert kp4.parse(valid_frame(led_hint=led)).led_hint == led


def test_full_page_range_is_accepted() -> None:
    for index in range(kp4.PAGE_MAX):
        assert kp4.parse(valid_frame(index=index, total=kp4.PAGE_MAX)).index == index


def test_empty_lines_are_accepted() -> None:
    assert kp4.parse(kp4.build_frame("NONE")).lines == ("",) * kp4.TEXT_LINE_COUNT


# ---------------------------------------------------------------------------
# Parser: the firmware's rejection set
# ---------------------------------------------------------------------------


def _grammar_frame(
    gen: str, index: str, total: str, icon: str, led: str, lines: list[str], roles: str = "000000"
) -> str:
    """Assemble a frame field-by-field, bypassing the builders' validation."""
    return kp4.PREFIX + "|".join([gen, index, total, icon, led, roles, *lines])


LINES = ["A"] * kp4.TEXT_LINE_COUNT


@pytest.mark.parametrize(
    ("reason", "frame"),
    [
        ("bad prefix", "KP2|" + valid_frame().removeprefix(kp4.PREFIX)),
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
            _grammar_frame("A0", "0", "1", "SUN", "0", ["B" * (kp4.LINE_MAX + 1), *LINES[1:]]),
        ),
        (
            "over-long icon",
            _grammar_frame("A0", "0", "1", "S" * (kp4.ICON_MAX + 1), "0", LINES),
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
    with pytest.raises(kp4.FrameError):
        kp4.parse(frame)
    assert reason  # the id is the point of the case


def test_oversize_frames_are_rejected() -> None:
    oversize = _grammar_frame("A0", "0", "1", "S" * kp4.ICON_MAX, "0", ["Z" * kp4.LINE_MAX] * kp4.TEXT_LINE_COUNT)
    assert len(oversize) == kp4.FRAME_MAX
    with pytest.raises(kp4.FrameError):
        kp4.parse(oversize + "!")


def test_a_pipe_in_a_line_cannot_smuggle_a_field() -> None:
    with pytest.raises(kp4.FrameError):
        kp4.parse(_grammar_frame("A0", "0", "1", "SUN", "0", ["A|B", *LINES[1:]]))


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def test_maximal_frame_measures_exactly_the_derived_frame_max() -> None:
    """The FRAME_MAX macro's arithmetic, checked against a real frame.

    No accepted icon spelling is ICON_MAX long, so the widest *valid* frame is
    shorter than the grammar's ceiling by exactly that slack.
    """
    widest = _grammar_frame(
        "F" * kp4.GENERATION_FIELD_MAX,
        "7",
        "8",
        "S" * kp4.ICON_MAX,
        "4",
        ["Z" * kp4.LINE_MAX] * kp4.TEXT_LINE_COUNT,
    )
    assert len(widest) == kp4.FRAME_MAX

    longest_icon = max(kp4.ICON_NAMES, key=len)
    widest_valid = kp4.build_frame(
        longest_icon,
        *["Z" * kp4.LINE_MAX] * kp4.TEXT_LINE_COUNT,
        generation=0xFF,
        index=kp4.PAGE_MAX - 1,
        total=kp4.PAGE_MAX,
        led_hint=kp4.LED_CODES[-1],
    )
    assert len(widest_valid) == kp4.FRAME_MAX - (kp4.ICON_MAX - len(longest_icon))


def test_kv_and_title_pad_to_the_derived_line_width() -> None:
    kv_line = kp4.kv("5H", "1h23m")
    assert len(kv_line) == kp4.LINE_MAX
    assert kv_line.startswith("5H") and kv_line.endswith("1h23m")

    assert len(kp4.title("CLAUDE")) == kp4.LINE_MAX
    assert kp4.title("CLAUDE").startswith("CLAUDE")


def test_bar_is_a_fixed_width_percentage_row() -> None:
    assert kp4.bar(7) == "[007]"
    assert kp4.bar(100) == "[100]"


def test_scoped_limit_row_is_short_and_unpadded() -> None:
    """Unlike kv(), the scoped-limit row does not claim the whole line: the
    glass right-aligns it, so it reads as one token under the 7D bar."""
    assert kp4.scoped_limit_row("FB", 41) == "FB 41%"
    assert kp4.scoped_limit_row("FB", 100) == "FB 100%"
    # The label may grow until the percentage runs out of line.
    assert len(kp4.scoped_limit_row("ABCD", 100)) == kp4.LINE_MAX


def test_builders_refuse_what_does_not_fit() -> None:
    with pytest.raises(kp4.FrameError):
        kp4.kv("LABEL", "VALUE1234")
    with pytest.raises(kp4.FrameError):
        kp4.title("X" * (kp4.LINE_MAX + 1))
    with pytest.raises(kp4.FrameError):
        kp4.scoped_limit_row("FABLE", 100)  # "FABLE 100%" is one over the line
    with pytest.raises(kp4.FrameError):
        kp4.build_frame("SUN", *["x"] * (kp4.TEXT_LINE_COUNT + 1))
    with pytest.raises(kp4.FrameError):
        kp4.build_frame("SUN", generation=0x100)


@pytest.mark.parametrize("field", ["generation", "index", "total", "led_hint"])
def test_builders_reject_bools_masquerading_as_ints(field: str) -> None:
    """bool subclasses int, so True would encode as 1 and ship a valid frame
    saying something the caller never meant -- led_hint ACTIVE, a one-page
    deck. The wire cannot express the mistake, so the builder refuses it."""
    with pytest.raises(kp4.FrameError, match=field):
        kp4.build_frame("SUN", **{field: True})


def test_build_frame_rejects_frames_the_firmware_would_reject() -> None:
    """Builders validate their own output, so a bad deck fails at the source."""
    with pytest.raises(kp4.FrameError):
        kp4.build_frame("SUN", total=kp4.PAGE_MAX + 1)
    with pytest.raises(kp4.FrameError):
        kp4.build_frame("SUN", index=1, total=1)
    with pytest.raises(kp4.FrameError):
        kp4.build_frame("MOON")
    with pytest.raises(kp4.FrameError):
        kp4.build_frame("SUN", "X" * (kp4.LINE_MAX + 1))


def test_usage_cards_fill_the_full_line_width() -> None:
    frame = kp4.claude_card("1h23m", 22, "4d", 41, led_hint=0, generation=0xA0)
    parsed = kp4.parse(frame)
    assert parsed.icon == "CLAUDE"
    assert parsed.lines[0] == "CLAUDE".ljust(kp4.LINE_MAX)
    assert parsed.lines[1] == kp4.kv("5H", "1h23m")
    assert parsed.lines[2] == kp4.bar(22)
    assert parsed.lines[5] == ""

    codex = kp4.parse(kp4.codex_card("12m", 78, "2d", 54, led_hint=2))
    assert codex.icon == "CODEX"
    assert codex.led_hint == 2


def test_usage_cards_carry_a_scoped_limit_on_the_last_line() -> None:
    """The producer's usual claude card: L6 is the highest model-scoped limit."""
    scoped = kp4.parse(kp4.claude_card("1h23m", 22, "4d", 41, scoped_limit=("FB", 68), led_hint=0))
    plain = kp4.parse(kp4.claude_card("1h23m", 22, "4d", 41, led_hint=0))

    assert scoped.lines[:5] == plain.lines[:5]
    assert scoped.lines[5] == kp4.scoped_limit_row("FB", 68)
    assert plain.lines[5] == ""


def test_a_scoped_limit_pair_the_caller_swapped_is_refused() -> None:
    """usage_card() takes the pair as one argument, so the wire can express the
    swap: "68 FB%" fits the line and the firmware would accept it."""
    with pytest.raises(kp4.FrameError):
        kp4.scoped_limit_row(68, "FB")  # type: ignore[arg-type]
    with pytest.raises(kp4.FrameError):
        kp4.claude_card("1h23m", 22, "4d", 41, scoped_limit=(68, "FB"), led_hint=0)  # type: ignore[arg-type]
