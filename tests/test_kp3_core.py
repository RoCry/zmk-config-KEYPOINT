"""Executable tests for the real firmware KP3 core, compiled and driven here.

`live_data_core.c` is Zephyr-free by construction, so the host cc can build it
and ctypes can drive it. These are the first tests that run the deck machine
rather than reading its source: staging, commit-when-complete, generation
replacement, page wrap, staleness.

The differential test is the point of the file. kp3 and the C core are two
implementations of one grammar, and a hand-maintained twin drifts. Running
both over one corpus and demanding identical verdicts *and* identical parsed
fields is what keeps them honest.
"""

from __future__ import annotations

import ctypes
import random
import re
import shutil
import subprocess
from pathlib import Path

import kp3
import pytest

ROOT = Path(__file__).resolve().parents[1]
WIDGETS = ROOT / "config/boards/shields/lpm_view/widgets"
SHIM = Path(__file__).resolve().parent / "kp3_core_shim.c"
CORE = WIDGETS / "live_data_core.c"


def _attention_levels() -> tuple[str, ...]:
    """Attention levels, in enum order, read from the firmware header.

    Deliberately not in kp3: attention is the firmware's LED semantic, not
    part of the KP3 wire grammar, so it has no business in the wire contract.
    """
    header = (WIDGETS / "live_data.h").read_text()
    block = re.search(r"enum keypoint_live_data_attention\s*\{(.*?)\};", header, re.S)
    assert block is not None, "enum keypoint_live_data_attention not found"
    levels = tuple(dict.fromkeys(re.findall(r"KEYPOINT_LIVE_DATA_ATTENTION_([A-Z_]+)", block.group(1))))
    assert levels, "no attention levels parsed"
    return levels


ATTENTION_LEVELS = _attention_levels()


