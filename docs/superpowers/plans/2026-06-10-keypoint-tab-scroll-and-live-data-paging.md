# KEYPOINT TAB Scroll + Live-Data Page Navigation Implementation Plan

> Historical implementation plan. Current firmware uses the KP3 deck protocol
> (`KP3|GEN|IDX|TOTAL|ICON|LED|L1|..|L6`, 75 bytes max); see `README.md`.
> KP2 details below are retained only as execution history.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the trackpoint hold-to-scroll modifier from the right-thumb BSPC key to the right-thumb TAB key, and turn the two left center-cluster keys into next/previous page controls for a new firmware-side multi-card live-data deck.

**Architecture:** Part 1 is a one-line change to the custom TrackPoint driver's hardcoded scroll-key position. Part 2 replaces the firmware's single live-data snapshot with a deck of pages: the rcink producer pushes every card (each stamped `IDX|TOTAL`), the central (left) half stores all pages, and a `position_state_changed` listener on key positions 32/33 flips the displayed page locally. A host-side pixel-exact simulator (`preview_keypoint_status.py`) and its pytest suite lock the wire protocol before the firmware mirrors it.

**Tech Stack:** ZMK / Zephyr C (firmware, no local build — CI + HIL), Python 3.13 + pytest (host tooling in this repo and the rcink producer), LVGL 1-bpp canvas rendering.

**Two repos:**
- `~/w/zmk-config-KEYPOINT` (this repo): firmware, keymap, demo/preview tooling, tests.
- `~/w/_hw/rcink/producer`: the real card producer.

**Test commands (memorize):**
- This repo (Python): `uv run --with pytest --with "pillow>=11.0" pytest tests/ -q`
- rcink producer: `cd ~/w/_hw/rcink/producer && uv run pytest tests/test_keypoint.py -q`
- Host-side render check: `uv run scripts/preview_keypoint_status.py --frame '<KP2 frame>'`
- Firmware: no local build available — verified by GitHub Actions artifact build + HIL flash.

**Wire protocol (the shared contract):**
```
old:  KP2|ICON|L1|L2|L3|L4|L5|L6                  (66 bytes max)
new:  KP2|IDX|TOTAL|ICON|L1|L2|L3|L4|L5|L6        (70 bytes max)
```
- `IDX`: 0-based page index of this card, `0 .. TOTAL-1` (single decimal digit).
- `TOTAL`: deck size, `1 .. 8` (single decimal digit).
- `MAX_PAGES = 8`. Lines unchanged: 6 fields, each 0..8 chars of `0x20..0x7E`, no `|`.

---

## Part 1 — Scroll trigger BSPC → TAB

### Task A1: Move the driver scroll-key position 49 → 50

**Files:**
- Modify: `config/boards/shields/right_trackpoint_keypoint/custom_driver_right/trackpoint_0x15.c:121-125`

Position 49 is `&lt SYMBOL BSPC` (right thumb); position 50 is `&mt RSHFT TAB` (right thumb, one key over). The driver's global `special_key_listener_cb` sets `scroll_key_pressed` from the watched position.

- [ ] **Step 1: Edit the scroll-key position and fix the stale comment/log**

Current code (lines 121-125):
```c
    // Scroll key (Space)
    if (ev->position == 49) {
        scroll_key_pressed = ev->state;
        LOG_INF("space position=49 %s", scroll_key_pressed ? "PRESSED" : "RELEASED");
    }
```
Replace with:
```c
    // Scroll key (right-thumb TAB, &mt RSHFT TAB at key position 50). Holding
    // it switches trackpoint motion from cursor to scroll. Note: this position
    // is a mod-tap, so holding also engages Right-Shift (host-visible).
    if (ev->position == 50) {
        scroll_key_pressed = ev->state;
        LOG_INF("scroll key position=50 %s", scroll_key_pressed ? "PRESSED" : "RELEASED");
    }
```

- [ ] **Step 2: Verify no other scroll-key reference remains**

Run: `rg -n "position == 49|position=49" config/boards/shields/right_trackpoint_keypoint/`
Expected: no matches (positions 20 and 22 — arrow/slow modes — are unrelated and stay).

- [ ] **Step 3: Commit**

```bash
git add config/boards/shields/right_trackpoint_keypoint/custom_driver_right/trackpoint_0x15.c
git commit -m "feat(trackpoint): move hold-to-scroll trigger from BSPC to right-thumb TAB"
```

> Verified at HIL after the `right` artifact builds: hold right-thumb TAB + move trackpoint → scrolls; tap TAB → still types Tab; holding BSPC no longer scrolls.

---

## Part 2 — Live-data page navigation

### Phase B — Lock the protocol host-side (pixel-exact simulator + tests)

This phase is fully testable locally. It also adds the layout constant the firmware will reuse, so the firmware phase stays in sync automatically (the preview parses `status_layout.h`).

### Task B1: Add the page-indicator layout constant

**Files:**
- Modify: `config/boards/shields/lpm_view/widgets/status_layout.h:16-22`

The top canvas has a free band between the status row (ends ~y=12) and the first live-data line (`KEYPOINT_LIVE_TEXT_Y = 26`). The indicator lives at y=14, right-aligned within the existing text region (`KEYPOINT_LIVE_TEXT_X = 3`, width 67). Both the firmware and the preview read this header, so define it once here.

- [ ] **Step 1: Add the constant after the text-layout defines**

