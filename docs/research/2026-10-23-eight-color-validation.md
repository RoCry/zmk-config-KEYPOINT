# Eight-color validation — 2026-10-23

Scope: RGB565 → compact RGB111 driver, shared color UI, KP4 row roles, producer, image conversion and native LVGL preview. Software validation complete; manual UF2 upgrade and physical acceptance pending.

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
