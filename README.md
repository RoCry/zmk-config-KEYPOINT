# zmk-config-KEYPOINT

ZMK config for the ZitaoTech KEYPOINT split keyboard.

## Current Features

- Left display LiveData service: encrypted BLE write characteristic for compact status cards.
- Eight-color LPM009M360A displays: RGB565 rendering, RGB111 panel output; firmware owns palette and styles.
- KP4 deck protocol: generation, page index/total, icon, LED hint, six row roles and six 9-char text lines.
- Trackpad LED status patterns: touch/backlight preview, USB transport confirmation, LiveData generation confirmation, stale/no-data/error/warning/attention pulses.
- A320 trackpad: interrupt-driven I2C read path, scroll/cursor modes, touch state exposed to the LED driver.
- TrackPoint: cursor only on the right half; scrolling is a layer decision made on the central half.

CapsLock LED animation was intentionally removed. This config treats the trackpad LED as a system/status light, not a HID indicator.

## Pointing

Two devices, two different places the scroll decision gets made.

The **trackpad** (left, central) scrolls by default and moves the cursor while an inner thumb key is held — `CONFIG_A320_START_IN_SCROLL_MODE=y` picks which way round that is. The driver watches the raw key position, so the mode key works on any layer.

The **TrackPoint** (right, peripheral) only ever reports cursor motion. Its scroll gesture is owned by `trackpoint_listener` on the left board: while the LOWER layer is active, an input processor remaps its X/Y onto the wheel axes and inverts Y. Hold either LOWER layer-tap — the left thumb `SPACE` or the bottom-row `LEFT` — and push the TrackPoint.

That Y inversion is a fixed axis convention, not a taste setting: `REL_X` and `HWHEEL` are both positive-right, but `REL_Y` is positive-down while `WHEEL` is positive-up. Every cursor→scroll conversion owes exactly one Y negation. The trackpad pays it in its driver; the TrackPoint pays it with `zip_scroll_transform`. Whether scrolling then feels "natural" is the host's business — macOS applies its own inversion on top, system-wide — so the firmware's only job is to keep the two halves agreeing with each other.

Both mode keys are **layer-taps on purpose**. A layer-tap held sends nothing to the host; a mod-tap held sends a modifier, and a Shift leaking out mid-gesture turns vertical scrolling into horizontal scrolling on macOS. Any future pointing modifier belongs on a layer-tap or a `&none`, never on a `&mt`.

Any TrackPoint motion also raises the POINTING layer for 700 ms, where the two right thumb keys become left and right click.

Those layer numbers live in two files that cannot see each other — `config/keypoint.keymap` and `zitaotech_keypoint_left.dts` — and a mismatch fails no build, it just silently kills the gesture. `tests/test_pointing_layers.py` is what holds them together.

## Display

Native glass: **72×144** portrait pixels; Zephyr/LVGL logical display: **144×72**. Both screens use explicitly opaque black surfaces. Left: white body text, colored titles and thin quota bars with percentages, page dots, unboxed profile numbers and a small freshness mark. Two contiguous canvases cover all 144 rows. Canvas rotation uses an exact in-place 90° permutation for RGB565 and RGB565+alpha pixels.

Right: native 72×144 fullscreen photos, with one 18px black status strip overlaid across the top. Image pixels below the strip remain unchanged; no padding, stretching or uncovered bottom edge. The four-image gallery advances every 60 seconds on the LVGL thread. Legacy non-fullscreen images were removed.

LVGL renders RGB565; the driver thresholds each channel into the eight RGB111 colors (black, blue, green, cyan, red, magenta, yellow, white), packs 27 bytes per native row and sends compact RGB at **1 MHz**. Changed rows are tracked; failed transactions retain dirty rows for retry. `LV_Z_VDB_SIZE=100` keeps a full-frame draw buffer, avoiding repeated native-row writes from rotated horizontal stripes.

Host previews establish software rendering, not physical color appearance, wiring, COM inversion, cold-start/wake behavior or power consumption. See the [eight-color validation record](docs/research/2026-10-23-eight-color-validation.md) for build evidence and outstanding physical checks.

## Firmware delivery

