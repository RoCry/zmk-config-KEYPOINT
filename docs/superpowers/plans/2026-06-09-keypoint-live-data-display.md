# KEYPOINT Live Data Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the left display WPM chart with a 4-line live-data panel fed by a BLE GATT demo sender.

**Architecture:** Firmware adds a small `lpm_view` live-data module that owns a custom writable BLE GATT characteristic, validates `KP1|...` frames, stores latest lines in RAM, and asks the display work queue to redraw. The existing central status widget reads that state and renders four `unscii_8` lines in the former WPM chart area. A standalone Python `bleak` script sends mock frames every 30 seconds.

**Tech Stack:** ZMK v0.3.0 config module, Zephyr Bluetooth GATT APIs, LVGL canvas text drawing, Python 3.13, `uv`, `bleak`, `pytest`.

---

## File Map

- Modify `config/boards/shields/lpm_view/CMakeLists.txt`: compile the live-data firmware module for central display builds.
- Modify `config/boards/shields/lpm_view/Kconfig.defconfig`: select Bluetooth GATT dependencies if needed and stop selecting WPM for this display widget.
- Create `config/boards/shields/lpm_view/widgets/live_data.h`: constants, state struct, parser/read API declarations.
- Create `config/boards/shields/lpm_view/widgets/live_data.c`: BLE GATT service, payload validation, state storage, display refresh scheduling.
- Modify `config/boards/shields/lpm_view/widgets/status.c`: replace WPM listener/chart drawing with live-data panel rendering.
- Create `scripts/send_keypoint_live_demo.py`: standalone BLE demo sender with shared protocol constants.
- Create/modify tests under `tests/`: static contract tests for firmware and sender.

## Task 1: Add Protocol Contract Tests

**Files:**
- Create: `tests/test_live_data_contract.py`

- [ ] **Step 1: Write failing tests**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_DATA_H = ROOT / "config/boards/shields/lpm_view/widgets/live_data.h"
STATUS_C = ROOT / "config/boards/shields/lpm_view/widgets/status.c"
CMAKE = ROOT / "config/boards/shields/lpm_view/CMakeLists.txt"
SENDER = ROOT / "scripts/send_keypoint_live_demo.py"


def test_live_data_firmware_contract_constants() -> None:
    text = LIVE_DATA_H.read_text()
    assert "#define KEYPOINT_LIVE_DATA_LINE_COUNT 4" in text
    assert "#define KEYPOINT_LIVE_DATA_LINE_MAX 8" in text
    assert "#define KEYPOINT_LIVE_DATA_STALE_MS 120000" in text
    assert "#define KEYPOINT_LIVE_DATA_PREFIX \"KP1|\"" in text


def test_live_data_compiled_for_central_lpm_view() -> None:
    text = CMAKE.read_text()
    assert "widgets/live_data.c" in text
    assert "NOT CONFIG_ZMK_SPLIT OR CONFIG_ZMK_SPLIT_ROLE_CENTRAL" in text


def test_status_uses_live_data_instead_of_wpm_chart() -> None:
    text = STATUS_C.read_text()
    assert '#include "live_data.h"' in text
    assert "draw_live_data_panel(" in text
    assert "ZMK_SUBSCRIPTION(widget_wpm_status" not in text
    assert "zmk_wpm_get_state" not in text


def test_demo_sender_uses_same_limits() -> None:
    text = SENDER.read_text()
    assert "LINE_COUNT = 4" in text
    assert "LINE_MAX = 8" in text
    assert 'PREFIX = "KP1|"' in text
    assert "CHAR_UUID = \"f5d40001-6d2f-4f4b-9b2a-2f4a8e8c0001\"" in text
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/test_live_data_contract.py -q
```

Expected: fails because `live_data.h` and sender script do not exist yet.

## Task 2: Add Firmware Live-Data Module

**Files:**
- Create: `config/boards/shields/lpm_view/widgets/live_data.h`
- Create: `config/boards/shields/lpm_view/widgets/live_data.c`
- Modify: `config/boards/shields/lpm_view/CMakeLists.txt`
- Modify: `config/boards/shields/lpm_view/Kconfig.defconfig`

- [ ] **Step 1: Create live-data header**

```c
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define KEYPOINT_LIVE_DATA_PREFIX "KP1|"
#define KEYPOINT_LIVE_DATA_LINE_COUNT 4
#define KEYPOINT_LIVE_DATA_LINE_MAX 8
#define KEYPOINT_LIVE_DATA_STALE_MS 120000

struct keypoint_live_data_snapshot {
    char lines[KEYPOINT_LIVE_DATA_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1];
    bool has_data;
    bool stale;
};

int keypoint_live_data_parse(const uint8_t *data, uint16_t len,
                             char out[KEYPOINT_LIVE_DATA_LINE_COUNT]
                                     [KEYPOINT_LIVE_DATA_LINE_MAX + 1]);
