#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["bleak>=0.22.0", "typer>=0.12.0"]
# ///
"""Send mock KP2 live-data frames to the KEYPOINT left display over BLE.

This file is also the PRODUCER REFERENCE for the KP2 protocol: a real
producer only needs to replicate what build_frame() sends here.

Wire protocol (mirrors config/boards/shields/lpm_view/widgets/live_data.{h,c}):
- Transport: BLE GATT write (with or without response) to CHAR_UUID under
  SERVICE_UUID on the LEFT (central) keyboard half. The characteristic
  requires an encrypted link, so the host must be paired with the keyboard.
- Payload: ASCII "KP2|IDX|TOTAL|ICON|LED|L1|L2|L3|L4|L5|L6", max 72 bytes, no newline.
  * IDX/TOTAL: this card's 0-based page index and the deck size (each a single
    decimal digit, TOTAL in 1..PAGE_MAX). The firmware stores the whole deck;
    the keyboard's left keys page through it locally.
  * ICON: one of ICON_IDS, selects the 8x8 bitmap in the top status row
    (NONE shows no icon).
  * LED: one digit status hint for the trackpad LED: 0=normal, 1=active,
    2=attention, 3=warning, 4=error.
  * Exactly TEXT_LINE_COUNT (6) line fields; each 0..LINE_MAX (8) chars
    from 0x20..0x7E, '|' excluded.
  * The firmware rejects invalid frames with a GATT error and keeps
    showing the previous content.
- Freshness: data turns stale KEYPOINT_LIVE_DATA_STALE_MS (6 min) after the
  last accepted frame -- the health strip under the detail rows changes from
  a solid bar to dashed segments (text stays readable). Push a frame at
  least every few minutes to stay "fresh".

Screen layout (72x144 portrait glass; monospace 8x8 font, so each line is
an 8-char-wide grid row):
- Top block, under the status row (battery / feed icon / link symbol):
  lines L1-L3.
- Bottom block, above the health strip and BLE profile grid: lines L4-L6.
- Lines render right-aligned; pad to the full 8 chars to control columns:
  kv("HUM", "40%") -> "HUM  40%" (label left, value right),
  title("SUNNY") -> "SUNNY   " (left-anchored).
- Convention used by the demo cards: L1 title, L2 key metric, L3 data
  timestamp (doubles as a clock), L4-L6 detail rows.

Verify any frame without hardware -- renders a pixel-exact PNG of the glass:
  uv run scripts/preview_keypoint_status.py --frame 'KP2|0|1|SUN|0|SUNNY   |TMP  24C|12:00|UV     5|HUM  40%|AQI   42'
"""

from __future__ import annotations

import asyncio
import platform
import random
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import cycle
from time import monotonic
from typing import TypeAlias

import typer
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

SERVICE_UUID = "f5d40000-6d2f-4f4b-9b2a-2f4a8e8c0001"
CHAR_UUID = "f5d40001-6d2f-4f4b-9b2a-2f4a8e8c0001"
PREFIX = "KP2|"
ICON_MAX = 8
TEXT_LINE_COUNT = 6
LINE_MAX = 8
PAGE_MAX = 8  # firmware deck capacity; idx/total are single decimal digits
DEMO_DECK_SIZE = 3  # pages pushed per cycle so page navigation can be exercised
LED_HINT_IDS = frozenset({"0", "1", "2", "3", "4"})
ICON_IDS = frozenset(
    {
        "NONE",
        "SUN",
        "CLOUD",
        "RAIN",
        "TEMP",
        "WARN",
        "CODE",
        "TIME",
        "CODEX",
        "CLAUDE",
    }
)


def kv(label: str, value: str) -> str:
    """Pad LABEL + value to a full LINE_MAX-wide line.

    The display font is monospace, so full-width lines turn the screen into an
    8x6 character grid: labels form a left column, values a right column."""
    if len(label) + len(value) >= LINE_MAX:
        raise ValueError(f"kv({label!r}, {value!r}) does not fit {LINE_MAX} chars with a gap")
    return f"{label}{' ' * (LINE_MAX - len(label) - len(value))}{value}"


def title(text: str) -> str:
    """Left-anchor a card title by padding it to the full line width."""
    if len(text) > LINE_MAX:
        raise ValueError(f"title {text!r} longer than {LINE_MAX} chars")
    return text.ljust(LINE_MAX)


@dataclass(frozen=True, slots=True)
class DemoSource:
    """One dashboard card: line1 title + line2 key metric + data_time on the
    top canvas, extra1-3 detail rows on the middle canvas."""

    icon: str
    led_hint: str
    line1: str
    line2: str
    extra1: str = ""
    extra2: str = ""
    extra3: str = ""


