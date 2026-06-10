# KEYPOINT: TAB scroll-trigger + Live-Data Page Navigation

Date: 2026-06-10

> Historical design note. Current firmware uses the KP3 deck protocol
> (`KP3|GEN|IDX|TOTAL|ICON|LED|L1|..|L6`, 75 bytes max); see `README.md`.
> KP2 paging details below are retained only as implementation history.

Two independent keymap-ergonomics changes requested together.

1. **Right hand** — the trackpoint "hold-to-scroll" modifier moves from the
   right-thumb **BSPC** key to the right-thumb **TAB** key.
2. **Left hand** — the two left center-cluster keys (`&mkp LCLK` / `&mkp MB3`)
   become **next / previous page** controls for the live-data display, which
   gains a firmware-side multi-card deck.

---

## Part 1 — Scroll trigger: BSPC → TAB

### Current behavior

The custom TrackPoint driver
(`config/boards/shields/right_trackpoint_keypoint/custom_driver_right/trackpoint_0x15.c`)
runs a global `zmk_position_state_changed` listener. Holding **key position 49**
(`&lt SYMBOL BSPC`, right thumb) sets `scroll_key_pressed`, which switches
trackpoint motion from cursor to scroll. Positions 20 (arrow mode) and 22 (slow
mode) are separate, unrelated features.

### Change

Move the scroll trigger to **key position 50** (`&mt RSHFT TAB`, the right-thumb
TAB immediately right of BSPC).

- Single edit at `trackpoint_0x15.c:122`: `ev->position == 49` → `== 50`.
- Fix the stale log/comment (`"space position=49"` → scroll key, position 50).
- No keymap change. Positions 20 and 22 are untouched.

### Known trade-off (accepted)

Position 50 is a mod-tap (`&mt RSHFT TAB`): **holding it to scroll also engages
Right-Shift**, which some hosts interpret as horizontal scroll. The previous
BSPC key held the SYMBOL *layer* (host-invisible); RSHFT is host-visible. The
user explicitly chose TAB with this trade-off understood. If undesirable later,
the fallback is a dedicated non-modifier TAB key position.

### Verification

Firmware-only behavioral change with no host-side simulator. Verified by CI
build of the `right` artifact and a HIL flash + scroll test (hold right-thumb
TAB, move trackpoint → scroll; tap TAB → still types Tab; BSPC no longer
scrolls).

---

## Part 2 — Live-data page navigation (firmware-side deck)

### Current architecture

- **Firmware** (`config/boards/shields/lpm_view/widgets/live_data.{c,h}`,
  compiled central-only): a custom BLE GATT service receives one ASCII frame
  `KP2|ICON|L1|L2|L3|L4|L5|L6` (icon + six 8-char lines) and stores it as a
  **single** `latest_*` snapshot. `status.c` renders it across two canvases
  (lines 1–3 top, lines 4–6 + health strip middle).
- **Producer** (`~/w/_hw/rcink/producer`): fetchers drop one card per source
  into a cache dir; `keypoint_push.py` (launchd, ~1/min) loads fresh cards and
  **rotates** them — writing each frame sequentially with a 12 s dwell, so the
  single-card firmware shows a slideshow.

The LEFT half is the split **central** (`Kconfig.defconfig`:
`ZMK_SPLIT_ROLE_CENTRAL default y` for `BOARD_ZITAOTECH_KEYPOINT_LEFT`). It runs
the keymap, raises `position_state_changed` for **all** positions (both halves),
hosts the live-data BLE service, and drives the display — so left-hand keys and
the deck logic live on the same core.

### New architecture

Move pagination from a producer-driven time rotation to a **firmware-side deck**
with **local, instant** key navigation:

- The producer pushes the **whole deck** each cycle (each card stamped with its
  page index and the deck total), instead of dwell-rotating one card at a time.
- The firmware stores all pages and shows one at a time.
- The two left keys flip the displayed page locally (wrap-around), with no
  back-channel and no persistent producer connection.

### Wire protocol (no backward compatibility)

```
old:  KP2|ICON|L1|L2|L3|L4|L5|L6
new:  KP2|IDX|TOTAL|ICON|L1|L2|L3|L4|L5|L6
```

