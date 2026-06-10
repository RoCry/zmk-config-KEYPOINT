# KEYPOINT Live Data Display Design

> Historical design note. Current firmware uses the KP3 deck protocol
> (`KP3|GEN|IDX|TOTAL|ICON|LED|L1|..|L6`, 75 bytes max); see `README.md`.
> KP2 details below are retained only as implementation history.

## Goal

Show small host-provided live data on the left KEYPOINT display by replacing the
current WPM graph area. First version ships with a BLE demo sender that pushes
randomized mock data by default. Real data sources can replace the sender provider
without changing firmware protocol.

## Scope

- Target only `zitaotech_keypoint_left`, the split central half.
- Replace only the WPM chart/number area in the central `lpm_view` status
  widget.
- Keep battery, output transport, BLE profile, and layer status behavior.
- Do not forward data to the right/peripheral half.
- Do not support Chinese text in v1.

## Display Contract

- Area: existing WPM panel in `widgets/status.c`, logical canvas region
  approximately `x=0..70`, `y=21..65`.
- Chrome: no surrounding frame; draw only a 1 px divider at the bottom of this
  region.
- Font: `lv_font_unscii_8`, already selected by `lpm_view`.
- Layout: 3 full-width text lines, plus one optional compact 8x8 pixel icon
  below the text and above the divider.
- Characters per text line: 8 printable ASCII bytes.
- Empty line is allowed.
- The `|` separator character is not allowed inside a line.
- Long or malformed payload is rejected as a whole.
- If no valid packet has arrived yet, display:
  - warning icon
  - `NO DATA`
  - `WAITING`
  - empty line
- If the last valid packet is older than 360 seconds, keep showing the last
  payload but draw icon, text, and bottom divider at reduced opacity
  (`LV_OPA_50`).

## Payload Contract

Text frame:

```text
KP2|ICON|LINE1|LINE2|TIME
```

Rules:

- Prefix must be `KP2|`.
- Exactly one icon field and 3 text fields after the prefix.
- `ICON` must be one of: `NONE`, `SUN`, `CLOUD`, `RAIN`, `TEMP`, `WARN`,
  `CODE`, `TIME`, `CODEX`, `CLAUDE`.
- Each text line is 0-8 printable ASCII characters, excluding `|`.
- `TIME` is the data-source update time, not the BLE send time. Recommended
  format: `HH:MM`.
- Total frame length must fit in one BLE write. With these limits the maximum
  payload is 39 bytes.
- Firmware stores the accepted data in RAM only. Reboot resets to `NO DATA`.
- Firmware fail-fast behavior: reject malformed packets and keep last valid
  display state. Do not silently truncate.

## BLE Transport

Use a custom BLE GATT service on the keyboard:

- Service UUID: `f5d40000-6d2f-4f4b-9b2a-2f4a8e8c0001`
- Write characteristic UUID: `f5d40001-6d2f-4f4b-9b2a-2f4a8e8c0001`
- Properties: write and write-without-response.
- Permissions: encrypted write.

The host script connects to the keyboard by BLE name or explicit address and
writes the text frame to the characteristic every 30 seconds.

## Firmware Artifacts And Bootloader Entry

Use short GitHub Actions artifact names in `build.yaml`:

- `left.uf2`
- `right.uf2`
- `left-reset.uf2`
- `right-reset.uf2`

Add layer-based Bootloader shortcuts without changing the base-layer tap
behavior:

- Left hand: hold `LOWER` and press the physical base-layer `MUTE` key.
- Right hand: hold `SYMBOL` and press the physical base-layer `Ctl+Up` key.

## Firmware Shape

Add a focused live-data module under `config/boards/shields/lpm_view/widgets/`:

- Own the BLE GATT service and write callback.
- Validate payloads.
- Store latest accepted icon, text lines, and receive timestamp.
- Expose a small read API for the status widget.
- Submit display work after valid updates.

Modify `widgets/status.c`:

- Include live-data header.
- Replace WPM chart drawing with a live-data icon plus 3-line text panel.
- Remove WPM listener dependency from central widget if no longer used.

Modify build/Kconfig:

- Compile live-data module only for central builds with display enabled.
- Keep peripheral build untouched.

## Demo Sender

Create `scripts/send_keypoint_live_demo.py`:

- Standalone PEP 723 script.
- Dependency: `bleak`.
- CLI flags:
  - `--name KEYPOINT`
  - `--address <BLE address or UUID>`
  - `--interval 2`
  - `--source-interval 2`
  - `--count <n>`
  - `--once`
  - `--random / --sequential`
  - `--seed <n>`
- Sends mock frames such as:
  - `KP2|SUN|SUNNY|TMP 24C|12:34`
  - `KP2|CODEX|CODEX|5h 58%|12:34`
  - `KP2|CLAUDE|CLAUDE|CODE|12:34`
- `--interval` controls BLE rebroadcast frequency. `--source-interval`
  controls when the demo source data and `TIME` field change.
- Default demo mode randomizes dynamic weather, code/build, Codex, Claude Code,
  time, warning, and edge-case samples.
- `--sequential` cycles through a stable sample set covering all supported icon
  IDs and several 8-character edge-case text fields for layout validation.

## Testing

- Add Python tests for payload contract constants and demo frame validation.
- Add static firmware tests that verify:
  - WPM chart calls were removed from central status drawing.
  - Live-data module is compiled in central `lpm_view` build path.
  - Payload limits in docs, sender, and firmware stay aligned.
- Run existing repository tests with `uv run pytest`.
- Full firmware build may require a ZMK west workspace not present in this
  config-only checkout.
