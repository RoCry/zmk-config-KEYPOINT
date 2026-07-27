# CONTEXT.md — KEYPOINT domain glossary

Authority chain: `config/boards/shields/lpm_view/widgets/live_data.h` (constants, enums, snapshot) + `live_data_core.c` (parse, deck staging, staleness) define the KP3 contract; everything else (Python tooling, tests, docs, external producer) derives from them. Never restate a contract value — derive or import it.

## Wire / protocol

- **KP3 frame** — `KP3|GEN|IDX|TOTAL|ICON|LED|L1..L6`, printable ASCII, ≤81 bytes, delivered as one encrypted BLE GATT write. The wire unit.
- **Card** — one page of live data as shown on the glass: title line (L1, rendered inverted) + 5 body lines + icon + LED hint.
- **Deck** — the set of `TOTAL` cards sharing one generation. Staged page-by-page; committed atomically only when every page of the generation has arrived.
- **Generation (GEN)** — two-hex-digit deck transaction id. A new generation replaces the whole deck; a repeated one updates pages in place.
- **Page (IDX/TOTAL)** — a card's position in its deck, `0 <= IDX < TOTAL <= 8`. Navigation wraps.
- **Usage card** — the rate-limit card shape (`kp3.usage_card`): a countdown row and a utilisation bar per window (5H/7D), then the scoped limit. Both the CLAUDE and CODEX pages are usage cards.
- **Scoped limit** — a per-model rate limit inside a plan (e.g. Fable at 68%), shown as one short `TAG NN%` row on a usage card's last line. The card has room for one, so the producer picks which (rcink sends the highest); a plan without any leaves the line empty.
- **Producer** — external host program building decks and writing frames. Reference producer: rcink (`~/w/_hw/rcink/producer/rcink/keypoint.py`).
- **kp3 contract module** — the single Python authority (`scripts/kp3.py`): constants derived from the firmware header at import, plus the one parser / validator / frame builder every script and test uses.

## Firmware state

- **Snapshot** — LiveData's read model: current card + `has_data` / `stale` / generation / view index / total. The only thing consumers may read.
- **Staleness** — no accepted frame for `KEYPOINT_LIVE_DATA_STALE_MS` (6 min). Shown via health strip + LED.
- **LED hint** — producer-declared severity for a card: none / active / attention / warning / error.
- **Attention level** — the single computed LED semantic LiveData exposes (folds LED hint + staleness + icon-specific emphasis). LED hardware modules render attention levels; they hold no opinion about icons or staleness.

## Display

- **Glass** — the physical 72×72 visible LCD area.
- **Canvas** — an LVGL draw surface (top / middle); rotated −90° and composed onto the glass. Canvas↔glass mapping (including the row/col-36 rotation artifact) is owned by the LVGL sim's `glass` interface.
- **Sim** — `scripts/keypoint_lvgl_sim.py`, a from-scratch reimplementation of the LVGL 8.3 1-bit render paths the firmware uses. Preview fidelity rests on it.
- **Derived seam** — Python parsing C source at import time (constants, icon bitmaps, layout tables) so values cannot drift. The preferred sync mechanism; substring-grep assertions are its deprecated predecessor.

## Input

- **Motion shaping** — pure math turning device deltas into cursor movement and scroll ticks: residual accumulation, speed-stepped scroll gain. One module shared by both pointing drivers. (Arrow mode — TrackPoint deltas as arrow-key repeats — was removed: its mode key was a bare `&kp`, so holding it typed the letter.)
- **Speed preference** — the user's cursor-speed setting, a named input to motion shaping. (Historically smuggled through trackpad/trackpoint LED brightness getters.)
- **Mode key** — a held key that changes what a pointing device's motion means. Must be a layer-tap or `&none`: held, it may send *nothing* to the host. A mod-tap here leaks its modifier for the whole gesture.
- **Scroll gesture** — hold a mode key, move a pointing device, scroll. The trackpad decides this in its own driver off a raw key position; the TrackPoint's decision is made on the central half by `trackpoint_listener`, gated on the LOWER layer. Same gesture, two mechanisms, because the TrackPoint's driver runs on the peripheral and only ever reports cursor motion.
- **Wheel axis polarity** — `REL_X` and `HWHEEL` are both positive-right, but `REL_Y` is positive-*down* while `WHEEL` is positive-*up*. So turning cursor motion into scrolling always costs one Y negation and never an X one. Both devices pay it: the trackpad in its driver (`INPUT_REL_WHEEL, -ticks.y`), the TrackPoint via `zip_scroll_transform INPUT_TRANSFORM_Y_INVERT`. Skip it and that device scrolls backwards and disagrees with the other one — with no other symptom.
- **POINTING layer** — raised for 700 ms by any TrackPoint motion (`zip_temp_layer`), not by any key. It turns the right thumb keys into mouse buttons while you are pointing.
- **Layer-number seam** — layer indices are positional in the keymap, but `zitaotech_keypoint_left.dts` restates two of them as macros to wire the listener. Neither file can see the other and a mismatch still builds; `tests/test_pointing_layers.py` derives the real indices and holds both files to them.
