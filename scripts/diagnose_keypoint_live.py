#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["bleak>=0.22.0", "typer>=0.12.0"]
# ///
"""Diagnose why the KEYPOINT live-data display stays on NO DATA / WAITING.

Writes an OLD-format frame and a NEW-format frame to the keyboard **with
response** (the demo/producer use write-WITHOUT-response, which silently hides
whether the firmware accepted or rejected the frame). With response, the
firmware's GATT accept/reject is visible — which tells us exactly what is wrong.

Run (keyboard must be connected/paired to this Mac):
    uv run scripts/diagnose_keypoint_live.py

Interpret the output:
  * OLD-format ACCEPTED  -> the left/central half is running OLD firmware
                            (the new IDX|TOTAL parser was never flashed there).
                            Fix: flash the new left.uf2 to the LEFT half.
  * OLD rejected, NEW ACCEPTED (display shows SUNNY) -> new firmware works;
                            the earlier NO DATA was a stale/failed send.
  * OLD rejected, NEW rejected -> new firmware is running but rejects valid
                            frames -> a real parser bug to fix.
  * connection / encryption error -> transport/pairing problem, not the parser.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

from bleak import BleakClient

# Reuse the demo sender's device-resolution + UUIDs (single source of truth).
_DEMO = Path(__file__).resolve().parent / "send_keypoint_live_demo.py"
_spec = importlib.util.spec_from_file_location("send_keypoint_live_demo", _DEMO)
demo = importlib.util.module_from_spec(_spec)
sys.modules["send_keypoint_live_demo"] = demo  # slotted @dataclass needs this registered
_spec.loader.exec_module(demo)

# Same card content, two grammars. OLD = pre-change (icon first, no page fields).
OLD_FRAME = b"KP2|SUN|SUNNY|TMP 24C|12:00|UV 5|HUM 40%|AQI 42"
NEW_FRAME = b"KP2|0|1|SUN|SUNNY|TMP 24C|12:00|UV 5|HUM 40%|AQI 42"


async def _run() -> None:
    target = await demo.resolve_device(name="KEYPOINT", address=None, timeout=8.0)
    async with BleakClient(target, services=[demo.SERVICE_UUID]) as client:
        print(f"connected={client.is_connected}  mtu={getattr(client, 'mtu_size', '?')}")
        for label, frame in (("OLD-format", OLD_FRAME), ("NEW-format", NEW_FRAME)):
            try:
                await client.write_gatt_char(demo.CHAR_UUID, frame, response=True)
                print(f"  [{label}] ACCEPTED ({len(frame)} B): {frame.decode()}  <- watch the LEFT display")
            except Exception as exc:  # noqa: BLE001 - report whatever the stack raises
                print(f"  [{label}] REJECTED/failed ({len(frame)} B): {type(exc).__name__}: {exc}")
            await asyncio.sleep(2.5)


if __name__ == "__main__":
    asyncio.run(_run())
