#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""The mock live-data cards the BLE demo sender pushes to the glass.

A card is one page of a deck: title, key metric, the data timestamp, then
detail rows. Every line is laid out with kp3's builders and every frame is
built by `kp3.build_frame`, so the demo cannot express something the firmware
would reject -- and nothing here restates a limit.

Deliberately stdlib + kp3 only, unlike `send_keypoint_live_demo.py`, which
needs bleak and typer: the cards are the interesting half to test, and CI
installs no BLE stack.
"""

from __future__ import annotations

import random
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import kp3  # noqa: E402


def led(name: str) -> int:
    """The wire code for a named LED hint, looked up in the firmware enum."""
    return kp3.LED_HINT_NAMES.index(name)


@dataclass(frozen=True, slots=True)
class DemoSource:
    """One dashboard card: line1 title + line2 key metric + data_time on the
    top canvas, extra1-3 detail rows on the middle canvas."""

    icon: str
    led_hint: int
    line1: str
    line2: str
    extra1: str = ""
    extra2: str = ""
    extra3: str = ""


def grid_probe_source(rng: random.Random | None = None) -> DemoSource:
    """The max-width card: every line filled edge to edge with distinct glyphs.

    Sized from kp3 so it keeps probing the glass edges -- and keeps making
    truncation obvious -- if the line width or line count ever moves.
    """
    _ = rng
    glyphs = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    width = kp3.LINE_MAX - 1  # the first column carries the row number
    rows = [
        f"{row + 1}" + "".join(glyphs[(row * width + column) % len(glyphs)] for column in range(width))
        for row in range(kp3.TEXT_LINE_COUNT - 1)
    ]
    # One line of the card is the data timestamp, so the card carries the rest.
    line1, line2, extra1, extra2, extra3 = rows
    return DemoSource(
        icon="NONE",
        led_hint=led("NONE"),
        line1=line1,
        line2=line2,
        extra1=extra1,
        extra2=extra2,
        extra3=extra3,
    )


DEFAULT_DEMO_SOURCES: tuple[DemoSource, ...] = (
    grid_probe_source(),
    DemoSource(
        icon="SUN",
        led_hint=led("NONE"),
        line1=kp3.title("SUNNY"),
        line2=kp3.kv("TMP", "24C"),
        extra1=kp3.kv("UV", "5"),
        extra2=kp3.kv("HUM", "40%"),
        extra3=kp3.kv("AQI", "42"),
    ),
    DemoSource(
        icon="SUN",
        led_hint=led("NONE"),
        line1=kp3.title("CLEAR"),
        line2=kp3.kv("TMP", "31C"),
        extra1=kp3.kv("UV", "8"),
        extra2=kp3.kv("WIND", "2M"),
        extra3=kp3.kv("AQI", "65"),
    ),
    DemoSource(
        icon="CLOUD",
        led_hint=led("NONE"),
        line1=kp3.title("CLOUDY"),
        line2=kp3.kv("TMP", "18C"),
        extra1=kp3.kv("HUM", "62%"),
        extra2=kp3.kv("PM2", "35"),
        extra3=kp3.kv("VIS", "8KM"),
    ),
    DemoSource(
        icon="CLOUD",
        led_hint=led("NONE"),
        line1=kp3.title("OVERCAST"),
        line2=kp3.kv("TMP", "15C"),
        extra1=kp3.kv("HUM", "71%"),
        extra2=kp3.kv("PM2", "52"),
        extra3=kp3.kv("VIS", "5KM"),
    ),
    DemoSource(
        icon="RAIN",
        led_hint=led("NONE"),
        line1=kp3.title("RAIN"),
        line2=kp3.kv("TMP", "16C"),
        extra1=kp3.kv("RAIN", "3MM"),
        extra2=kp3.kv("WIND", "6M"),
        extra3=kp3.kv("HUM", "88%"),
    ),
    DemoSource(
        icon="RAIN",
        led_hint=led("ATTENTION"),
        line1=kp3.title("STORM"),
        line2=kp3.kv("TMP", "14C"),
        extra1=kp3.kv("RAIN", "9MM"),
        extra2=kp3.kv("GUST", "19M"),
        extra3=kp3.kv("VIS", "2KM"),
    ),
    DemoSource(
        icon="TEMP",
        led_hint=led("NONE"),
        line1=kp3.title("INDOOR"),
        line2=kp3.kv("IN", "25C"),
        extra1=kp3.kv("OUT", "19C"),
        extra2=kp3.kv("HUM", "55%"),
        extra3=kp3.kv("CO2", "640"),
    ),
    DemoSource(
        icon="TEMP",
        led_hint=led("NONE"),
        line1=kp3.title("OUTDOOR"),
        line2=kp3.kv("OUT", "-3C"),
        extra1=kp3.kv("FEEL", "-8C"),
        extra2=kp3.kv("WIND", "9M"),
        extra3=kp3.kv("HUM", "30%"),
    ),
    DemoSource(
        icon="WARN",
        led_hint=led("WARNING"),
        line1=kp3.title("AQI WARN"),
        line2=kp3.kv("AQI", "142"),
        extra1=kp3.kv("PM2", "89"),
        extra2=kp3.kv("PM10", "160"),
        extra3=kp3.kv("LVL", "BAD"),
    ),
    DemoSource(
        icon="WARN",
        led_hint=led("WARNING"),
        line1=kp3.title("LOW BATT"),
        line2=kp3.kv("BAT", "9%"),
        extra1=kp3.kv("EST", "2H"),
        extra2=kp3.kv("CHG", "SOON"),
    ),
    DemoSource(
        icon="CODE",
        led_hint=led("ACTIVE"),
        line1=kp3.title("CI PASS"),
        line2=kp3.kv("MAIN", "OK"),
        extra1=kp3.kv("TESTS", "56"),
        extra2=kp3.kv("COV", "87%"),
        extra3=kp3.kv("TIME", "3M"),
    ),
    DemoSource(
        icon="CODE",
        led_hint=led("ERROR"),
        line1=kp3.title("CI FAIL"),
        line2=kp3.kv("PR", "#142"),
        extra1=kp3.kv("FAIL", "2"),
        extra2=kp3.kv("AT", "LINT"),
        extra3=kp3.kv("DUR", "45S"),
    ),
    DemoSource(
        icon="TIME",
        led_hint=led("NONE"),
        line1=kp3.title("TZ UTC+8"),
        line2=kp3.kv("NTP", "OK"),
        extra1=kp3.kv("UP", "14D"),
        extra2=kp3.kv("DRIFT", "2S"),
    ),
    DemoSource(
        icon="CODEX",
        led_hint=led("NONE"),
        line1=kp3.title("CODEX"),
        line2=kp3.kv("5H", "58%"),
        extra1=kp3.kv("7D", "45%"),
        extra2=kp3.kv("RST", "3H"),
        extra3=kp3.kv("CTX", "12%"),
    ),
    DemoSource(
        icon="CODEX",
        led_hint=led("WARNING"),
        line1=kp3.title("CODEX"),
        line2=kp3.kv("5H", "91%"),
        extra1=kp3.kv("7D", "72%"),
        extra2=kp3.kv("RST", "36M"),
        extra3=kp3.kv("CTX", "40%"),
    ),
    DemoSource(
        icon="CLAUDE",
        led_hint=led("NONE"),
        line1=kp3.title("CLAUDE"),
        line2=kp3.kv("5H", "22%"),
        extra1=kp3.kv("WK", "41%"),
        extra2=kp3.kv("CTX", "64%"),
        extra3=kp3.kv("TOK", "81K"),
    ),
    DemoSource(
        icon="CLAUDE",
        led_hint=led("ATTENTION"),
        line1=kp3.title("CLAUDE"),
        line2=kp3.kv("5H", "76%"),
        extra1=kp3.kv("WK", "88%"),
        extra2=kp3.kv("RST", "90M"),
        extra3=kp3.kv("CTX", "18%"),
    ),
)

DemoGenerator: TypeAlias = Callable[[random.Random], DemoSource]


def usage_led_hint(pct: int) -> int:
    """Severity for a rate-limit card, the way the reference producer grades it."""
    if pct >= 90:
        return led("WARNING")
    if pct >= 75:
        return led("ATTENTION")
    return led("NONE")


def random_sun_source(rng: random.Random) -> DemoSource:
    return DemoSource(
        icon="SUN",
        led_hint=led("NONE"),
        line1=kp3.title(rng.choice(("SUNNY", "CLEAR"))),
        line2=kp3.kv("TMP", f"{rng.randint(18, 35)}C"),
        extra1=kp3.kv("UV", str(rng.randint(1, 9))),
        extra2=kp3.kv("HUM", f"{rng.randint(20, 60)}%"),
        extra3=kp3.kv("AQI", str(rng.randint(10, 99))),
    )


def random_cloud_source(rng: random.Random) -> DemoSource:
    return DemoSource(
        icon="CLOUD",
        led_hint=led("NONE"),
        line1=kp3.title(rng.choice(("CLOUDY", "OVERCAST"))),
        line2=kp3.kv("TMP", f"{rng.randint(8, 22)}C"),
        extra1=kp3.kv("HUM", f"{rng.randint(35, 85)}%"),
        extra2=kp3.kv("PM2", str(rng.randint(10, 80))),
        extra3=kp3.kv("VIS", f"{rng.randint(2, 9)}KM"),
    )


def random_rain_source(rng: random.Random) -> DemoSource:
    return DemoSource(
        icon="RAIN",
        led_hint=rng.choice((led("NONE"), led("ATTENTION"))),
        line1=kp3.title(rng.choice(("RAIN", "STORM"))),
        line2=kp3.kv("TMP", f"{rng.randint(8, 20)}C"),
        extra1=kp3.kv("RAIN", f"{rng.randint(1, 9)}MM"),
        extra2=kp3.kv("WIND", f"{rng.randint(1, 19)}M"),
        extra3=kp3.kv("HUM", f"{rng.randint(70, 99)}%"),
    )


def random_temp_source(rng: random.Random) -> DemoSource:
    return DemoSource(
        icon="TEMP",
        led_hint=led("NONE"),
        line1=kp3.title("INDOOR"),
        line2=kp3.kv("IN", f"{rng.randint(18, 28)}C"),
        extra1=kp3.kv("OUT", f"{rng.randint(-9, 35)}C"),
        extra2=kp3.kv("HUM", f"{rng.randint(30, 70)}%"),
        extra3=kp3.kv("CO2", str(rng.randint(400, 999))),
    )


def random_warn_source(rng: random.Random) -> DemoSource:
    if rng.choice((True, False)):
        return DemoSource(
            icon="WARN",
            led_hint=led("WARNING"),
            line1=kp3.title("AQI WARN"),
            line2=kp3.kv("AQI", str(rng.randint(101, 199))),
            extra1=kp3.kv("PM2", str(rng.randint(60, 99))),
            extra2=kp3.kv("PM10", str(rng.randint(100, 199))),
            extra3=kp3.kv("LVL", "BAD"),
        )
    return DemoSource(
        icon="WARN",
        led_hint=led("WARNING"),
        line1=kp3.title("LOW BATT"),
        line2=kp3.kv("BAT", f"{rng.randint(5, 19)}%"),
        extra1=kp3.kv("EST", f"{rng.randint(1, 9)}H"),
        extra2=kp3.kv("CHG", "SOON"),
    )


def random_code_source(rng: random.Random) -> DemoSource:
    if rng.choice((True, False)):
        return DemoSource(
            icon="CODE",
            led_hint=led("ACTIVE"),
            line1=kp3.title("CI PASS"),
            line2=kp3.kv("MAIN", "OK"),
            extra1=kp3.kv("TESTS", str(rng.randint(10, 99))),
            extra2=kp3.kv("COV", f"{rng.randint(60, 99)}%"),
            extra3=kp3.kv("TIME", f"{rng.randint(1, 9)}M"),
        )
    return DemoSource(
        icon="CODE",
        led_hint=led("ERROR"),
        line1=kp3.title("CI FAIL"),
        line2=kp3.kv("PR", f"#{rng.randint(100, 999)}"),
        extra1=kp3.kv("FAIL", str(rng.randint(1, 9))),
        extra2=kp3.kv("AT", rng.choice(("LINT", "TEST", "BUILD"))),
        extra3=kp3.kv("DUR", f"{rng.randint(10, 99)}S"),
    )


def random_time_source(rng: random.Random) -> DemoSource:
    return DemoSource(
        icon="TIME",
        led_hint=led("NONE"),
        line1=kp3.title("TZ UTC+8"),
        line2=kp3.kv("NTP", "OK"),
        extra1=kp3.kv("UP", f"{rng.randint(1, 99)}D"),
        extra2=kp3.kv("DRIFT", f"{rng.randint(0, 9)}S"),
    )


def random_codex_source(rng: random.Random) -> DemoSource:
    pct = rng.randint(10, 99)
    return DemoSource(
        icon="CODEX",
        led_hint=usage_led_hint(pct),
        line1=kp3.title("CODEX"),
        line2=kp3.kv("5H", f"{pct}%"),
        extra1=kp3.kv("7D", f"{rng.randint(10, 99)}%"),
        extra2=kp3.kv("RST", f"{rng.randint(1, 9)}H"),
        extra3=kp3.kv("CTX", f"{rng.randint(10, 99)}%"),
    )


def random_claude_source(rng: random.Random) -> DemoSource:
    pct = rng.randint(10, 99)
    return DemoSource(
        icon="CLAUDE",
        led_hint=usage_led_hint(pct),
        line1=kp3.title("CLAUDE"),
        line2=kp3.kv("5H", f"{pct}%"),
        extra1=kp3.kv("WK", f"{rng.randint(10, 99)}%"),
        extra2=kp3.kv("CTX", f"{rng.randint(10, 99)}%"),
        extra3=kp3.kv("TOK", f"{rng.randint(10, 99)}K"),
    )


DEMO_GENERATORS: tuple[DemoGenerator, ...] = (
    grid_probe_source,
    random_sun_source,
    random_cloud_source,
    random_rain_source,
    random_temp_source,
    random_warn_source,
    random_code_source,
    random_time_source,
    random_codex_source,
    random_claude_source,
)


def random_demo_source(rng: random.Random, previous: DemoSource | None) -> DemoSource:
    for _ in range(8):
        source = rng.choice(DEMO_GENERATORS)(rng)
        if previous is None or source != previous:
            return source

    return source


def next_demo_source(
    source_iter: Iterator[DemoSource],
    rng: random.Random,
    randomize: bool,
    previous: DemoSource | None,
) -> DemoSource:
    if randomize:
        return random_demo_source(rng=rng, previous=previous)

    return next(source_iter)


def demo_deck(source_iter: Iterator[DemoSource], rng: random.Random, randomize: bool, size: int) -> list[DemoSource]:
    """Build a deck of `size` demo sources (the firmware stores the whole deck;
    the keyboard's left keys page through it)."""
    deck: list[DemoSource] = []
    previous: DemoSource | None = None
    for _ in range(size):
        previous = next_demo_source(source_iter=source_iter, rng=rng, randomize=randomize, previous=previous)
        deck.append(previous)
    return deck


def card_frame(source: DemoSource, data_time: str, *, generation: int, idx: int, total: int) -> str:
    """One deck page as a KP3 frame; kp3 validates it before it hits the wire.

    Card convention: title, key metric, the data timestamp, then detail rows.
    """
    return kp3.build_frame(
        source.icon,
        source.line1,
        source.line2,
        data_time,
        source.extra1,
        source.extra2,
        source.extra3,
        generation=generation,
        index=idx,
        total=total,
        led_hint=source.led_hint,
    )
