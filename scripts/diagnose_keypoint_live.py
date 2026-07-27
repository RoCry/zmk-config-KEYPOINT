#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["bleak>=0.22.0", "typer>=0.12.0"]
# ///
"""Diagnose why the KEYPOINT live-data display stays on NO DATA / WAITING.

Writes one probe frame to the keyboard **with response** (the demo sender and
real producers write WITHOUT response, which silently hides whether the
firmware accepted or rejected the frame). With response, the firmware's GATT
accept/reject is visible -- which tells us exactly what is wrong.

The probe is built by `scripts/kp3.py` at run time, from the same builders the
demo sender and the producer use. That matters: a hardcoded frame would keep
probing with yesterday's grammar, so a rejection would no longer distinguish
"the firmware is stale" from "this script is stale" -- the one question this
script exists to answer.

Run (keyboard must be connected/paired to this Mac):
    uv run scripts/diagnose_keypoint_live.py

Interpret the output:
  * PROBE ACCEPTED (display shows SUNNY) -> new firmware works;
                            the earlier NO DATA was a stale/failed send.
  * PROBE rejected -> firmware/parser/protocol mismatch. Flash the latest
                            left.uf2 so the firmware speaks the same KP3
                            grammar kp3.py just derived from these sources.
  * connection / encryption error -> transport/pairing problem, not the parser.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

from bleak import BleakClient

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import kp3  # noqa: E402

# Reuse the demo sender's device-resolution + UUIDs (single source of truth).
_DEMO = _SCRIPT_DIR / "send_keypoint_live_demo.py"
_spec = importlib.util.spec_from_file_location("send_keypoint_live_demo", _DEMO)
demo = importlib.util.module_from_spec(_spec)
sys.modules["send_keypoint_live_demo"] = demo  # slotted @dataclass needs this registered
_spec.loader.exec_module(demo)

PROBE_FRAME = kp3.build_frame(
    "SUN",
    kp3.title("SUNNY"),
    kp3.kv("TMP", "24C"),
    "12:00",
    kp3.kv("UV", "5"),
    kp3.kv("HUM", "40%"),
    kp3.kv("AQI", "42"),
    generation=0xA0,
)


async def _run() -> None:
    payload = PROBE_FRAME.encode("ascii")
    target = await demo.resolve_device(name="KEYPOINT", address=None, timeout=8.0)
    async with BleakClient(target, services=[demo.SERVICE_UUID]) as client:
        print(f"connected={client.is_connected}  mtu={getattr(client, 'mtu_size', '?')}")
        try:
            await client.write_gatt_char(demo.CHAR_UUID, payload, response=True)
            print(f"  [PROBE] ACCEPTED ({len(payload)} B): {PROBE_FRAME}  <- watch the LEFT display")
        except Exception as exc:  # noqa: BLE001 - report whatever the stack raises
            print(f"  [PROBE] REJECTED/failed ({len(payload)} B): {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(_run())
