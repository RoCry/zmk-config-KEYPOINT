# CONTEXT.md — KEYPOINT domain glossary

Authority chain: `config/boards/shields/lpm_view/widgets/live_data.h` (constants, enums, snapshot) + `live_data_core.c` (parse, deck staging, staleness) define the KP4 contract; Python tooling and external producers derive/import it. Docs describe current values; executable consumers must not redeclare them.

## Wire / protocol

- **KP4 frame** — `KP4|GEN|IDX|TOTAL|ICON|LED|ROLES|L1..L6`, printable ASCII, ≤88 bytes, delivered as one encrypted BLE GATT write. KP3 and older frames are rejected.
- **Card** — one page of live data: title line (L1, contrasting text on a filled bar) + 5 content lines + corresponding row roles + icon + LED hint.
- **Deck** — the set of `TOTAL` cards sharing one generation. Staged page-by-page; committed atomically only when every page of the generation has arrived.
- **Generation (GEN)** — two-uppercase-hex-digit deck transaction id. All pages must arrive before replacing the committed deck, including when reusing a generation id.
- **Page (IDX/TOTAL)** — a card's position in its deck, `0 <= IDX < TOTAL <= 8`. Navigation wraps.
- **Usage card** — rate-limit page: countdown row and consumed-quota bar per available window, then optional scoped limit. CLAUDE has 5H/7D; CODEX may have only one weekly window. `kp4.usage_card` builds the common two-window shape; producer owns thresholds and row meanings.
- **Scoped limit** — a per-model rate limit inside a plan (e.g. Fable at 68%), shown as one short `TAG NN%` row on a usage card's last line. The card has room for one, so the producer picks which (rcink sends the highest); a plan without any leaves the line empty.
- **Producer** — external host program building decks and writing frames. Reference producer: rcink (`~/w/_hw/rcink/producer/rcink/keypoint.py`).
- **Row role (ROLES)** — six codes aligned with L1..L6: neutral `0`, positive `1`, attention `2`, warning `3`, error `4`. Producer declares meaning; firmware maps it to a color/style. Independent of the card's LED hint.
- **kp4 contract module** — `scripts/kp4.py`: firmware-derived constants/enums plus parser/validator/builders. `kp4_contract.json` supplies the same contract to vendored copies without the firmware tree.

## Firmware state

- **Snapshot** — LiveData's read model: current card/row roles + `has_data` / `stale` / generation / view index / total. The only thing consumers may read.
- **Staleness** — current committed card's frame age reaches `KEYPOINT_LIVE_DATA_STALE_MS` (6 min). Last content and roles remain visible; segmented health strip and LED signal staleness.
- **LED hint** — producer-declared severity for a card: none / active / attention / warning / error.
- **Attention level** — the single computed LED semantic LiveData exposes (folds LED hint + staleness + icon-specific emphasis). LED hardware modules render attention levels; they hold no opinion about icons or staleness.

## Display

- **Panel palette** — the eight physical colors: black, blue, green, cyan, red, magenta, yellow and white.
- **Theme** — firmware mapping of row roles, card identity and keyboard state to panel colors and readable text/background pairs. Business thresholds belong to producer.
- **Glass** — the physical LCD area: 72×144 native pixels. A 72×72 canvas covers one section, not the whole panel.
- **Logical display** — LVGL/Zephyr landscape surface, 144×72 pixels; driver maps it onto native portrait glass.
- **Canvas** — 72×72 LVGL draw surface (top / middle); exact in-place −90° rotation, then composition onto logical display. No resampling artifact or scratch buffer.
- **Native preview** — `scripts/build_preview.py` builds pinned LVGL 8.3.7 plus the shared C renderer/theme/rotation/panel core; `scripts/preview_keypoint_status.py` produces glass PNGs through that library. No duplicate Python UI simulation; physical panel behavior still needs device acceptance.
- **Panel conversion** — RGB565 render pixels become RGB111 by half-range channel thresholds, then compact 27-byte native rows. Driver sends changed rows at 1 MHz; full-frame LVGL VDB prevents stripe amplification.
- **Image asset** — eight-color export uses LVGL indexed 4-bit pixels and palette; source quantization optionally uses Floyd–Steinberg dithering. `scripts/preview_lpm_image.py` exports and previews assets.
- **Derived seam** — tooling derives wire values from C; native preview compiles the actual C drawing code. Consumers share authority instead of duplicating implementations.

## Input

- **Motion shaping** — pure math turning device deltas into cursor movement and scroll ticks: residual accumulation, speed-stepped scroll gain. One module shared by both pointing drivers. (Arrow mode — TrackPoint deltas as arrow-key repeats — was removed: its mode key was a bare `&kp`, so holding it typed the letter.)
- **Speed preference** — the user's cursor-speed setting, a named input to motion shaping. (Historically smuggled through trackpad/trackpoint LED brightness getters.)
- **Mode key** — a held key that changes what a pointing device's motion means. Must be a layer-tap or `&none`: held, it may send *nothing* to the host. A mod-tap here leaks its modifier for the whole gesture.
- **Scroll gesture** — hold a mode key, move a pointing device, scroll. The trackpad decides this in its own driver off a raw key position; the TrackPoint's decision is made on the central half by `trackpoint_listener`, gated on the LOWER layer. Same gesture, two mechanisms, because the TrackPoint's driver runs on the peripheral and only ever reports cursor motion.
- **Wheel axis polarity** — `REL_X` and `HWHEEL` are both positive-right, but `REL_Y` is positive-*down* while `WHEEL` is positive-*up*. So turning cursor motion into scrolling always costs one Y negation and never an X one. Both devices pay it: the trackpad in its driver (`INPUT_REL_WHEEL, -ticks.y`), the TrackPoint via `zip_scroll_transform INPUT_TRANSFORM_Y_INVERT`. Skip it and that device scrolls backwards and disagrees with the other one — with no other symptom.
- **POINTING layer** — raised for 700 ms by any TrackPoint motion (`zip_temp_layer`), not by any key. It turns the right thumb keys into mouse buttons while you are pointing.
- **Layer-number seam** — layer indices are positional in the keymap, but `zitaotech_keypoint_left.dts` restates two of them as macros to wire the listener. Neither file can see the other and a mismatch still builds; `tests/test_pointing_layers.py` derives the real indices and holds both files to them.
