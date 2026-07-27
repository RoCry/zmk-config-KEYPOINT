#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["bleak>=0.22.0", "typer>=0.12.0"]
# ///
"""Send mock KP3 live-data decks to the KEYPOINT left display over BLE.

This script owns the transport only. `scripts/kp3.py` is the grammar authority
-- it derives every limit, icon and LED code from the firmware C and builds and
validates the frames -- the README documents the contract for producers, and
`keypoint_demo_cards.py` holds the mock cards. Nothing about the frame layout
is restated here, on purpose: a second copy is how the two drift apart.

Transport:
- BLE GATT write to CHAR_UUID under SERVICE_UUID on the LEFT (central)
  keyboard half. The characteristic requires an encrypted link, so the host
  must already be paired with the keyboard.
- This sender writes WITHOUT response, like a real producer: fast, and the
  firmware's accept/reject verdict is invisible. When a frame is not showing
  up, run `scripts/diagnose_keypoint_live.py`, which writes the same kind of
  frame WITH response so the GATT error surfaces.
- A deck is pushed page by page under one generation; the firmware commits it
  only once every page of that generation has arrived, then the keyboard's
  left keys page through the deck locally.
- Freshness: the display marks data stale `kp3.STALE_MS` after the last
  accepted frame (segmented health strip, text stays readable), so keep the
  loop running to stay fresh.

Render any frame without hardware -- pixel-exact PNG of the glass:
  uv run scripts/preview_keypoint_status.py --frame '<frame>'
"""

from __future__ import annotations

import asyncio
import platform
import random
import sys
from datetime import datetime
from itertools import cycle
from pathlib import Path
from time import monotonic
from typing import TypeAlias

import typer
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import kp3  # noqa: E402
from keypoint_demo_cards import DEFAULT_DEMO_SOURCES, card_frame, demo_deck  # noqa: E402

SERVICE_UUID = "f5d40000-6d2f-4f4b-9b2a-2f4a8e8c0001"
CHAR_UUID = "f5d40001-6d2f-4f4b-9b2a-2f4a8e8c0001"
DEMO_DECK_SIZE = 3  # pages pushed per cycle so page navigation can be exercised
GENERATION_WRAP = 16**kp3.GENERATION_FIELD_MAX

app = typer.Typer(help="Send mock live-data frames to the KEYPOINT left display over BLE.")

BleTarget: TypeAlias = BLEDevice | str


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
    generation = 0

    async with BleakClient(target, services=[SERVICE_UUID]) as client:
        while True:
            now = monotonic()
            if now >= next_source_update:
                deck = demo_deck(source_iter=source_iter, rng=rng, randomize=randomize, size=DEMO_DECK_SIZE)
                data_time = datetime.now().strftime("%H:%M")
                next_source_update = now + source_interval

            # Push the whole deck each cycle; the firmware owns page navigation.
            total = len(deck)
            generation = (generation + 1) % GENERATION_WRAP
            for idx, source in enumerate(deck):
                frame = card_frame(source, data_time, generation=generation, idx=idx, total=total)
                await client.write_gatt_char(CHAR_UUID, frame.encode("ascii"), response=False)
                typer.echo(f"sent {frame}")
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