- `IDX`  — 0-based page index of this card, `0 .. TOTAL-1`.
- `TOTAL` — number of pages in the current deck, `1 .. MAX_PAGES`.
- `MAX_PAGES = 8` (single decimal digit; generous vs. today's 2 cards).
- Remainder (icon + six 8-char lines, `0x20..0x7E`, no `|`) is unchanged.
- Frame max grows from 66 → **70 bytes** (`+IDX +TOTAL +2` separators, each
  field a single digit). Within the negotiated MTU (66-byte writes work today);
  confirmed at HIL.
- Malformed/out-of-range frames are rejected whole (fail-fast); firmware keeps
  its last good deck.

### Firmware changes

`live_data.h`
- Replace the single-snapshot constants with a deck:
  - `KEYPOINT_LIVE_DATA_PAGE_MAX 8`
  - extend the frame-max macro by `IDX(1) + TOTAL(1) + 2` separators → 70.
- Extend `struct keypoint_live_data_snapshot` with `uint8_t view_index` and
  `uint8_t total_pages` so the renderer can draw the indicator.

`live_data.c`
- Storage: `static struct { enum icon; char lines[6][9]; bool has_data;
  int64_t update_ms; } deck[PAGE_MAX];` plus `uint8_t deck_total` and
  `uint8_t view_index`.
- Parser: read `IDX` and `TOTAL` before the icon; validate ranges
  (`TOTAL` in `1..PAGE_MAX`, `IDX` in `0..TOTAL-1`).
- On valid write: store `deck[IDX]`, set `deck_total = TOTAL`, clamp
  `view_index` to `< deck_total`, stamp `deck[IDX].update_ms`, refresh display.
  Per-page staleness keeps the existing 360 s rule (`KEYPOINT_LIVE_DATA_STALE_MS`),
  evaluated per slot.
- `keypoint_live_data_snapshot_get()` returns `deck[view_index]` plus
  `view_index` / `deck_total`. Empty in-range slot (frame not yet arrived) shows
  the existing `NO DATA / WAITING` card for that page.
- **Page-nav listener**: a `zmk_position_state_changed` subscription (mirroring
  the TrackPoint driver pattern) watching key positions **32** (NEXT) and **33**
  (PREV). On press:
  - **Gate**: act only when the FN layer is **not** the highest active layer
    (`zmk_keymap_highest_layer_active() != FN`, FN = layer 3). FN maps 32/33 to
    `&msc SCRL_*`; deferring only on FN avoids dead-zones from the 700 ms
    POINTING temp-layer and held LOWER/SYMBOL while preserving FN scroll.
  - NEXT: `view_index = (view_index + 1) % deck_total`.
  - PREV: `view_index = (view_index + deck_total - 1) % deck_total`.
  - No-op when `deck_total <= 1`. Submit a display refresh after a change.

`status.c` / `status_layout.h`
- Page indicator: render a compact `n/N` (1-based, e.g. `2/5`) using
  `lv_font_unscii_8`, right-aligned in the free band between the status row and
  the first live-data line (~`y=14`, x within the `3..70` text region) on the
  top canvas. Shown only when `total_pages > 1` and data is present.
- Exact pixel placement is finalized against the host-side simulator
  (`scripts/preview_keypoint_status.py`), which is pixel-exact for the 1-bpp
  left screen.

### Keymap change (`config/keypoint.keymap`)

- Base (`default_layer`) positions 32/33: `&mkp LCLK` / `&mkp MB3` → **`&none`**
  (suppresses the mouse click; the listener performs paging — the
  `position_state_changed` event still fires for `&none`).
- Other layers untouched: FN keeps `&msc SCRL_DOWN/UP` on 32/33; LOWER / SYMBOL /
  POINTING keep `&trans` (now falling through to base `&none`).
- `scripts/check_keypoint_bindings.py`: add `default_layer[32] = "&none"` and
  `default_layer[33] = "&none"` as guardrails.

### Producer changes (`~/w/_hw/rcink/producer`)

`rcink/keypoint.py`
- `render_frame(card, *, now, index, total)`: emit
  `KP2|IDX|TOTAL|ICON|...`; bump `FRAME_MAX_BYTES` 66 → 70; add a
  `PAGE_MAX = 8` cap.
- `frames_to_push(...)`: total = number of fresh cards (capped at `PAGE_MAX`);
  render each with its index/total.

`scripts/keypoint_push.py`
- Push the **whole deck** in one connection — write all frames back-to-back
  (small inter-write pacing for write-without-response reliability), then exit.
  Remove the 12 s dwell rotation. Re-running each minute idempotently refreshes
  all slots and live countdowns; the firmware preserves `view_index`.

Producer tests (`producer/tests/test_keypoint.py`): update to the new frame
grammar and the deck push.

### This repo's tooling

- `scripts/send_keypoint_live_demo.py`: emit the new frame; default demo pushes
  a multi-card deck (idx/total stamped).
- `scripts/preview_keypoint_status.py` (`--frame`): parse `IDX|TOTAL` and render
  the indicator; allow previewing a chosen page.
- Tests: `tests/test_live_data_contract.py`,
  `tests/test_keypoint_status_preview.py` — update to the new frame and the
  indicator.

### Protocol mirror-points (keep in lockstep)

The frame grammar appears in seven places; change them together:

1. firmware parse — `live_data.c`
2. firmware frame-max — `live_data.h`
3. producer `render_frame` / `FRAME_MAX_BYTES` — `rcink/keypoint.py`
4. demo sender — `scripts/send_keypoint_live_demo.py`
5. preview `--frame` — `scripts/preview_keypoint_status.py`
6. this repo's tests — `tests/test_live_data_contract.py`,
   `tests/test_keypoint_status_preview.py`
7. producer tests — `producer/tests/test_keypoint.py`

### Verification

- **Producer + this repo's tooling/tests**: local `uv run` pytest in both repos;
  host-side render check via `preview_keypoint_status.py --frame` for the
  indicator and per-page rendering.
- **Firmware**: CI build of the `left` artifact + HIL flash. HIL checks: deck of
  ≥2 cards shows the indicator; left key advances pages and wraps; right key goes
  back and wraps; FN-layer scroll on 32/33 still scrolls; pages survive a
  producer re-push (view_index preserved); single-card deck hides the indicator
  and ignores nav.

### Out of scope

- No back-channel/notify from keyboard to host (deck is producer-pushed).
- No Chinese text (unchanged from v1).
- No change to icons, battery, layer, or profile widgets beyond adding the
  indicator band.