DEFAULT_DEMO_SOURCES: tuple[DemoSource, ...] = (
    # Grid test card: every line at max width.
    DemoSource(
        icon="NONE",
        led_hint="0",
        line1="MAX8CHAR",
        line2="ABCDEFGH",
        extra1="12345678",
        extra2="IJKLMNOP",
        extra3="87654321",
    ),
    DemoSource(
        icon="SUN",
        led_hint="0",
        line1=title("SUNNY"),
        line2=kv("TMP", "24C"),
        extra1=kv("UV", "5"),
        extra2=kv("HUM", "40%"),
        extra3=kv("AQI", "42"),
    ),
    DemoSource(
        icon="SUN",
        led_hint="0",
        line1=title("CLEAR"),
        line2=kv("TMP", "31C"),
        extra1=kv("UV", "8"),
        extra2=kv("WIND", "2M"),
        extra3=kv("AQI", "65"),
    ),
    DemoSource(
        icon="CLOUD",
        led_hint="0",
        line1=title("CLOUDY"),
        line2=kv("TMP", "18C"),
        extra1=kv("HUM", "62%"),
        extra2=kv("PM2", "35"),
        extra3=kv("VIS", "8KM"),
    ),
    DemoSource(
        icon="CLOUD",
        led_hint="0",
        line1=title("OVERCAST"),
        line2=kv("TMP", "15C"),
        extra1=kv("HUM", "71%"),
        extra2=kv("PM2", "52"),
        extra3=kv("VIS", "5KM"),
    ),
    DemoSource(
        icon="RAIN",
        led_hint="0",
        line1=title("RAIN"),
        line2=kv("TMP", "16C"),
        extra1=kv("RAIN", "3MM"),
        extra2=kv("WIND", "6M"),
        extra3=kv("HUM", "88%"),
    ),
    DemoSource(
        icon="RAIN",
        led_hint="2",
        line1=title("STORM"),
        line2=kv("TMP", "14C"),
        extra1=kv("RAIN", "9MM"),
        extra2=kv("GUST", "19M"),
        extra3=kv("VIS", "2KM"),
    ),
    DemoSource(
        icon="TEMP",
        led_hint="0",
        line1=title("INDOOR"),
        line2=kv("IN", "25C"),
        extra1=kv("OUT", "19C"),
        extra2=kv("HUM", "55%"),
        extra3=kv("CO2", "640"),
    ),
    DemoSource(
        icon="TEMP",
        led_hint="0",
        line1=title("OUTDOOR"),
        line2=kv("OUT", "-3C"),
        extra1=kv("FEEL", "-8C"),
        extra2=kv("WIND", "9M"),
        extra3=kv("HUM", "30%"),
    ),
    DemoSource(
        icon="WARN",
        led_hint="3",
        line1=title("AQI WARN"),
        line2=kv("AQI", "142"),
        extra1=kv("PM2", "89"),
        extra2=kv("PM10", "160"),
        extra3=kv("LVL", "BAD"),
    ),
    DemoSource(
        icon="WARN",
        led_hint="3",
        line1=title("LOW BATT"),
        line2=kv("BAT", "9%"),
        extra1=kv("EST", "2H"),
        extra2=kv("CHG", "SOON"),
    ),
    DemoSource(
        icon="CODE",
        led_hint="1",
        line1=title("CI PASS"),
        line2=kv("MAIN", "OK"),
        extra1=kv("TESTS", "56"),
        extra2=kv("COV", "87%"),
        extra3=kv("TIME", "3M"),
    ),
    DemoSource(
        icon="CODE",
        led_hint="4",
        line1=title("CI FAIL"),
        line2=kv("PR", "#142"),
        extra1=kv("FAIL", "2"),
        extra2=kv("AT", "LINT"),
        extra3=kv("DUR", "45S"),
    ),
    DemoSource(
        icon="TIME",
        led_hint="0",
        line1=title("TZ UTC+8"),
        line2=kv("NTP", "OK"),
        extra1=kv("UP", "14D"),
        extra2=kv("DRIFT", "2S"),
    ),
    DemoSource(
        icon="CODEX",
        led_hint="0",
        line1=title("CODEX"),
        line2=kv("5H", "58%"),
        extra1=kv("7D", "45%"),
        extra2=kv("RST", "3H"),
        extra3=kv("CTX", "12%"),
    ),
    DemoSource(
        icon="CODEX",
        led_hint="3",
        line1=title("CODEX"),
        line2=kv("5H", "91%"),
        extra1=kv("7D", "72%"),
        extra2=kv("RST", "36M"),
        extra3=kv("CTX", "40%"),
    ),
    DemoSource(
        icon="CLAUDE",
        led_hint="0",
        line1=title("CLAUDE"),
        line2=kv("5H", "22%"),
        extra1=kv("WK", "41%"),
        extra2=kv("CTX", "64%"),
        extra3=kv("TOK", "81K"),
    ),
    DemoSource(
        icon="CLAUDE",
        led_hint="2",
        line1=title("CLAUDE"),
        line2=kv("5H", "76%"),
        extra1=kv("WK", "88%"),
        extra2=kv("RST", "90M"),
        extra3=kv("CTX", "18%"),
    ),
)