struct keypoint_live_data_snapshot keypoint_live_data_snapshot_get(void);
```

- [ ] **Step 2: Create live-data implementation**

Implement:

- `keypoint_live_data_parse(...)`
  - reject null data
  - reject missing `KP1|` prefix
  - reject not exactly 4 fields
- reject fields longer than 8 chars
- reject bytes outside printable ASCII range `0x20..0x7e`
- reject embedded `|` separators by requiring exactly 4 fields
  - copy accepted fields and null-terminate each line
- `keypoint_live_data_snapshot_get()`
  - return `NO DATA`/`WAITING` before first valid packet
  - return `STALE` plus previous lines when older than 120 seconds
- BLE GATT service with writable characteristic:
  - service UUID `f5d40000-6d2f-4f4b-9b2a-2f4a8e8c0001`
  - characteristic UUID `f5d40001-6d2f-4f4b-9b2a-2f4a8e8c0001`
  - update state only on valid parse
  - call `k_work_submit_to_queue(zmk_display_work_q(), &live_data_work)` after valid parse
  - use `BT_GATT_PERM_WRITE_ENCRYPT` for the write characteristic

- [ ] **Step 3: Wire build**

In `config/boards/shields/lpm_view/CMakeLists.txt`, add:

```cmake
zephyr_library_sources(widgets/live_data.c)
```

inside the central branch next to `widgets/status.c`.

In `config/boards/shields/lpm_view/Kconfig.defconfig`, remove the `select ZMK_WPM` line from the central custom widget block.

- [ ] **Step 4: Run contract tests**

Run:

```bash
uv run pytest tests/test_live_data_contract.py -q
```

Expected: still fails until `status.c` and sender script are updated.

## Task 3: Replace WPM Panel Rendering

**Files:**
- Modify: `config/boards/shields/lpm_view/widgets/status.c`
- Modify: `config/boards/shields/lpm_view/widgets/util.h`

- [ ] **Step 1: Remove WPM dependencies**

From `status.c`, remove:

```c
#include <zmk/events/wpm_state_changed.h>
#include <zmk/wpm.h>
```

Remove `struct wpm_status_state`, `set_wpm_status`, `wpm_status_update_cb`,
`wpm_status_get_state`, `ZMK_DISPLAY_WIDGET_LISTENER(widget_wpm_status, ...)`,
and `ZMK_SUBSCRIPTION(widget_wpm_status, zmk_wpm_state_changed);`.

Remove the `uint8_t wpm[10];` field from the central branch of
`struct status_state` in `util.h`.

- [ ] **Step 2: Add live-data drawing helper**

Add to `status.c`:

```c
#include "live_data.h"
```

Add a helper near `draw_top()`:

```c
static void draw_live_data_panel(lv_obj_t *canvas, const lv_draw_label_dsc_t *label_dsc,
                                 const lv_draw_rect_dsc_t *rect_black_dsc,
                                 const lv_draw_rect_dsc_t *rect_white_dsc) {
    lv_canvas_draw_rect(canvas, 0, 21, 70, 44, rect_white_dsc);
    lv_canvas_draw_rect(canvas, 1, 22, 66, 42, rect_black_dsc);

    struct keypoint_live_data_snapshot snapshot = keypoint_live_data_snapshot_get();

    for (int i = 0; i < KEYPOINT_LIVE_DATA_LINE_COUNT; i++) {
        lv_canvas_draw_text(canvas, 3, 24 + (i * 10), 62, label_dsc, snapshot.lines[i]);
    }
}
```

- [ ] **Step 3: Replace WPM drawing block**

In `draw_top()`, replace the WPM rectangle, WPM number, range calculation, point
array, and `lv_canvas_draw_line(...)` with:

```c
draw_live_data_panel(canvas, &label_dsc_wpm, &rect_black_dsc, &rect_white_dsc);
```

Do not call `widget_wpm_status_init()` in `zmk_widget_status_init()`.

- [ ] **Step 4: Run contract tests**

Run:

```bash
uv run pytest tests/test_live_data_contract.py -q
```

Expected: sender-related assertion still fails until Task 4.

## Task 4: Add BLE Demo Sender

**Files:**
- Create: `scripts/send_keypoint_live_demo.py`
- Modify: `tests/test_live_data_contract.py` if import-based sender tests are added.

- [ ] **Step 1: Create standalone script**

Create a PEP 723 script with:

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["bleak>=0.22.0", "typer>=0.12.0"]
# ///
```

Constants:

```python
SERVICE_UUID = "f5d40000-6d2f-4f4b-9b2a-2f4a8e8c0001"
CHAR_UUID = "f5d40001-6d2f-4f4b-9b2a-2f4a8e8c0001"
PREFIX = "KP1|"
LINE_COUNT = 4
LINE_MAX = 8
```

Implement:

- `validate_lines(lines: list[str]) -> None`
- `build_frame(lines: list[str]) -> bytes`
- async BLE connection by `--address` or scan by `--name`
- `--interval`, default 30
- `--once`
- rotating demo frames shown in the spec

- [ ] **Step 2: Run script unit checks**

Run:

```bash
uv run scripts/send_keypoint_live_demo.py --help
```

Expected: Typer help prints options for `--name`, `--address`, `--interval`,
and `--once`.

- [ ] **Step 3: Run contract tests**

Run:

```bash
uv run pytest tests/test_live_data_contract.py -q
```

Expected: pass.

## Task 5: Run Full Available Verification

**Files:**
- Existing tests.

- [ ] **Step 1: Run repository tests**

Run:

```bash
uv run pytest -q
```

Expected: all Python/static tests pass.

- [ ] **Step 2: Run firmware build if ZMK workspace is available**

Check:

```bash
command -v west
```

If `west` is available and the ZMK workspace is initialized, run:

```bash
west build -p -b zitaotech_keypoint_left -- -DSHIELD="lpm_view;left_bbtrackpad_keypoint"
```

Expected: left firmware builds.

If `west` is not available, record that firmware build was not run in the final
answer and rely on static tests plus GitHub Actions.

## Self-Review

- Spec coverage: left-only display, WPM replacement, 4x8 ASCII protocol, BLE demo sender, stale/no-data states, and no real data source are covered.
- Placeholder scan: plan has no TBD/TODO/later placeholders.
- Type consistency: protocol constants use `KEYPOINT_LIVE_DATA_*` in firmware and matching sender constants.