After this block (line 22, `#define KEYPOINT_LIVE_TEXT_LINE_HEIGHT 12`):
```c
#define KEYPOINT_LIVE_TEXT_X 3
#define KEYPOINT_LIVE_TEXT_Y 26
#define KEYPOINT_LIVE_TEXT_WIDTH 67
#define KEYPOINT_LIVE_TEXT_LINE_HEIGHT 12
```
add:
```c
/* Page indicator ("n/N") for a multi-card deck: right-aligned in the free band
 * between the status row and the first live-data line. Shown only when the deck
 * has >1 page. Reuses KEYPOINT_LIVE_TEXT_X / _WIDTH for right alignment. */
#define KEYPOINT_LIVE_PAGE_Y 14
```

- [ ] **Step 2: Confirm the preview picks it up**

Run: `uv run --with "pillow>=11.0" python -c "import importlib.util,pathlib; s=importlib.util.spec_from_file_location('p','scripts/preview_keypoint_status.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.LAYOUT['KEYPOINT_LIVE_PAGE_Y'])"`
Expected: `14`

- [ ] **Step 3: Commit**

```bash
git add config/boards/shields/lpm_view/widgets/status_layout.h
git commit -m "feat(lpm_view): add page-indicator layout constant"
```

### Task B2: Teach the simulator the IDX/TOTAL grammar + render the indicator

**Files:**
- Modify: `scripts/preview_keypoint_status.py`
  - frame-max constant near line 143
  - `LiveDataSnapshot` dataclass (lines 189-194)
  - `parse_live_frame` (lines 197-232)
  - `live_data_snapshot` (lines 235-242)
  - `draw_live_data_panel` (lines 302-320)
  - `_card` helper (lines 483-488)
- Test: `tests/test_live_data_contract.py`, `tests/test_keypoint_status_preview.py`

- [ ] **Step 1: Write failing tests for the new grammar**