app = typer.Typer(help="Send mock live-data frames to the KEYPOINT left display over BLE.")

BleTarget: TypeAlias = BLEDevice | str
DemoGenerator: TypeAlias = Callable[[random.Random], DemoSource]


def random_none_source(rng: random.Random) -> DemoSource:
    _ = rng
    return DemoSource(
        icon="NONE",
        led_hint="0",
        line1="MAX8CHAR",
        line2="ABCDEFGH",
        extra1="12345678",
        extra2="IJKLMNOP",
        extra3="87654321",
    )


def random_sun_source(rng: random.Random) -> DemoSource:
    return DemoSource(
        icon="SUN",
        led_hint="0",
        line1=title(rng.choice(("SUNNY", "CLEAR"))),
        line2=kv("TMP", f"{rng.randint(18, 35)}C"),
        extra1=kv("UV", str(rng.randint(1, 9))),
        extra2=kv("HUM", f"{rng.randint(20, 60)}%"),
        extra3=kv("AQI", str(rng.randint(10, 99))),
    )


def random_cloud_source(rng: random.Random) -> DemoSource:
    return DemoSource(
        icon="CLOUD",
        led_hint="0",
        line1=title(rng.choice(("CLOUDY", "OVERCAST"))),
        line2=kv("TMP", f"{rng.randint(8, 22)}C"),
        extra1=kv("HUM", f"{rng.randint(35, 85)}%"),
        extra2=kv("PM2", str(rng.randint(10, 80))),
        extra3=kv("VIS", f"{rng.randint(2, 9)}KM"),
    )


def random_rain_source(rng: random.Random) -> DemoSource:
    return DemoSource(
        icon="RAIN",
        led_hint=rng.choice(("0", "2")),
        line1=title(rng.choice(("RAIN", "STORM"))),
        line2=kv("TMP", f"{rng.randint(8, 20)}C"),
        extra1=kv("RAIN", f"{rng.randint(1, 9)}MM"),
        extra2=kv("WIND", f"{rng.randint(1, 19)}M"),
        extra3=kv("HUM", f"{rng.randint(70, 99)}%"),
    )


def random_temp_source(rng: random.Random) -> DemoSource:
    return DemoSource(
        icon="TEMP",
        led_hint="0",
        line1=title("INDOOR"),
        line2=kv("IN", f"{rng.randint(18, 28)}C"),
        extra1=kv("OUT", f"{rng.randint(-9, 35)}C"),
        extra2=kv("HUM", f"{rng.randint(30, 70)}%"),
        extra3=kv("CO2", str(rng.randint(400, 999))),
    )


def random_warn_source(rng: random.Random) -> DemoSource:
    if rng.choice((True, False)):
        return DemoSource(
            icon="WARN",
            led_hint="3",
            line1=title("AQI WARN"),
            line2=kv("AQI", str(rng.randint(101, 199))),
            extra1=kv("PM2", str(rng.randint(60, 99))),
            extra2=kv("PM10", str(rng.randint(100, 199))),
            extra3=kv("LVL", "BAD"),
        )
    return DemoSource(
        icon="WARN",
        led_hint="3",
        line1=title("LOW BATT"),
        line2=kv("BAT", f"{rng.randint(5, 19)}%"),
        extra1=kv("EST", f"{rng.randint(1, 9)}H"),
        extra2=kv("CHG", "SOON"),
    )


