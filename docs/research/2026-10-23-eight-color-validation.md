# Eight-color validation — 2026-10-23

Initial scope: RGB565 → compact RGB111 driver, shared color UI, KP4 row roles, producer, image conversion and native LVGL preview. Initial software evidence below; subsequent device evidence and dark UI revision recorded at the end.

## Host checks

- `uv run scripts/check.py -q`: 283 passed. Builds the shared native renderer first. Covers independent wire-byte/corner/pitch fixtures, SPI failure/retry, KP4 parser and staging, actual LVGL output, image palette/export/decoding.
- rcink producer: `uv run pytest tests/test_keypoint.py tests/test_keypoint_cards.py tests/test_keypoint_roles.py`: 68 passed. Row semantics, timestamp/padding alignment and quota thresholds.
- Canonical and producer-vendored KP4 Python/JSON contracts byte-identical.

## Local firmware builds

ZMK v0.3.0 (`edf5c0814fd3ea202e43aad2d68fd32e882a518c`), Zephyr `dacab4875df72109b96cc8977547a0dc04875bcd`, SDK 0.16.9. Container `zmkfirmware/zmk-build-arm:stable`, digest `sha256:edb1c953438c6f720ddb79c3762f3972013b7fbbaf4fff3592fc869983e7afc5`.

| Half | FLASH | RAM | UF2 bytes | Result |
|---|---:|---:|---:|---|
| Left | 436,268 / 864,256 (50.48%) | 132,730 / 262,144 (50.63%) | 872,960 | PASS |
| Right | 332,668 / 864,256 (38.49%) | 92,636 / 262,144 (35.34%) | 665,600 | PASS |

Left map: 20,736-byte full draw buffer; 20,768-byte widget allocation; 4,052-byte driver state including mutex. No new display/UI warnings; existing Nordic/ZMK configuration warnings remain.

Local evidence: `tmp/firmware-8color/{candidate-left.log,candidate-right.log,sources.json,left.uf2,right.uf2}`. Candidate config tar SHA-256 `4fa5b630e1eabdad654a59799222543db88499446689ea680257c00309c96751`.

- Left UF2 SHA-256: `16379e5c687a88b5d6555200b117790e61f3cbf9240614f127fbee5bc798b464`
- Right UF2 SHA-256: `b248a2c10627eea7b9fad2edd091644400e0b3adb50a4ab99c8c70554aa43cbf`

These are local build hashes, not GitHub Actions artifact hashes. Delivery uses Actions artifacts for the pushed commit; select the corresponding successful run in [Actions](https://github.com/RoCry/zmk-config-KEYPOINT/actions/workflows/main.yml).

## Preview and pending acceptance

`just preview` → `tmp/status-preview/`. Includes fresh/warning/scoped-limit CLAUDE, attention/stale CODEX, mixed deck and no-data. `tmp/eight-color-al-pacino/` contains RGB/no-dither/dither comparison and decoded firmware image.

Not verified: physical colors/readability/orientation, DISP/EXTCOMIN wiring, COM behavior, cold start, wake, power. Switching a live mono panel to RGB may require a full power/DISP reset. User chose preview first, then manual upgrade from Actions UF2. No device flashed.

KEYPOINT launchd sender was unloaded because it reads the producer working tree every minute; leave it paused until KP4 firmware and an acknowledged deck succeed. Other producer fetching remains active. Resume sequence: `rcink/producer/docs/keypoint-kp4.md`.

## Subsequent device evidence and dark UI revision

User manually flashed initial Actions artifacts from run `39911617016` (`7f290fd`). Photos show colored battery/connection/profile UI and Al Pacino. At 14:40, five KP4 frames succeeded with acknowledged writes; subsequent photo showed CLAUDE 5H/7D/scoped rows. Scheduled sender resumed at 14:42; later five-card deliveries continued with `response=True`. Initial NO DATA was consistent with the intentionally paused sender, not a reproduced parser failure.

Photographed white bottom strip reproduced as 4 uncovered portrait rows: logical x20 + image width120 =140, screen width144. Image decoding excluded white padding in the asset. Dark revision uses native fullscreen144×72 assets, one18px full-width overlay, and explicitly black parent surfaces.

Dark revision: 300 host tests passed, including independent decoded-photo pixels across the whole region below the overlay, repeated charging/image updates, and frozen pixel hashes of all four user-approved D previews. Export defaults to no dithering; a midtone fixture catches accidental diffusion. Native preview now executes full shared LVGL object composition, replacing manual canvas copying. Code review found no actionable defects.

| Dark revision | FLASH | RAM | UF2 bytes |
|---|---:|---:|---:|
| Left | 435,828 | 132,730 | 871,936 |
| Right | 345,504 | 97,756 | 691,200 |

Both builds passed using the same local toolchain above. Evidence: `tmp/dark-firmware/`. User chose D for all four images: nearest RGB111 palette, no dithering; exported pixels match the selected PNGs exactly. Dark revision has not been flashed. COM, wake, power and detailed physical readability remain unverified.