@pytest.fixture(scope="session")
def core(tmp_path_factory: pytest.TempPathFactory) -> ctypes.CDLL:
    """Compile the pure core + ctypes shim with the host cc."""
    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None:
        raise RuntimeError("no host C compiler found; the KP3 core tests need cc or gcc")

    library = tmp_path_factory.mktemp("kp3core") / "libkp3core.so"
    subprocess.run(
        [
            compiler,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-shared",
            "-fPIC",
            f"-I{WIDGETS}",
            str(SHIM),
            str(CORE),
            "-o",
            str(library),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    lib = ctypes.CDLL(str(library))
    lib.kp3_shim_deck_size.restype = ctypes.c_size_t
    lib.kp3_shim_line_count.restype = ctypes.c_size_t
    lib.kp3_shim_line_stride.restype = ctypes.c_size_t
    return lib


class Deck:
    """A firmware deck instance, driven through the shim."""

    def __init__(self, lib: ctypes.CDLL) -> None:
        self._lib = lib
        self._line_count = lib.kp3_shim_line_count()
        self._stride = lib.kp3_shim_line_stride()
        self._buffer = ctypes.create_string_buffer(lib.kp3_shim_deck_size())
        lib.kp3_shim_deck_reset(self._buffer)

    def _lines(self, raw: ctypes.Array) -> tuple[str, ...]:
        return tuple(
            bytes(raw[i * self._stride : (i + 1) * self._stride]).split(b"\0")[0].decode("ascii")
            for i in range(self._line_count)
        )

    def write(self, frame: str, now_ms: int = 0) -> tuple[int, bool]:
        """Feed one frame in as the GATT handler would. -> (parse code, committed)."""
        committed = ctypes.c_int()
        data = frame.encode("latin-1")
        ret = self._lib.kp3_shim_write(
            self._buffer,
            data,
            ctypes.c_uint16(len(data)),
            ctypes.c_int64(now_ms),
            ctypes.byref(committed),
        )
        return ret, bool(committed.value)

    def accept(self, frame: str, now_ms: int = 0) -> bool:
        ret, committed = self.write(frame, now_ms)
        assert ret == 0, f"core rejected {frame!r}"
        return committed

    def snapshot(self, now_ms: int = 0) -> dict[str, object]:
        out = [ctypes.c_int() for _ in range(8)]
        raw = ctypes.create_string_buffer(self._line_count * self._stride)
        self._lib.kp3_shim_snapshot(self._buffer, ctypes.c_int64(now_ms), *(ctypes.byref(value) for value in out), raw)
        icon, led_hint, attention, has_data, stale, generation, view_index, total_pages = (value.value for value in out)
        return {
            "icon": kp3.ICON_NAMES[icon],
            "led_hint": led_hint,
            "attention": ATTENTION_LEVELS[attention],
            "has_data": bool(has_data),
            "stale": bool(stale),
            "generation": generation,
            "view_index": view_index,
            "total_pages": total_pages,
            "lines": self._lines(raw),
        }

    def page_advance(self, delta: int) -> bool:
        return bool(self._lib.kp3_shim_page_advance(self._buffer, ctypes.c_int(delta)))

    def parse(self, frame: str) -> tuple[int, kp3.Frame | None]:
        out = [ctypes.c_int() for _ in range(5)]
        raw = ctypes.create_string_buffer(self._line_count * self._stride)
        data = frame.encode("latin-1")
        ret = self._lib.kp3_shim_parse(data, ctypes.c_uint16(len(data)), *(ctypes.byref(value) for value in out), raw)
        if ret < 0:
            return ret, None
        generation, index, total, icon, led_hint = (value.value for value in out)
        return ret, kp3.Frame(
            generation=generation,
            index=index,
            total=total,
            icon=kp3.ICON_NAMES[icon],
            led_hint=led_hint,
            lines=self._lines(raw),
        )


@pytest.fixture
def deck(core: ctypes.CDLL) -> Deck:
    return Deck(core)


def card(index: int, total: int, *, generation: int, text: str = "X", icon: str = "SUN") -> str:
    return kp3.build_frame(icon, kp3.title(text), generation=generation, index=index, total=total)


# ---------------------------------------------------------------------------
# Differential corpus: kp3 and the compiled core must agree, verdict and fields
# ---------------------------------------------------------------------------


def _corpus() -> list[str]:
    line = "Z" * kp3.LINE_MAX
    lines = [line] * kp3.TEXT_LINE_COUNT
    joined = "|".join(lines)

    frames = [
        # Accepted
        kp3.build_frame("NONE"),
        kp3.build_frame("SUN", "A", "B", "C", "D", "E", "F", generation=0x00),
        kp3.build_frame("CLAUDE", *lines, generation=0xFF, index=7, total=8, led_hint=4),
        kp3.claude_card("1h23m", 22, "4d", 41, led_hint=0, generation=0xA0),
        kp3.codex_card("NOW", 96, "18h", 89, led_hint=3, generation=0x0F, index=1, total=2),
        *(kp3.build_frame(icon) for icon in kp3.ICON_NAMES),
        *(kp3.build_frame("SUN", led_hint=code) for code in kp3.LED_CODES),
        # Rejected
        "",
        "KP3",
        "KP2|A0|0|1|SUN|0|" + joined,
        f"KP3|a0|0|1|SUN|0|{joined}",
        f"KP3|A|0|1|SUN|0|{joined}",
        f"KP3|A0F|0|1|SUN|0|{joined}",
        f"KP3|GG|0|1|SUN|0|{joined}",
        f"KP3||0|1|SUN|0|{joined}",
        f"KP3|A0||1|SUN|0|{joined}",
        f"KP3|A0|0||SUN|0|{joined}",
        f"KP3|A0|0|0|SUN|0|{joined}",
        f"KP3|A0|0|9|SUN|0|{joined}",
        f"KP3|A0|1|1|SUN|0|{joined}",
        f"KP3|A0|3|2|SUN|0|{joined}",
        f"KP3|A0|x|1|SUN|0|{joined}",
        f"KP3|A0|0|1|MOON|0|{joined}",
        f"KP3|A0|0|1||0|{joined}",
        f"KP3|A0|0|1|sun|0|{joined}",
        f"KP3|A0|0|1|SUN|5|{joined}",
        f"KP3|A0|0|1|SUN||{joined}",
        f"KP3|A0|0|1|SUN|01|{joined}",
        f"KP3|A0|0|1|SUN|0|{joined}|X",
        f"KP3|A0|0|1|SUN|0|{joined}|",
        "KP3|A0|0|1|SUN|0|" + "|".join(lines[:-1]),
        "KP3|A0|0|1|SUN|0|" + "|".join(["Z" * (kp3.LINE_MAX + 1), *lines[1:]]),
        "KP3|A0|0|1|" + "S" * (kp3.ICON_MAX + 1) + f"|0|{joined}",
        "KP3|A0|0|1|SUN|0|" + "|".join(["\x01", *lines[1:]]),
        "KP3|A0|0|1|SUN|0|" + "|".join(["\x7f", *lines[1:]]),
        "KP3|A0|0|1|SUN|0|" + "|".join(["A|B", *lines[1:]]),
        "KP3|A0|0|1|" + "S" * kp3.ICON_MAX + f"|0|{joined}" + "!",  # over FRAME_MAX
    ]
    return frames


CORPUS = _corpus()


@pytest.mark.parametrize("frame", CORPUS, ids=range(len(CORPUS)))
def test_python_and_c_parsers_agree(deck: Deck, frame: str) -> None:
    ret, c_frame = deck.parse(frame)

    try:
        expected = kp3.parse(frame)
    except kp3.FrameError:
        assert ret < 0, f"C core accepted a frame kp3 rejects: {frame!r}"
        return

    assert ret == 0, f"C core rejected a frame kp3 accepts: {frame!r}"
    assert c_frame == expected


def test_the_corpus_covers_both_verdicts() -> None:
    """A corpus that only exercises one verdict proves nothing."""
    accepted = sum(1 for frame in CORPUS if _accepts(frame))
    assert accepted >= 10
    assert len(CORPUS) - accepted >= 20


_FUZZ_FIELDS = ("", "A0", "a0", "0", "9", "SUN", "CLAUDE", "MOON", "4", "5", "Z" * 9, "Z" * 10, "AB")
_FUZZ_BYTES = tuple(chr(code) for code in range(0x20, 0x7F)) + ("\x00", "\x01", "\x7f", "|", "\xff")


def _random_frame(rng: random.Random) -> str:
    """Three shapes: structured garbage, a near-valid frame with one field
    mutated (where the interesting disagreements live), and raw byte soup."""
    match rng.randrange(3):
        case 0:
            fields = [rng.choice(_FUZZ_FIELDS) for _ in range(rng.randrange(8, 14))]
            prefix = kp3.PREFIX if rng.random() < 0.9 else "KP2|"
            return prefix + "|".join(fields)
        case 1:
            fields = ["A0", "0", "1", "SUN", "0", *(f"L{i}" for i in range(kp3.TEXT_LINE_COUNT))]
            fields[rng.randrange(len(fields))] = rng.choice(_FUZZ_FIELDS)
            return kp3.PREFIX + "|".join(fields)
        case _:
            return "".join(rng.choice(_FUZZ_BYTES) for _ in range(rng.randrange(0, 90)))


def test_the_parsers_agree_on_random_frames(deck: Deck) -> None:
    """The hand-written corpus only covers what someone thought to list.

    Seeded, so a failure is reproducible; the seed is fixed rather than
    time-based so CI cannot go red on a frame nobody can regenerate.
    """
    rng = random.Random(20260727)
    for _ in range(5_000):
        frame = _random_frame(rng)
        ret, c_frame = deck.parse(frame)
        try:
            expected = kp3.parse(frame)
        except kp3.FrameError:
            assert ret < 0, f"C core accepted a frame kp3 rejects: {frame!r}"
            continue
        assert ret == 0, f"C core rejected a frame kp3 accepts: {frame!r}"
        assert c_frame == expected, f"parsed fields differ for {frame!r}"


def _accepts(frame: str) -> bool:
    try:
        kp3.parse(frame)
    except kp3.FrameError:
        return False
    return True


# ---------------------------------------------------------------------------
# Deck staging
# ---------------------------------------------------------------------------


def test_a_single_page_deck_commits_on_arrival(deck: Deck) -> None:
    assert deck.accept(card(0, 1, generation=0xA0, text="ONE"))
    snapshot = deck.snapshot()
    assert snapshot["has_data"] is True
    assert snapshot["total_pages"] == 1
    assert snapshot["generation"] == 0xA0
    assert snapshot["lines"][0] == kp3.title("ONE")


def test_a_deck_commits_only_when_every_page_has_arrived(deck: Deck) -> None:
    assert not deck.accept(card(0, 3, generation=0xB1, text="P0"))
    assert not deck.accept(card(1, 3, generation=0xB1, text="P1"))
    assert deck.snapshot()["has_data"] is False, "staged pages must not be visible"

    assert deck.accept(card(2, 3, generation=0xB1, text="P2"))
    snapshot = deck.snapshot()
    assert snapshot["has_data"] is True
    assert snapshot["total_pages"] == 3
    assert snapshot["lines"][0] == kp3.title("P0")


def test_pages_may_arrive_out_of_order(deck: Deck) -> None:
    assert not deck.accept(card(2, 3, generation=0xC0))
    assert not deck.accept(card(0, 3, generation=0xC0))
    assert deck.accept(card(1, 3, generation=0xC0))


def test_a_repeated_page_does_not_complete_a_deck(deck: Deck) -> None:
    assert not deck.accept(card(0, 2, generation=0xD0, text="A"))
    assert not deck.accept(card(0, 2, generation=0xD0, text="B"))
    assert deck.snapshot()["has_data"] is False

    assert deck.accept(card(1, 2, generation=0xD0))
    assert deck.snapshot()["lines"][0] == kp3.title("B"), "the later page-0 write wins"


def test_a_new_generation_restarts_staging(deck: Deck) -> None:
    assert not deck.accept(card(0, 2, generation=0xE0))
    assert not deck.accept(card(0, 2, generation=0xE1)), "generation change discards the old stage"
    assert deck.accept(card(1, 2, generation=0xE1))
    assert deck.snapshot()["generation"] == 0xE1


def test_a_total_change_restarts_staging(deck: Deck) -> None:
    assert not deck.accept(card(0, 3, generation=0xE2))
    assert deck.accept(card(0, 1, generation=0xE2)), "a one-page deck of the same generation commits"
    assert deck.snapshot()["total_pages"] == 1


def test_a_new_generation_replaces_the_committed_deck(deck: Deck) -> None:
    assert deck.accept(card(0, 1, generation=0x10, text="OLD"))
    assert deck.accept(card(0, 1, generation=0x11, text="NEW"))
    snapshot = deck.snapshot()
    assert snapshot["generation"] == 0x11
    assert snapshot["lines"][0] == kp3.title("NEW")


def test_a_shrinking_deck_pulls_the_view_index_back_into_range(deck: Deck) -> None:
    for index in range(3):
        deck.accept(card(index, 3, generation=0x20))
    deck.page_advance(+2)
    assert deck.snapshot()["view_index"] == 2

    assert deck.accept(card(0, 1, generation=0x21))
    assert deck.snapshot()["view_index"] == 0


# ---------------------------------------------------------------------------
# Page navigation
# ---------------------------------------------------------------------------


def test_paging_wraps_in_both_directions(deck: Deck) -> None:
    for index in range(3):
        deck.accept(card(index, 3, generation=0x30, text=f"P{index}"))

    assert deck.snapshot()["view_index"] == 0
    assert deck.page_advance(+1) and deck.snapshot()["view_index"] == 1
    assert deck.page_advance(+1) and deck.snapshot()["view_index"] == 2
    assert deck.page_advance(+1) and deck.snapshot()["view_index"] == 0, "next wraps to the front"
    assert deck.page_advance(-1) and deck.snapshot()["view_index"] == 2, "prev wraps to the back"


def test_paging_shows_the_page_it_lands_on(deck: Deck) -> None:
    for index in range(2):
        deck.accept(card(index, 2, generation=0x31, text=f"P{index}"))
    deck.page_advance(+1)
    assert deck.snapshot()["lines"][0] == kp3.title("P1")


def test_paging_a_single_page_deck_changes_nothing(deck: Deck) -> None:
    deck.accept(card(0, 1, generation=0x32))
    assert deck.page_advance(+1) is False
    assert deck.snapshot()["view_index"] == 0


def test_paging_an_empty_deck_changes_nothing(deck: Deck) -> None:
    assert deck.page_advance(+1) is False


# ---------------------------------------------------------------------------
# Staleness and the no-data fallback
# ---------------------------------------------------------------------------


def test_data_goes_stale_exactly_at_the_derived_threshold(deck: Deck) -> None:
    deck.accept(card(0, 1, generation=0x40), now_ms=1_000)

    assert deck.snapshot(now_ms=1_000)["stale"] is False
    assert deck.snapshot(now_ms=1_000 + kp3.STALE_MS - 1)["stale"] is False
    assert deck.snapshot(now_ms=1_000 + kp3.STALE_MS)["stale"] is True


def test_a_fresh_frame_clears_staleness(deck: Deck) -> None:
    deck.accept(card(0, 1, generation=0x41), now_ms=0)
    assert deck.snapshot(now_ms=kp3.STALE_MS)["stale"] is True

    deck.accept(card(0, 1, generation=0x42), now_ms=kp3.STALE_MS)
    assert deck.snapshot(now_ms=kp3.STALE_MS)["stale"] is False


def test_an_empty_deck_reports_the_no_data_card(deck: Deck) -> None:
    snapshot = deck.snapshot()
    assert snapshot["has_data"] is False
    assert snapshot["stale"] is False
    assert snapshot["icon"] == "WARN"
    assert snapshot["lines"][0] == "NO DATA"
    assert snapshot["lines"][1] == "WAITING"
    assert snapshot["total_pages"] == 1, "the page rail needs a deck size even when empty"


def test_stale_data_keeps_its_text(deck: Deck) -> None:
    """1-bit rendering cannot dim, so stale cards stay readable and the health
    strip carries the signal. Losing the text would be a silent regression."""
    deck.accept(card(0, 1, generation=0x51, text="KEEP"), now_ms=0)
    stale = deck.snapshot(now_ms=kp3.STALE_MS)

    assert stale["stale"] is True
    assert stale["has_data"] is True
    assert stale["lines"][0] == kp3.title("KEEP")


# ---------------------------------------------------------------------------
# Attention level: the one LED semantic, folded here so the LED driver
# needs no opinion about icons or staleness
# ---------------------------------------------------------------------------


def attention_for(deck: Deck, *, icon: str, led_hint: int, stale: bool = False) -> str:
    deck.accept(kp3.build_frame(icon, kp3.title("X"), generation=0x60, led_hint=led_hint), now_ms=0)
    return str(deck.snapshot(now_ms=kp3.STALE_MS if stale else 0)["attention"])


@pytest.mark.parametrize(
    ("led_hint", "expected"),
    [(1, "ACTIVE"), (2, "ATTENTION"), (3, "WARNING"), (4, "ERROR")],
)
def test_an_explicit_led_hint_wins(deck: Deck, led_hint: int, expected: str) -> None:
    assert attention_for(deck, icon="SUN", led_hint=led_hint) == expected


@pytest.mark.parametrize(
    ("icon", "expected"),
    [
        ("CLAUDE", "HEARTBEAT_SINGLE"),
        ("CODEX", "HEARTBEAT_DOUBLE"),
        ("WARN", "CAUTION"),
        ("SUN", "IDLE"),
        ("NONE", "IDLE"),
    ],
)
def test_an_unhinted_card_falls_back_to_what_its_icon_says(deck: Deck, icon: str, expected: str) -> None:
    assert attention_for(deck, icon=icon, led_hint=0) == expected


def test_staleness_outranks_both_hint_and_icon(deck: Deck) -> None:
    assert attention_for(deck, icon="CLAUDE", led_hint=4, stale=True) == "STALE"


def test_an_empty_deck_reports_no_data_attention(deck: Deck) -> None:
    assert deck.snapshot()["attention"] == "NO_DATA"


def test_every_attention_level_is_distinct(deck: Deck) -> None:
    """Each level is a distinct blink pattern on the device; two folding to one
    is a silent regression the LED driver cannot detect."""
    reached = {
        deck.snapshot()["attention"],
        attention_for(deck, icon="CLAUDE", led_hint=0, stale=True),
        *(attention_for(deck, icon="SUN", led_hint=code) for code in kp3.LED_CODES if code),
        *(attention_for(deck, icon=icon, led_hint=0) for icon in ("CLAUDE", "CODEX", "WARN", "SUN")),
    }
    assert reached == set(ATTENTION_LEVELS), f"unreachable levels: {set(ATTENTION_LEVELS) - reached}"


def test_a_rejected_frame_leaves_the_deck_untouched(deck: Deck) -> None:
    deck.accept(card(0, 1, generation=0x50, text="KEEP"))

    ret, committed = deck.write("KP3|A0|0|9|SUN|0|X|||||")
    assert ret < 0 and not committed

    assert deck.snapshot()["lines"][0] == kp3.title("KEEP")