def random_code_source(rng: random.Random) -> DemoSource:
    if rng.choice((True, False)):
        return DemoSource(
            icon="CODE",
            led_hint="1",
            line1=title("CI PASS"),
            line2=kv("MAIN", "OK"),
            extra1=kv("TESTS", str(rng.randint(10, 99))),
            extra2=kv("COV", f"{rng.randint(60, 99)}%"),
            extra3=kv("TIME", f"{rng.randint(1, 9)}M"),
        )
    return DemoSource(
        icon="CODE",
        led_hint="4",
        line1=title("CI FAIL"),
        line2=kv("PR", f"#{rng.randint(100, 999)}"),
        extra1=kv("FAIL", str(rng.randint(1, 9))),
        extra2=kv("AT", rng.choice(("LINT", "TEST", "BUILD"))),
        extra3=kv("DUR", f"{rng.randint(10, 99)}S"),
    )


def random_time_source(rng: random.Random) -> DemoSource:
    return DemoSource(
        icon="TIME",
        led_hint="0",
        line1=title("TZ UTC+8"),
        line2=kv("NTP", "OK"),
        extra1=kv("UP", f"{rng.randint(1, 99)}D"),
        extra2=kv("DRIFT", f"{rng.randint(0, 9)}S"),
    )


def random_codex_source(rng: random.Random) -> DemoSource:
    pct = rng.randint(10, 99)
    return DemoSource(
        icon="CODEX",
        led_hint="3" if pct >= 90 else "2" if pct >= 75 else "0",
        line1=title("CODEX"),
        line2=kv("5H", f"{pct}%"),
        extra1=kv("7D", f"{rng.randint(10, 99)}%"),
        extra2=kv("RST", f"{rng.randint(1, 9)}H"),
        extra3=kv("CTX", f"{rng.randint(10, 99)}%"),
    )


def random_claude_source(rng: random.Random) -> DemoSource:
    pct = rng.randint(10, 99)
    return DemoSource(
        icon="CLAUDE",
        led_hint="3" if pct >= 90 else "2" if pct >= 75 else "0",
        line1=title("CLAUDE"),
        line2=kv("5H", f"{pct}%"),
        extra1=kv("WK", f"{rng.randint(10, 99)}%"),
        extra2=kv("CTX", f"{rng.randint(10, 99)}%"),
        extra3=kv("TOK", f"{rng.randint(10, 99)}K"),
    )


