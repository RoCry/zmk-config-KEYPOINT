#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["bleak>=0.22.0", "typer>=0.12.0"]
# ///

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
TEXT_LINE_COUNT = 3
LINE_MAX = 8
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


@dataclass(frozen=True, slots=True)
class DemoSource:
    icon: str
    line1: str
    line2: str


DEFAULT_DEMO_SOURCES: tuple[DemoSource, ...] = (
    DemoSource(icon="NONE", line1="MAX8CHAR", line2="ABCDEFGH"),
    DemoSource(icon="SUN", line1="SUNNY", line2="TMP 24C"),
    DemoSource(icon="SUN", line1="UV HI", line2="AQI 42"),
    DemoSource(icon="CLOUD", line1="CLOUDY", line2="HUM 62%"),
    DemoSource(icon="CLOUD", line1="PM2 035", line2="VIS 8KM"),
    DemoSource(icon="RAIN", line1="RAIN", line2="WIND 3M"),
    DemoSource(icon="RAIN", line1="RAIN 8MM", line2="WIND 12"),
    DemoSource(icon="TEMP", line1="TEMP", line2="24C"),
    DemoSource(icon="TEMP", line1="OUT 19C", line2="IN  25C"),
    DemoSource(icon="WARN", line1="WARN", line2="AQI 142"),
    DemoSource(icon="WARN", line1="LOW BATT", line2="CHG SOON"),
    DemoSource(icon="CODE", line1="BUILD OK", line2="READY"),
    DemoSource(icon="CODE", line1="CI PASS", line2="22 TESTS"),
    DemoSource(icon="TIME", line1="TIME", line2="LOCAL"),
    DemoSource(icon="TIME", line1="TZ  UTC8", line2="SYNC OK"),
    DemoSource(icon="CODEX", line1="CODEX", line2="5h 58%"),
    DemoSource(icon="CODEX", line1="7D 45%", line2="3D 12H"),
    DemoSource(icon="CLAUDE", line1="CLAUDE", line2="CODE"),
    DemoSource(icon="CLAUDE", line1="TOK 81%", line2="CTX OK"),
)

app = typer.Typer(help="Send mock live-data frames to the KEYPOINT left display over BLE.")

BleTarget: TypeAlias = BLEDevice | str
DemoGenerator: TypeAlias = Callable[[random.Random], DemoSource]


def random_none_source(rng: random.Random) -> DemoSource:
    _ = rng
    return DemoSource(icon="NONE", line1="MAX8CHAR", line2="ABCDEFGH")


def random_sun_source(rng: random.Random) -> DemoSource:
    return DemoSource(icon="SUN", line1=rng.choice(("SUNNY", "UV HI")), line2=f"TMP {rng.randint(18, 35):02d}C")


def random_cloud_source(rng: random.Random) -> DemoSource:
    return DemoSource(icon="CLOUD", line1=rng.choice(("CLOUDY", "PM2 035")), line2=f"HUM {rng.randint(35, 85):02d}%")


def random_rain_source(rng: random.Random) -> DemoSource:
    return DemoSource(icon="RAIN", line1=f"RN {rng.randint(1, 18):02d}MM", line2=f"WND {rng.randint(1, 18):02d}M")


def random_temp_source(rng: random.Random) -> DemoSource:
    return DemoSource(icon="TEMP", line1="TEMP", line2=f"OUT {rng.randint(10, 35):02d}C")


def random_warn_source(rng: random.Random) -> DemoSource:
    if rng.choice((True, False)):
        return DemoSource(icon="WARN", line1="AQI WARN", line2=f"AQI {rng.randint(101, 199):03d}")
    return DemoSource(icon="WARN", line1="LOW BATT", line2=f"BAT {rng.randint(5, 19):02d}%")


def random_code_source(rng: random.Random) -> DemoSource:
    if rng.choice((True, False)):
        return DemoSource(icon="CODE", line1="BUILD OK", line2="READY")
    return DemoSource(icon="CODE", line1="CI PASS", line2=f"{rng.randint(10, 99)} TEST")


def random_time_source(rng: random.Random) -> DemoSource:
    return DemoSource(icon="TIME", line1="LOCAL", line2=rng.choice(("SYNC OK", "TZ UTC8")))


def random_codex_source(rng: random.Random) -> DemoSource:
    if rng.choice((True, False)):
        return DemoSource(icon="CODEX", line1="CODEX", line2=f"{rng.randint(1, 9)}h {rng.randint(10, 99)}%")
    return DemoSource(
        icon="CODEX",
        line1=f"{rng.randint(1, 7)}D {rng.randint(10, 99)}%",
        line2=f"CTX {rng.randint(10, 99)}%",
    )


def random_claude_source(rng: random.Random) -> DemoSource:
    if rng.choice((True, False)):
        return DemoSource(icon="CLAUDE", line1="CLAUDE", line2="CODE")
    return DemoSource(icon="CLAUDE", line1=f"TOK {rng.randint(10, 99)}%", line2=f"CTX {rng.randint(10, 99)}%")


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


def validate_icon(icon: str) -> None:
    if icon not in ICON_IDS:
        choices = ", ".join(sorted(ICON_IDS))
        raise ValueError(f"unsupported icon {icon!r}; expected one of: {choices}")

    if len(icon) > ICON_MAX:
        raise ValueError(f"icon is {len(icon)} chars, max {ICON_MAX}: {icon!r}")


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


def build_frame(icon: str, lines: Sequence[str]) -> bytes:
    validate_icon(icon=icon)
    validate_lines(lines=lines)
    return f"{PREFIX}{icon}|{'|'.join(lines)}".encode("ascii")


def lines_for_source(source: DemoSource, data_time: str) -> tuple[str, str, str]:
    return (source.line1, source.line2, data_time)


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
    source = next_demo_source(source_iter=source_iter, rng=rng, randomize=randomize, previous=None)
    data_time = datetime.now().strftime("%H:%M")
    next_source_update = monotonic() + source_interval
    sent_count = 0

    async with BleakClient(target, services=[SERVICE_UUID]) as client:
        while True:
            now = monotonic()
            if now >= next_source_update:
                source = next_demo_source(source_iter=source_iter, rng=rng, randomize=randomize, previous=source)
                data_time = datetime.now().strftime("%H:%M")
                next_source_update = now + source_interval

            frame = build_frame(icon=source.icon, lines=lines_for_source(source=source, data_time=data_time))

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
