# zmk-config-KEYPOINT

ZMK config for the ZitaoTech KEYPOINT split keyboard.

## Current Features

- Left display LiveData service: encrypted BLE write characteristic for compact status cards.
- KP3 deck protocol: whole-deck generation id, page index/total, icon, LED hint, six 9-char text lines.
- Trackpad LED status patterns: touch/backlight preview, USB transport confirmation, LiveData generation confirmation, stale/no-data/error/warning/attention pulses.
- A320 trackpad: interrupt-driven I2C read path, scroll/arrow modes, touch state exposed to the LED driver.

CapsLock LED animation was intentionally removed. This config treats the trackpad LED as a system/status light, not a HID indicator.

## LiveData KP3 Contract

GATT service/characteristic:

- Service: `f5d40000-6d2f-4f4b-9b2a-2f4a8e8c0001`
- Characteristic: `f5d40001-6d2f-4f4b-9b2a-2f4a8e8c0001`
- Permission: encrypted write

Frame:

```text
KP3|GEN|IDX|TOTAL|ICON|LED|L1|L2|L3|L4|L5|L6
```

- `GEN`: exactly two uppercase hex digits. New deck transaction id.
- `IDX`: decimal page index, `0 <= IDX < TOTAL`.
- `TOTAL`: decimal deck size, `1..8`.
- `ICON`: one of firmware `KEYPOINT_LIVE_DATA_ICON_*` ids, including `CLAUDE` and `CODEX`.
- `LED`: `0` none, `1` active, `2` attention, `3` warning, `4` error.
- `L1..L6`: printable ASCII, max 9 chars each, `|` not allowed. A full 9-char line fills the 72px glass edge to edge (monospace 8px glyphs).
- Max frame size: 81 bytes.

Firmware stages KP3 pages by `(GEN, TOTAL)` and only commits the visible deck after every page in that generation has arrived. Old KP2 frames are rejected.

`config/boards/shields/lpm_view/widgets/live_data.{h,c}` is the contract; `scripts/kp3.py` is the tooling authority that derives it. kp3 parses those C sources at import, so every constant above has exactly one home. Preview, demo sender, diagnose probe and the tests all build and validate frames through kp3 — nothing else may declare a contract value.

Producer reference lives in `~/w/_hw/rcink/producer/rcink/keypoint.py`; upgrade producer and firmware together.

## Local Checks

```bash
uv run pytest
```

Preview one frame:

```bash
uv run scripts/preview_keypoint_status.py --frame 'KP3|A0|0|1|CLAUDE|2|CLAUDE  |5H   76%|14:30|7D   88%|RST  90M|OP   18%'
```

Build locally with the checked-out ZMK tree:

```bash
PATH=/Users/rocry/w/zmk-local/zmk/.venv/bin:$PATH west build -s app -d build/keypoint-left -b zitaotech_keypoint_left -- -DZMK_CONFIG=/Users/rocry/w/zmk-config-KEYPOINT/config -DSHIELD='lpm_view;left_bbtrackpad_keypoint'
```