Add to `tests/test_live_data_contract.py` (import `parse_live_frame`, `LIVE_FRAME_MAX`, and the module if not already; follow the file's existing import style):
```python
def test_parse_live_frame_returns_idx_total(preview):
    idx, total, icon, lines = preview.parse_live_frame("KP2|1|3|CLAUDE|CLAUDE  |5H   76%|14:30||||")
    assert (idx, total, icon) == (1, 3, "CLAUDE")
    assert lines[0] == "CLAUDE  "


def test_parse_live_frame_rejects_idx_ge_total(preview):
    with pytest.raises(ValueError):
        preview.parse_live_frame("KP2|3|3|CLAUDE|A|||||")  # idx must be < total


def test_parse_live_frame_rejects_zero_total(preview):
    with pytest.raises(ValueError):
        preview.parse_live_frame("KP2|0|0|CLAUDE|A|||||")


def test_live_frame_max_grew_to_70(preview):
    assert preview.LIVE_FRAME_MAX == 70
```
(If the test module loads the preview via an `importlib` fixture, reuse it; otherwise import the functions directly as the file already does. Match the existing pattern in this test file.)

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run --with pytest --with "pillow>=11.0" pytest tests/test_live_data_contract.py -q -k "idx_total or ge_total or zero_total or grew_to_70"`
Expected: FAIL (parse_live_frame returns 2-tuple; LIVE_FRAME_MAX is 66).

- [ ] **Step 3: Update the frame-max constant**

At line 143:
```python
LIVE_FRAME_MAX = len(LIVE_PREFIX) + LIVE_ICON_MAX + (LIVE_LINE_COUNT * LIVE_LINE_MAX) + LIVE_LINE_COUNT
```
replace with:
```python
# Two extra single-digit fields (IDX, TOTAL) with their separators precede ICON.
LIVE_PAGE_FIELD_MAX = 1  # MAX_PAGES = 8 -> idx 0..7, total 1..8 (one digit)
LIVE_FRAME_MAX = (
    len(LIVE_PREFIX)
    + (LIVE_PAGE_FIELD_MAX + 1) * 2
    + LIVE_ICON_MAX
    + (LIVE_LINE_COUNT * LIVE_LINE_MAX)
    + LIVE_LINE_COUNT
)
```

- [ ] **Step 4: Extend the snapshot dataclass**

Lines 189-194:
```python
class LiveDataSnapshot:
    icon: str
    lines: tuple[str, ...]
    has_data: bool
    stale: bool
```
add two fields with defaults (keeps existing positional constructions working):
```python
class LiveDataSnapshot:
    icon: str
    lines: tuple[str, ...]
    has_data: bool
    stale: bool
    view_index: int = 0
    total_pages: int = 1
```

- [ ] **Step 5: Rewrite `parse_live_frame` to read IDX/TOTAL**

Replace the whole function (lines 197-232) with:
```python
def parse_live_frame(frame: str | bytes) -> tuple[int, int, str, tuple[str, ...]]:
    """Port of keypoint_live_data_parse(); raises ValueError where the firmware
    rejects the GATT write with BT_ATT_ERR_VALUE_NOT_ALLOWED. Frame grammar:
    KP2|IDX|TOTAL|ICON|L1|..|L6."""
    data = frame.encode() if isinstance(frame, str) else frame
    if len(data) > LIVE_FRAME_MAX:
        raise ValueError(f"frame longer than {LIVE_FRAME_MAX} bytes")
    prefix = LIVE_PREFIX.encode()
    if not data.startswith(prefix):
        raise ValueError(f"frame must start with {LIVE_PREFIX!r}")

    # Fields after the prefix: 0=IDX, 1=TOTAL, 2=ICON, 3..(2+LINE_COUNT)=lines.
    fields = data[len(prefix):].split(b"|")
    expected = 3 + LIVE_LINE_COUNT
    if len(fields) != expected:
        raise ValueError(f"expected {expected} fields, got {len(fields)}")

    if not (fields[0].isdigit() and fields[1].isdigit()):
        raise ValueError("IDX/TOTAL must be decimal digits")
    idx, total = int(fields[0]), int(fields[1])
    if not (1 <= total) or not (0 <= idx < total):
        raise ValueError(f"bad page idx={idx} total={total}")

    icon_field = fields[2].decode("latin-1")
    if len(icon_field) > LIVE_ICON_MAX or icon_field not in ICON_NAMES:
        raise ValueError(f"unknown icon {icon_field!r}")

    lines = []
    for raw in fields[3:]:
        if len(raw) > LIVE_LINE_MAX or any(not (0x20 <= b <= 0x7E) for b in raw):
            raise ValueError(f"bad line field {raw!r}")
        lines.append(raw.decode("ascii"))
    return idx, total, icon_field, tuple(lines)
```

- [ ] **Step 6: Update `live_data_snapshot` for the new return tuple**

Lines 235-242:
```python
def live_data_snapshot(frame: str | None, stale: bool = False) -> LiveDataSnapshot:
    if frame is None:
        lines = ("NO DATA", "WAITING") + ("",) * (LIVE_LINE_COUNT - 2)
        return LiveDataSnapshot("WARN", lines, has_data=False, stale=False)
    icon, lines = parse_live_frame(frame)
    return LiveDataSnapshot(icon, lines, has_data=True, stale=stale)
```
replace with:
```python
def live_data_snapshot(frame: str | None, stale: bool = False) -> LiveDataSnapshot:
    if frame is None:
        lines = ("NO DATA", "WAITING") + ("",) * (LIVE_LINE_COUNT - 2)
        return LiveDataSnapshot("WARN", lines, has_data=False, stale=False)
    idx, total, icon, lines = parse_live_frame(frame)
    return LiveDataSnapshot(icon, lines, has_data=True, stale=stale, view_index=idx, total_pages=total)
```

- [ ] **Step 7: Draw the page indicator in `draw_live_data_panel`**

At the end of `draw_live_data_panel` (after the line-drawing loop, ~line 320), add:
```python
    if snapshot.has_data and snapshot.total_pages > 1:
        canvas.draw_text(
            LAYOUT["KEYPOINT_LIVE_TEXT_X"],
            LAYOUT["KEYPOINT_LIVE_PAGE_Y"],
            LAYOUT["KEYPOINT_LIVE_TEXT_WIDTH"],
            FONT_UNSCII_8,
            f"{snapshot.view_index + 1}/{snapshot.total_pages}",
            align="right",
        )
```

- [ ] **Step 8: Update the `_card` helper to stamp IDX/TOTAL**

Lines 483-488:
```python
def _card(icon: str, *lines: str) -> str:
    """Build a KP2 frame; missing lines are sent empty."""
    padded = [*lines] + [""] * (LIVE_LINE_COUNT - len(lines))
    return f"{LIVE_PREFIX}{icon}|" + "|".join(padded)
```
replace with:
```python
def _card(icon: str, *lines: str, idx: int = 0, total: int = 1) -> str:
    """Build a KP2 frame; missing lines are sent empty."""
    padded = [*lines] + [""] * (LIVE_LINE_COUNT - len(lines))
    return f"{LIVE_PREFIX}{idx}|{total}|{icon}|" + "|".join(padded)
```

- [ ] **Step 9: Run the new contract tests, verify they pass**

Run: `uv run --with pytest --with "pillow>=11.0" pytest tests/test_live_data_contract.py -q -k "idx_total or ge_total or zero_total or grew_to_70"`
Expected: PASS

### Task B3: Fix the rest of the suite + add an indicator render test

**Files:**
- Modify: `tests/test_live_data_contract.py`, `tests/test_keypoint_status_preview.py`

The `_card` default args keep single-page calls working, but any test that builds a raw `KP2|...` literal or asserts on `parse_live_frame`'s old 2-tuple return must be updated.

- [ ] **Step 1: Find every stale frame literal / return-shape assumption**

Run: `rg -n "parse_live_frame|KP2\||LIVE_FRAME_MAX|== 66|<= ?66" tests/`
For each hit: raw `KP2|ICON|...` literals gain `IDX|TOTAL|` after the prefix; any `icon, lines = parse_live_frame(...)` unpack becomes `idx, total, icon, lines = parse_live_frame(...)`; any `== 66`/`<= 66` frame-size assertion becomes `70`.

- [ ] **Step 2: Add a multi-page indicator render test**

Add to `tests/test_keypoint_status_preview.py` (match the file's existing render-assertion style — it renders to an image and checks pixels/snapshot; reuse its helpers):
```python
def test_indicator_renders_for_multipage_deck(preview):
    snap = preview.live_data_snapshot("KP2|1|3|CLAUDE|CLAUDE  |5H   76%|14:30||||")
    assert (snap.view_index, snap.total_pages) == (1, 3)
    img = preview.render_left_screen(preview.DEMO_CASES[0].state, "KP2|1|3|CLAUDE|CLAUDE  |5H   76%|14:30||||")
    # The "2/3" indicator paints pixels in the y=14 band; a single-page frame does not.
    single = preview.render_left_screen(preview.DEMO_CASES[0].state, "KP2|0|1|CLAUDE|CLAUDE  |5H   76%|14:30||||")
    assert list(img.getdata()) != list(single.getdata())
```

- [ ] **Step 3: Run the full suite**

Run: `uv run --with pytest --with "pillow>=11.0" pytest tests/ -q`
Expected: PASS (was 57 passing; now 57 + new tests, none failing).

- [ ] **Step 4: Eyeball the render**

Run: `uv run scripts/preview_keypoint_status.py --frame 'KP2|1|3|CLAUDE|CLAUDE  |5H   76%|14:30|WK   88%|RST  90M|OP   18%'`
Then open the printed PNG and confirm a `2/3` indicator sits top-right above the first line.

- [ ] **Step 5: Commit**

```bash
git add scripts/preview_keypoint_status.py tests/test_live_data_contract.py tests/test_keypoint_status_preview.py
git commit -m "feat(preview): IDX/TOTAL frame grammar + page indicator"
```

### Phase C — Demo sender

### Task C1: Update the demo sender to the deck grammar

**Files:**
- Modify: `scripts/send_keypoint_live_demo.py` (`build_frame` at line 430-433; the send/loop in `main`)

- [ ] **Step 1: Update `build_frame` to stamp IDX/TOTAL**

Lines 430-433:
```python
def build_frame(icon: str, lines: Sequence[str]) -> bytes:
    ...
    return f"{PREFIX}{icon}|{'|'.join(lines)}".encode("ascii")
```
change the signature and return (keep the existing validation above it):
```python
def build_frame(icon: str, lines: Sequence[str], *, idx: int = 0, total: int = 1) -> bytes:
    ...
    return f"{PREFIX}{idx}|{total}|{icon}|{'|'.join(lines)}".encode("ascii")
```

- [ ] **Step 2: Push a multi-card demo deck**

In `main`'s build/push path, replace the single-frame build with a small fixed deck and write each page once per cycle (find where it currently calls `build_frame(...)` and `write_gatt_char(...)`):
```python
    demo_cards = [
        ("CLAUDE", [title("CLAUDE"), kv("5H", "76%"), "14:30", kv("WK", "88%"), kv("RST", "90M"), kv("OP", "18%")]),
        ("CODEX", [title("CODEX"), kv("RUN", "3"), "14:30", kv("Q", "12"), kv("ETA", "5M"), ""]),
        ("TEMP", [title("INDOOR"), kv("IN", "25C"), "14:30", kv("HUM", "40%"), "", ""]),
    ]
    total = len(demo_cards)
    for idx, (icon, lines) in enumerate(demo_cards):
        frame = build_frame(icon, lines, idx=idx, total=total)
        await client.write_gatt_char(CHAR_UUID, frame, response=False)
```
(Adapt to the file's existing async client/loop structure; the key change is enumerating the deck with `idx`/`total` and writing each page.)

- [ ] **Step 3: Smoke-render one demo frame through the preview**

Run: `uv run scripts/preview_keypoint_status.py --frame 'KP2|1|3|CODEX|CODEX   |RUN    3|14:30|Q     12|ETA    5M|'`
Expected: renders without error, shows `2/3`.

- [ ] **Step 4: Commit**

```bash
git add scripts/send_keypoint_live_demo.py
git commit -m "feat(demo): send a multi-card deck with IDX/TOTAL frames"
```

### Phase D — Firmware deck, navigation, indicator, keymap

No local build. Each task ends by re-running the host-side suite (the preview parses these headers, so contract drift surfaces there) and is finally validated by CI build + HIL.

### Task D1: Deck constants, frame-max, and snapshot API in `live_data.h`

**Files:**
- Modify: `config/boards/shields/lpm_view/widgets/live_data.h`

- [ ] **Step 1: Add deck/page constants and grow the frame-max macro**

After `#define KEYPOINT_LIVE_DATA_LINE_MAX 8` (line 14), add:
```c
#define KEYPOINT_LIVE_DATA_PAGE_MAX 8
#define KEYPOINT_LIVE_DATA_PAGE_FIELD_MAX 1 /* PAGE_MAX <= 9 -> single digit */
```
Replace the frame-max macro (lines 16-20):
```c
#define KEYPOINT_LIVE_DATA_FRAME_MAX                                                                \
    ((sizeof(KEYPOINT_LIVE_DATA_PREFIX) - 1) +                                                     \
     KEYPOINT_LIVE_DATA_ICON_MAX +                                                                 \
     (KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT * KEYPOINT_LIVE_DATA_LINE_MAX) +                          \
     KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT)
```
with (adds IDX + TOTAL single-digit fields and their two separators):
```c
#define KEYPOINT_LIVE_DATA_FRAME_MAX                                                                \
    ((sizeof(KEYPOINT_LIVE_DATA_PREFIX) - 1) +                                                     \
     ((KEYPOINT_LIVE_DATA_PAGE_FIELD_MAX + 1) * 2) +                                               \
     KEYPOINT_LIVE_DATA_ICON_MAX +                                                                 \
     (KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT * KEYPOINT_LIVE_DATA_LINE_MAX) +                          \
     KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT)
```

- [ ] **Step 2: Add page fields to the snapshot struct**

In `struct keypoint_live_data_snapshot` (lines 35-40), add after `bool stale;`:
```c
    uint8_t view_index; /* 0-based index of the page being shown */
    uint8_t total_pages; /* current deck size (1 when empty/NO DATA) */
```

- [ ] **Step 3: Update the parse prototype and add nav declarations**

Change the `keypoint_live_data_parse` prototype (lines 42-45) to carry page info, and add page-nav declarations:
```c
int keypoint_live_data_parse(const uint8_t *data, uint16_t len, uint8_t *idx, uint8_t *total,
                             enum keypoint_live_data_icon *icon,
                             char out[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT]
                                     [KEYPOINT_LIVE_DATA_LINE_MAX + 1]);
struct keypoint_live_data_snapshot keypoint_live_data_snapshot_get(void);
void keypoint_live_data_refresh_displays(void);
```

### Task D2: Deck storage, IDX/TOTAL parse, and page-nav listener in `live_data.c`

**Files:**
- Modify: `config/boards/shields/lpm_view/widgets/live_data.c`

- [ ] **Step 1: Add includes for keymap + position events**

After `#include <zmk/display.h>` (line 15), add:
```c
#include <zmk/keymap.h>
#include <zmk/event_manager.h>
#include <zmk/events/position_state_changed.h>
```

- [ ] **Step 2: Replace the single-snapshot statics with a deck**

Replace lines 29-32:
```c
static enum keypoint_live_data_icon latest_icon = KEYPOINT_LIVE_DATA_ICON_NONE;
static char latest_lines[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1];
static bool latest_has_data;
static int64_t latest_update_ms;
```
with:
```c
/* Page navigation: left key (pos 32) = NEXT, right key (pos 33) = PREV. Defer
 * only on the FN layer, where these keys are &msc SCRL_*; page on every other
 * layer so the 700ms POINTING temp-layer and held LOWER/SYMBOL don't dead-zone. */
#define KEYPOINT_LIVE_PAGE_NEXT_POS 32
#define KEYPOINT_LIVE_PAGE_PREV_POS 33
#define KEYPOINT_FN_LAYER 3 /* matches FN in config/keypoint.keymap */

struct live_data_slot {
    enum keypoint_live_data_icon icon;
    char lines[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1];
    bool has_data;
    int64_t update_ms;
};

static struct live_data_slot deck[KEYPOINT_LIVE_DATA_PAGE_MAX];
static uint8_t deck_total;  /* number of valid pages; 0 until first frame */
static uint8_t view_index;  /* page currently shown */
```

- [ ] **Step 3: Rewrite `keypoint_live_data_parse` for IDX/TOTAL**

Replace the function body (lines 84-134) with one that reads the two leading numeric fields, then icon, then 6 lines:
```c
int keypoint_live_data_parse(const uint8_t *data, uint16_t len, uint8_t *idx, uint8_t *total,
                             enum keypoint_live_data_icon *icon,
                             char out[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT]
                                     [KEYPOINT_LIVE_DATA_LINE_MAX + 1]) {
    if (data == NULL || idx == NULL || total == NULL || icon == NULL || out == NULL ||
        len > KEYPOINT_LIVE_DATA_FRAME_MAX) {
        return -EINVAL;
    }

    const size_t prefix_len = sizeof(KEYPOINT_LIVE_DATA_PREFIX) - 1;
    if (len < prefix_len || memcmp(data, KEYPOINT_LIVE_DATA_PREFIX, prefix_len) != 0) {
        return -EINVAL;
    }

    char icon_field[KEYPOINT_LIVE_DATA_ICON_MAX + 1] = {};
    memset(out, 0, KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT * (KEYPOINT_LIVE_DATA_LINE_MAX + 1));

    /* Field layout after the prefix: 0=IDX, 1=TOTAL, 2=ICON, 3..8=lines. */
    uint16_t idx_val = 0, total_val = 0;
    size_t field = 0;
    size_t column = 0;

    for (size_t i = prefix_len; i < len; i++) {
        const uint8_t ch = data[i];

        if (ch == '|') {
            if (field >= 2 + KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT) {
                return -EINVAL;
            }
            field++;
            column = 0;
            continue;
        }

        if (field == 0 || field == 1) {
            if (ch < '0' || ch > '9' || column >= KEYPOINT_LIVE_DATA_PAGE_FIELD_MAX) {
                return -EINVAL;
            }
            uint16_t *acc = (field == 0) ? &idx_val : &total_val;
            *acc = (uint16_t)(*acc * 10 + (ch - '0'));
            column++;
            continue;
        }

        const size_t field_max =
            (field == 2) ? KEYPOINT_LIVE_DATA_ICON_MAX : KEYPOINT_LIVE_DATA_LINE_MAX;
        if (!is_printable_ascii(ch) || column >= field_max) {
            return -EINVAL;
        }
        if (field == 2) {
            icon_field[column++] = (char)ch;
        } else {
            out[field - 3][column++] = (char)ch;
        }
    }

    if (field != 2 + KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT) {
        return -EINVAL;
    }
    if (total_val < 1 || total_val > KEYPOINT_LIVE_DATA_PAGE_MAX || idx_val >= total_val) {
        return -EINVAL;
    }

    *idx = (uint8_t)idx_val;
    *total = (uint8_t)total_val;
    return icon_from_field(icon_field, icon);
}
```

- [ ] **Step 4: Rewrite `keypoint_live_data_snapshot_get` to read the current page**

Replace lines 136-162:
```c
struct keypoint_live_data_snapshot keypoint_live_data_snapshot_get(void) {
    struct keypoint_live_data_snapshot snapshot = {};

    k_mutex_lock(&live_data_mutex, K_FOREVER);

    snapshot.total_pages = deck_total > 0 ? deck_total : 1;
    snapshot.view_index = view_index;
    const struct live_data_slot *slot = (deck_total > 0) ? &deck[view_index] : NULL;

    if (slot != NULL && slot->has_data) {
        snapshot.icon = slot->icon;
        snapshot.has_data = true;
        const int64_t age_ms = k_uptime_get() - slot->update_ms;
        snapshot.stale = age_ms >= KEYPOINT_LIVE_DATA_STALE_MS;
        for (int i = 0; i < KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT; i++) {
            strncpy(snapshot.lines[i], slot->lines[i], KEYPOINT_LIVE_DATA_LINE_MAX);
            snapshot.lines[i][KEYPOINT_LIVE_DATA_LINE_MAX] = '\0';
        }
    }

    k_mutex_unlock(&live_data_mutex);

    if (!snapshot.has_data) {
        snapshot.icon = KEYPOINT_LIVE_DATA_ICON_WARN;
        strcpy(snapshot.lines[0], "NO DATA");
        strcpy(snapshot.lines[1], "WAITING");
    }

    return snapshot;
}
```

- [ ] **Step 5: Update `store_live_data` to write into a deck slot**

Replace `store_live_data` (lines 164-178). New signature takes idx/total:
```c
static void store_live_data(uint8_t idx, uint8_t total, enum keypoint_live_data_icon icon,
                            char lines[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT]
                                      [KEYPOINT_LIVE_DATA_LINE_MAX + 1]) {
    k_mutex_lock(&live_data_mutex, K_FOREVER);

    deck_total = total;
    struct live_data_slot *slot = &deck[idx];
    slot->icon = icon;
    for (int i = 0; i < KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT; i++) {
        strncpy(slot->lines[i], lines[i], KEYPOINT_LIVE_DATA_LINE_MAX);
        slot->lines[i][KEYPOINT_LIVE_DATA_LINE_MAX] = '\0';
    }
    slot->has_data = true;
    slot->update_ms = k_uptime_get();

    if (view_index >= deck_total) {
        view_index = deck_total - 1;
    }

    k_mutex_unlock(&live_data_mutex);
}
```

- [ ] **Step 6: Update the GATT write callback to the new parse signature**

In `write_live_data` (lines 180-204), replace the parse + store block:
```c
    enum keypoint_live_data_icon icon;
    uint8_t idx, total;
    char parsed[KEYPOINT_LIVE_DATA_TEXT_LINE_COUNT][KEYPOINT_LIVE_DATA_LINE_MAX + 1];
    int ret = keypoint_live_data_parse((const uint8_t *)buf, len, &idx, &total, &icon, parsed);
    if (ret < 0) {
        LOG_WRN("Rejected live-data payload len=%u", len);
        return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
    }

    store_live_data(idx, total, icon, parsed);
    k_work_reschedule(&live_data_stale_work, K_MSEC(KEYPOINT_LIVE_DATA_STALE_MS + 1));

    submit_live_data_display_refresh();

    return len;
```

- [ ] **Step 7: Add the page-navigation position listener**

Add near the bottom of the file, before `BT_GATT_SERVICE_DEFINE` (line 206):
```c
static void live_data_page_advance(int delta) {
    bool changed = false;

    k_mutex_lock(&live_data_mutex, K_FOREVER);
    if (deck_total > 1) {
        view_index = (uint8_t)((view_index + deck_total + delta) % deck_total);
        changed = true;
    }
    k_mutex_unlock(&live_data_mutex);

    if (changed) {
        submit_live_data_display_refresh();
    }
}

static int live_data_page_key_listener(const zmk_event_t *eh) {
    const struct zmk_position_state_changed *ev = as_zmk_position_state_changed(eh);
    if (ev == NULL || !ev->state) {
        return ZMK_EV_EVENT_BUBBLE; /* act on press only */
    }
    if (ev->position != KEYPOINT_LIVE_PAGE_NEXT_POS &&
        ev->position != KEYPOINT_LIVE_PAGE_PREV_POS) {
        return ZMK_EV_EVENT_BUBBLE;
    }
    if (zmk_keymap_highest_layer_active() == KEYPOINT_FN_LAYER) {
        return ZMK_EV_EVENT_BUBBLE; /* FN maps these to &msc SCRL_*; defer */
    }

    live_data_page_advance(ev->position == KEYPOINT_LIVE_PAGE_NEXT_POS ? +1 : -1);
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(keypoint_live_data_page_keys, live_data_page_key_listener);
ZMK_SUBSCRIPTION(keypoint_live_data_page_keys, zmk_position_state_changed);
```

- [ ] **Step 8: Sanity-check the contract is still consistent host-side**

Run: `uv run --with pytest --with "pillow>=11.0" pytest tests/ -q`
Expected: PASS (the preview re-derives PREFIX/ICON_MAX/LINE_COUNT/LINE_MAX from this header; unchanged, so still green).

### Task D3: Render the page indicator in firmware `status.c`

**Files:**
- Modify: `config/boards/shields/lpm_view/widgets/status.c`

- [ ] **Step 1: Add the stdio include for snprintf**

After `#include <zephyr/kernel.h>` (line 8), add:
```c
#include <stdio.h>
```

- [ ] **Step 2: Draw the indicator inside `draw_live_data_panel`**

At the end of `draw_live_data_panel` (after the line-drawing loop, ~line 136), add:
```c
    if (snapshot.has_data && snapshot.total_pages > 1) {
        char page_text[8];
        snprintf(page_text, sizeof(page_text), "%u/%u", (unsigned)(snapshot.view_index + 1),
                 (unsigned)snapshot.total_pages);
        lv_canvas_draw_text(canvas, KEYPOINT_LIVE_TEXT_X, KEYPOINT_LIVE_PAGE_Y,
                            KEYPOINT_LIVE_TEXT_WIDTH, label_dsc, page_text);
    }
```
(`draw_live_data_panel` already holds `snapshot` and receives `label_dsc` = the right-aligned `lv_font_unscii_8` descriptor — the same font/alignment the preview uses.)

- [ ] **Step 3: Host-side parity re-check**

Run: `uv run --with pytest --with "pillow>=11.0" pytest tests/ -q`
Expected: PASS

### Task D4: Keymap — left keys become page nav; add guardrails

**Files:**
- Modify: `config/keypoint.keymap:105` (default_layer row 3)
- Modify: `scripts/check_keypoint_bindings.py:37-44`

- [ ] **Step 1: Set base-layer pos 32/33 to `&none`**

In `default_layer` (line 105), the left center-cluster pair currently reads `&mkp LCLK   &mkp MB3` at positions 32 and 33:
```
&kp LSHFT  &kp Z  &kp X  &kp C  &kp V  &kp B  &mkp LCLK  &mkp MB3  &mkp LCLK  &mkp MB3  &kp N  ...
```
Change **positions 32 and 33 only** (the FIRST `&mkp LCLK` and FIRST `&mkp MB3` — the left pair) to `&none`. Positions 34/35 (the right pair) stay `&mkp LCLK  &mkp MB3`:
```
&kp LSHFT  &kp Z  &kp X  &kp C  &kp V  &kp B  &none  &none  &mkp LCLK  &mkp MB3  &kp N  ...
```

- [ ] **Step 2: Add binding guardrails**

In `scripts/check_keypoint_bindings.py`, add to `EXPECTED_DEFAULT_BINDINGS` (lines 37-44):
```python
    32: "&none",  # left center-cluster: live-data NEXT page (driven by listener)
    33: "&none",  # left center-cluster: live-data PREV page (driven by listener)
```

- [ ] **Step 3: Run the binding checker**

Run: `uv run scripts/check_keypoint_bindings.py && echo OK`
Expected: `OK` (no assertion output).

- [ ] **Step 4: Run the full suite (binding checker is also covered by tests)**

Run: `uv run --with pytest --with "pillow>=11.0" pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit the firmware + keymap phase**

```bash
git add config/boards/shields/lpm_view/widgets/live_data.h \
        config/boards/shields/lpm_view/widgets/live_data.c \
        config/boards/shields/lpm_view/widgets/status.c \
        config/keypoint.keymap scripts/check_keypoint_bindings.py
git commit -m "feat(live_data): firmware-side page deck + left-key navigation + indicator"
```

> **Firmware verification (not local):** push the branch; let GitHub Actions build the `left`/`right` artifacts. Then HIL-flash and confirm: a ≥2-card deck shows the indicator; left key advances + wraps; right key goes back + wraps; FN-layer scroll on these keys still scrolls; a producer re-push preserves `view_index`; a single-card deck hides the indicator and ignores nav.

### Phase E — rcink producer

### Task E1: Producer renders IDX/TOTAL and pushes the whole deck

**Files:**
- Modify: `~/w/_hw/rcink/producer/rcink/keypoint.py` (`PREFIX`/`FRAME_MAX_BYTES` lines 28-32; `render_frame` lines 107-124; `frames_to_push` lines 176-180)
- Test: `~/w/_hw/rcink/producer/tests/test_keypoint.py`

- [ ] **Step 1: Write failing tests for the new producer grammar**

Add to `tests/test_keypoint.py`:
```python
def test_render_frame_carries_idx_total():
    fields = render_frame(make_card(), now=NOW, index=2, total=5).decode("ascii").split("|")
    assert fields[0] == "KP2"
    assert (fields[1], fields[2]) == ("2", "5")
    assert fields[3] == "CLAUDE"  # icon now after IDX/TOTAL
    assert fields[4] == "CLAUDE  "  # L1 title
    assert len(render_frame(make_card(), now=NOW, index=0, total=1)) <= 70


def test_frames_to_push_stamps_index_and_total(cache):
    write_card(make_card(id="claude"))
    write_card(make_card(id="codex", icon="CODEX", title="CODEX"))
    frames = frames_to_push(now=NOW, max_age_s=6 * 3600)
    parsed = [f.decode("ascii").split("|") for f in frames]
    assert [(p[1], p[2], p[3]) for p in parsed] == [("0", "2", "CLAUDE"), ("1", "2", "CODEX")]
```
Also update the existing field-index assertions in `test_render_frame_layout`, `test_render_frame_l3_is_data_ts_not_now`, `test_render_frame_pads_missing_rows_with_empty_lines`, and `test_frames_to_push_*`: every `render_frame(card, now=NOW)` call gains `index=0, total=1` (or the right values), and field indices shift by **+2** (icon moves from `fields[1]`→`fields[3]`, L1 `fields[2]`→`fields[4]`, … L6 `fields[7]`→`fields[9]`); the `<= 66` assertion becomes `<= 70`; `len(fields) == 8` becomes `len(fields) == 10`.

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd ~/w/_hw/rcink/producer && uv run pytest tests/test_keypoint.py -q`
Expected: FAIL (render_frame has no `index`/`total` kwargs; field indices off).

- [ ] **Step 3: Update constants**

`rcink/keypoint.py` lines 28-32 — add a page cap and grow the byte budget:
```python
PREFIX = "KP2"
TEXT_LINE_COUNT = 6
LINE_MAX = 8
MAX_ROWS = 4  # rows[0] -> L2, rows[1:4] -> L4..L6
PAGE_MAX = 8
FRAME_MAX_BYTES = 70
```

- [ ] **Step 4: Update `render_frame` to take + emit IDX/TOTAL**

Lines 107-124 — change the signature and the frame join:
```python
def render_frame(card: Card, *, now: dt.datetime, index: int, total: int) -> bytes:
    """Render a card to one full-screen KP2 frame: KP2|IDX|TOTAL|ICON|L1..L6,
    computing countdowns at render time and stamping L3 with the data timestamp."""
    if not (1 <= total <= PAGE_MAX):
        raise ValueError(f"total {total} out of range 1..{PAGE_MAX}")
    if not (0 <= index < total):
        raise ValueError(f"index {index} out of range for total {total}")
    if card.icon not in ICON_IDS:
        raise ValueError(f"unsupported icon {card.icon!r}; expected one of: {', '.join(sorted(ICON_IDS))}")
    if not 1 <= len(card.rows) <= MAX_ROWS:
        raise ValueError(f"card {card.id!r}: expected 1..{MAX_ROWS} rows, got {len(card.rows)}")

    now_ts = int(now.timestamp())
    rendered = [_render_row(r, now_ts=now_ts) for r in card.rows]
    rendered += [""] * (MAX_ROWS - len(rendered))
    data_time = dt.datetime.fromtimestamp(card.data_ts, tz=now.tzinfo).strftime("%H:%M")
    lines = [title(card.title), rendered[0], data_time, *rendered[1:]]

    frame = "|".join(
        [PREFIX, str(index), str(total), card.icon, *(_validate_line(line) for line in lines)]
    ).encode("ascii")
    if len(frame) > FRAME_MAX_BYTES:
        raise ValueError(f"frame is {len(frame)} bytes, max {FRAME_MAX_BYTES}")
    return frame
```

- [ ] **Step 5: Update `write_card`'s render dry-run + `frames_to_push`**

`write_card` (line 134) currently calls `render_frame(card, now=...)`; give it page args:
```python
    render_frame(card, now=dt.datetime.now().astimezone(), index=0, total=1)
```
`frames_to_push` (lines 176-180):
```python
def frames_to_push(*, now: dt.datetime, max_age_s: int) -> list[bytes]:
    """Load the cache, drop stale cards, and render the whole deck — each card
    stamped with its page index and the deck total (capped at PAGE_MAX)."""
    cards = fresh_cards(load_cards(), now=now, max_age_s=max_age_s)[:PAGE_MAX]
    total = len(cards)
    return [render_frame(card, now=now, index=i, total=total) for i, card in enumerate(cards)]
```

- [ ] **Step 6: Run tests, verify they pass**

Run: `cd ~/w/_hw/rcink/producer && uv run pytest tests/test_keypoint.py -q`
Expected: PASS

### Task E2: Pusher writes the whole deck (no dwell rotation)

**Files:**
- Modify: `~/w/_hw/rcink/producer/scripts/keypoint_push.py` (`_push` lines 72-86; the `dwell` option lines 93)

- [ ] **Step 1: Push every frame back-to-back in one connection**

Replace the write loop in `_push` (lines 80-86):
```python
    target = await _resolve_device(name=name, address=address, scan_timeout=scan_timeout)
    async with BleakClient(target, services=[SERVICE_UUID]) as client:
        for frame in frames:
            await client.write_gatt_char(CHAR_UUID, frame, response=False)
            logger.info(f"pushed {frame.decode('ascii')}")
            await asyncio.sleep(pace)  # brief pacing for write-without-response reliability
    logger.success(f"pushed deck: {len(frames)} card(s)")
```

- [ ] **Step 2: Replace the `dwell` option with a small `pace`**

In `run` (line 93), replace the `dwell` option:
```python
    pace: float = typer.Option(0.1, min=0.0, help="Seconds between back-to-back deck writes."),
```
and update the `_push(...)` call + `_push` signature to pass `pace` instead of `dwell` (the firmware now owns paging; the producer just refreshes all slots each cycle). Update the module docstring's "rotation"/"dwell" wording to "pushes the whole deck each cycle; the firmware owns page navigation."

- [ ] **Step 3: Run the producer suite**

Run: `cd ~/w/_hw/rcink/producer && uv run pytest -q`
Expected: PASS

- [ ] **Step 4: Commit the producer changes**

```bash
cd ~/w/_hw/rcink
git add producer/rcink/keypoint.py producer/scripts/keypoint_push.py producer/tests/test_keypoint.py
git commit -m "feat(keypoint): push whole deck with IDX/TOTAL frames (firmware owns paging)"
```

---

## Final verification

- [ ] **This repo Python suite green:** `uv run --with pytest --with "pillow>=11.0" pytest tests/ -q`
- [ ] **Binding checker green:** `uv run scripts/check_keypoint_bindings.py && echo OK`
- [ ] **Producer suite green:** `cd ~/w/_hw/rcink/producer && uv run pytest -q`
- [ ] **Render check:** `uv run scripts/preview_keypoint_status.py --frame 'KP2|1|3|CLAUDE|CLAUDE  |5H   76%|14:30|WK   88%|RST  90M|OP   18%'` shows `2/3`.
- [ ] **Firmware build:** push branch; GitHub Actions builds `left.uf2` / `right.uf2` without error.
- [ ] **HIL (zmk-config):** flash both halves; verify Part 1 (TAB scroll) and Part 2 (deck indicator, left=next/right=prev, wrap, FN-scroll preserved, view_index survives re-push, single-card hides indicator).
- [ ] **HIL (end-to-end):** run `cd ~/w/_hw/rcink/producer && uv run keypoint-push` and confirm the real deck appears and pages with the left keys.

## Spec coverage check

- Part 1 BSPC→TAB → Task A1. RSHFT side-effect documented in the driver comment.
- New `KP2|IDX|TOTAL|...` grammar → Tasks B2, C1, D1, D2, E1 (all 7 mirror-points: firmware parse D2, firmware frame-max D1, producer render/FRAME_MAX E1, demo C1, preview B2, this-repo tests B3, producer tests E1).
- Firmware deck + per-slot staleness + clamp → Task D2.
- Page-nav listener, FN-gated, pos32=NEXT/pos33=PREV, wrap → Task D2.
- Keymap `&none` + guardrails → Task D4.
- `2/5` indicator (constant B1, preview B2, firmware D3) → covered.
- MAX_PAGES=8 → D1 (firmware), E1 (producer cap).
- Producer pushes whole deck (no dwell) → Task E2.