DEMO_GENERATORS: tuple[DemoGenerator, ...] = (
    random_none_source,
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


def demo_deck(source_iter, rng: random.Random, randomize: bool, size: int) -> list[DemoSource]:
    """Build a deck of `size` demo sources (the firmware stores the whole deck;
    the keyboard's left keys page through it)."""
    deck: list[DemoSource] = []
    previous: DemoSource | None = None
    for _ in range(size):
        previous = next_demo_source(source_iter=source_iter, rng=rng, randomize=randomize, previous=previous)
        deck.append(previous)
    return deck


def validate_icon(icon: str) -> None:
    if icon not in ICON_IDS:
        choices = ", ".join(sorted(ICON_IDS))
        raise ValueError(f"unsupported icon {icon!r}; expected one of: {choices}")

    if len(icon) > ICON_MAX:
        raise ValueError(f"icon is {len(icon)} chars, max {ICON_MAX}: {icon!r}")


def validate_led_hint(led_hint: str) -> None:
    if led_hint not in LED_HINT_IDS:
        choices = ", ".join(sorted(LED_HINT_IDS))
        raise ValueError(f"unsupported LED hint {led_hint!r}; expected one of: {choices}")


def validate_lines(lines: Sequence[str]) -> None:
    if len(lines) != TEXT_LINE_COUNT:
        raise ValueError(f"expected {TEXT_LINE_COUNT} text lines, got {len(lines)}")

    for index, line in enumerate(lines, start=1):
        if len(line) > LINE_MAX:
            raise ValueError(f"line {index} is {len(line)} chars, max {LINE_MAX}: {line!r}")

        for ch in line:
            codepoint = ord(ch)
            if ch == "|" or codepoint < 0x20 or codepoint > 0x7E:
                raise ValueError(f"line {index} contains unsupported character {ch!r}")


def build_frame(icon: str, led_hint: str, lines: Sequence[str], *, idx: int = 0, total: int = 1) -> bytes:
    validate_icon(icon=icon)
    validate_led_hint(led_hint=led_hint)
    validate_lines(lines=lines)
    if not (1 <= total <= PAGE_MAX) or not (0 <= idx < total):
        raise ValueError(f"bad page idx={idx} total={total} (PAGE_MAX={PAGE_MAX})")
    return f"{PREFIX}{idx}|{total}|{icon}|{led_hint}|{'|'.join(lines)}".encode("ascii")


def lines_for_source(source: DemoSource, data_time: str) -> tuple[str, str, str, str, str, str]:
    return (source.line1, source.line2, data_time, source.extra1, source.extra2, source.extra3)


async def resolve_connected_macos_device(name: str) -> BLEDevice | None:
    if platform.system() != "Darwin":
        return None

    from bleak.backends.corebluetooth.CentralManagerDelegate import CentralManagerDelegate
    from CoreBluetooth import CBUUID

    manager = CentralManagerDelegate()
    await manager.wait_until_ready()
    peripherals = manager.central_manager.retrieveConnectedPeripheralsWithServices_(
        [CBUUID.UUIDWithString_(SERVICE_UUID)]
    )

    for peripheral in peripherals:
        peripheral_name = peripheral.name()
        if name and peripheral_name != name:
            continue

        return BLEDevice(
            peripheral.identifier().UUIDString(),
            peripheral_name,
            (peripheral, manager),
        )

    return None


async def resolve_device(name: str, address: str | None, timeout: float) -> BleTarget:
    if address:
        return address

    if connected_device := await resolve_connected_macos_device(name=name):
        typer.echo(f"using connected macOS BLE peripheral {connected_device.address}: {connected_device.name}")
        return connected_device

    devices = await BleakScanner.discover(timeout=timeout)
    matches = [device for device in devices if device.name == name]
    if not matches:
        seen = ", ".join(sorted({device.name for device in devices if device.name})) or "none"
        raise RuntimeError(f"no BLE device named {name!r}; seen devices: {seen}")

    return matches[0]


async def send_loop(
    name: str,
    address: str | None,
    interval: float,
    source_interval: float,
    count: int | None,
    once: bool,
    randomize: bool,
    seed: int | None,
    scan_timeout: float,
) -> None:
    if interval <= 0:
        raise ValueError("--interval must be greater than 0")
    if source_interval <= 0:
        raise ValueError("--source-interval must be greater than 0")
    if count is not None and count <= 0:
        raise ValueError("--count must be greater than 0")

    target = await resolve_device(name=name, address=address, timeout=scan_timeout)
    source_iter = cycle(DEFAULT_DEMO_SOURCES)
    rng = random.Random(seed)
    deck = demo_deck(source_iter=source_iter, rng=rng, randomize=randomize, size=DEMO_DECK_SIZE)
    data_time = datetime.now().strftime("%H:%M")
    next_source_update = monotonic() + source_interval
    sent_count = 0

    async with BleakClient(target, services=[SERVICE_UUID]) as client:
        while True:
            now = monotonic()
            if now >= next_source_update:
                deck = demo_deck(source_iter=source_iter, rng=rng, randomize=randomize, size=DEMO_DECK_SIZE)
                data_time = datetime.now().strftime("%H:%M")
                next_source_update = now + source_interval

            # Push the whole deck each cycle; the firmware owns page navigation.
            total = len(deck)
            for idx, source in enumerate(deck):
                frame = build_frame(
                    icon=source.icon,
                    led_hint=source.led_hint,
                    lines=lines_for_source(source=source, data_time=data_time),
                    idx=idx,
                    total=total,
                )
                await client.write_gatt_char(CHAR_UUID, frame, response=False)
                typer.echo(f"sent {frame.decode('ascii')}")
            sent_count += 1

            if once or (count is not None and sent_count >= count):
                return

            await asyncio.sleep(interval)


@app.command()
def main(
    name: str = typer.Option("KEYPOINT", help="BLE device name to scan for when --address is unset."),
    address: str | None = typer.Option(None, help="BLE address/UUID. On macOS this is often a UUID."),
    interval: float = typer.Option(2.0, min=0.1, help="Seconds between mock frames."),
    source_interval: float = typer.Option(2.0, min=0.1, help="Seconds between mock data-source updates."),
    count: int | None = typer.Option(None, min=1, help="Send this many frames and exit."),
    once: bool = typer.Option(False, help="Send one frame and exit."),
    randomize: bool = typer.Option(True, "--random/--sequential", help="Randomize mock data-source updates."),
    seed: int | None = typer.Option(None, help="Seed random mock data for reproducible visual tests."),
    scan_timeout: float = typer.Option(8.0, min=1.0, help="BLE scan timeout in seconds."),
) -> None:
    try:
        asyncio.run(
            send_loop(
                name=name,
                address=address,
                interval=interval,
                source_interval=source_interval,
                count=count,
                once=once,
                randomize=randomize,
                seed=seed,
                scan_timeout=scan_timeout,
            )
        )
    except (BleakError, RuntimeError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
