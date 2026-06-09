#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["bleak>=0.22.0", "typer>=0.12.0"]
# ///

from __future__ import annotations

import asyncio
import platform
from collections.abc import Sequence
from datetime import datetime
from itertools import cycle
from typing import TypeAlias

import typer
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

SERVICE_UUID = "f5d40000-6d2f-4f4b-9b2a-2f4a8e8c0001"
CHAR_UUID = "f5d40001-6d2f-4f4b-9b2a-2f4a8e8c0001"
PREFIX = "KP1|"
LINE_COUNT = 4
LINE_MAX = 8

DEFAULT_DEMO_FRAMES: tuple[tuple[str, str, str, str], ...] = (
    ("SUNNY", "TMP 24C", "AQI 42", "12:34"),
    ("CLOUDY", "TMP 19C", "HUM 62%", "12:35"),
    ("RAIN", "TMP 17C", "WIND 3M", "12:36"),
)

app = typer.Typer(help="Send mock live-data frames to the KEYPOINT left display over BLE.")

BleTarget: TypeAlias = BLEDevice | str


def validate_lines(lines: Sequence[str]) -> None:
    if len(lines) != LINE_COUNT:
        raise ValueError(f"expected {LINE_COUNT} lines, got {len(lines)}")

    for index, line in enumerate(lines, start=1):
        if len(line) > LINE_MAX:
            raise ValueError(f"line {index} is {len(line)} chars, max {LINE_MAX}: {line!r}")

        for ch in line:
            codepoint = ord(ch)
            if ch == "|" or codepoint < 0x20 or codepoint > 0x7E:
                raise ValueError(f"line {index} contains unsupported character {ch!r}")


def build_frame(lines: Sequence[str]) -> bytes:
    validate_lines(lines=lines)
    return f"{PREFIX}{'|'.join(lines)}".encode("ascii")


def with_current_time(lines: Sequence[str]) -> list[str]:
    current = list(lines)
    current[3] = datetime.now().strftime("%H:%M")
    return current


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


async def send_loop(name: str, address: str | None, interval: float, once: bool, scan_timeout: float) -> None:
    if interval <= 0:
        raise ValueError("--interval must be greater than 0")

    target = await resolve_device(name=name, address=address, timeout=scan_timeout)

    async with BleakClient(target, services=[SERVICE_UUID]) as client:
        for frame_lines in cycle(DEFAULT_DEMO_FRAMES):
            lines = with_current_time(lines=frame_lines)
            frame = build_frame(lines=lines)

            await client.write_gatt_char(CHAR_UUID, frame, response=False)
            typer.echo(f"sent {frame.decode('ascii')}")

            if once:
                return

            await asyncio.sleep(interval)


@app.command()
def main(
    name: str = typer.Option("KEYPOINT", help="BLE device name to scan for when --address is unset."),
    address: str | None = typer.Option(None, help="BLE address/UUID. On macOS this is often a UUID."),
    interval: float = typer.Option(30.0, min=0.1, help="Seconds between mock frames."),
    once: bool = typer.Option(False, help="Send one frame and exit."),
    scan_timeout: float = typer.Option(8.0, min=1.0, help="BLE scan timeout in seconds."),
) -> None:
    try:
        asyncio.run(send_loop(name=name, address=address, interval=interval, once=once, scan_timeout=scan_timeout))
    except (BleakError, RuntimeError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