Push to `main`, then open [Build ZMK firmware in Actions](https://github.com/RoCry/zmk-config-KEYPOINT/actions/workflows/main.yml). Select the successful run for the intended commit and download its firmware artifact. Extract `left.uf2` and `right.uf2`; manually enter each half's UF2 bootloader and copy the matching file to its mounted drive. The `left-reset` and `right-reset` images clear settings and are not the normal upgrade images.

For this KP4 upgrade, update both halves before resuming the producer. Reconnect BLE, verify an acknowledged KP4 deck, then restore scheduled sending using the producer rollout guide below. Physical eight-color acceptance follows the manual upgrade.

## LiveData KP4 Contract

GATT service/characteristic:

- Service: `f5d40000-6d2f-4f4b-9b2a-2f4a8e8c0001`
- Characteristic: `f5d40001-6d2f-4f4b-9b2a-2f4a8e8c0001`
- Permission: encrypted write

Frame:

```text
KP4|GEN|IDX|TOTAL|ICON|LED|ROLES|L1|L2|L3|L4|L5|L6
```

- `GEN`: exactly two uppercase hex digits. New deck transaction id.
- `IDX`: decimal page index, `0 <= IDX < TOTAL`.
- `TOTAL`: decimal deck size, `1..8`.
- `ICON`: one of firmware `KEYPOINT_LIVE_DATA_ICON_*` ids, including `CLAUDE` and `CODEX`.
- `LED`: `0` none, `1` active, `2` attention, `3` warning, `4` error.
- `ROLES`: exactly six single-digit codes, one per `L1..L6`: `0` neutral, `1` positive, `2` attention, `3` warning, `4` error. Roles express meaning; firmware chooses colors. They do not change LED hints.
- `L1..L6`: printable ASCII, max 9 chars each, `|` not allowed. A full 9-char line fills the 72px glass edge to edge (monospace 8px glyphs).
- Max frame size: 88 bytes. `[NNN]` lines, `000..100`, render as progress bars.

Firmware stages KP4 pages by `(GEN, TOTAL)` and only commits the visible deck after every page in that generation has arrived. Rows and roles commit together. KP3 and older frames are rejected.

`widgets/live_data.h` and `live_data_core.c` under `config/boards/shields/lpm_view/` own the contract. `scripts/kp4.py` derives constants/enums and provides the tooling parser/builders; `kp4_contract.json` is its frozen producer copy. Preview, demo sender, diagnose probe and tests use this module.

Producer reference: `~/w/_hw/rcink/producer/rcink/keypoint.py`; upgrade producer and firmware together. Rollout guide: `~/w/_hw/rcink/producer/docs/keypoint-kp4.md`. Its launchd sender runs directly from the working tree every 60 seconds when loaded. The KP4 upgrade was confirmed by acknowledged writes and a user photo; scheduled sending has resumed. The dark UI revision keeps the same protocol.

## Local Checks

```bash
just test
just preview
```

Requires `uv`, `cmake` and `ninja`. `scripts/build_preview.py` downloads checksum-pinned LVGL 8.3.7 and builds the firmware's shared drawing, object composition, gallery, rotation and panel mapping into a native library. `scripts/preview_keypoint_status.py` emits left UI and every right gallery image as RGB PNGs to `tmp/status-preview/`. Actual LVGL flush output includes parent backgrounds and image overlays; no separate Python drawing simulation.

Preview one frame after building the native library:

```bash
uv run scripts/preview_keypoint_status.py --frame 'KP4|A0|0|1|CLAUDE|2|002021|CLAUDE   |5H  1h30m|[076]|7D     4d|[088]|FB 68%'
```

## Image conversion

`scripts/preview_lpm_image.py` quantizes source RGB images to the same eight-color palette. Firmware export uses `LV_IMG_CF_INDEXED_4BIT`: eight palette entries plus padding for the 16-entry LVGL table, two pixels per byte. Export defaults to **no dithering**, matching the user's selected D style for all four photos. `--dither` explicitly enables Floyd–Steinberg; preview contact sheets show both for comparison.

Example Al Pacino regeneration from a retained original image:

```bash
uv run scripts/preview_lpm_image.py --input /path/to/al_pacino.jpg --stem al_pacino --firmware-c-out config/boards/shields/lpm_view/widgets/picture/al_pacino.c --firmware-symbol al_pacino
uv run scripts/preview_lpm_image.py --c-input config/boards/shields/lpm_view/widgets/picture/al_pacino.c --c-preview-out tmp/al_pacino.png
```

Defaults: portrait crop 72×144, `crop_face` framing, focus `(0.5, 0.38)`, counterclockwise rotation to logical 144×72. `--input` also accepts `host:/abs/path`; decoding supports indexed 1/2/4-bit assets. Use `--help` for crop, size, rotation and output options. Gallery assets record source basename/hash, crop parameters and quantization; originals stay outside git. Regression fixtures freeze the exact user-approved D preview pixels.
