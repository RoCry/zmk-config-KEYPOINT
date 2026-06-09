# KEYPOINT Live Data Display Design

## Goal

Show small host-provided live data on the left KEYPOINT display by replacing the
current WPM graph area. First version ships with a BLE demo sender that pushes
mock data every 30 seconds. Real data sources can replace the sender provider
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
- Lines: 4.
- Characters per line: 8 printable ASCII bytes.
- Empty line is allowed.
- The `|` separator character is not allowed inside a line.
- Long or malformed payload is rejected as a whole.
- If no valid packet has arrived yet, display:
  - `NO DATA`
  - `WAITING`
  - empty line
  - empty line
- If the last valid packet is older than 120 seconds, display:
  - `STALE`
  - previous line 1
  - previous line 2
  - previous line 3
- Stale state also draws the live-data text and bottom divider at reduced
  opacity (`LV_OPA_50`). The `STALE` text remains as a reliable fallback for
  monochrome or low-contrast display paths.

## Payload Contract

Text frame:

```text
KP1|LINE1|LINE2|LINE3|LINE4
```

Rules:

- Prefix must be `KP1|`.
- Exactly 4 line fields after the prefix.
- Each line is 0-8 printable ASCII characters, excluding `|`.
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

## Firmware Shape

Add a focused live-data module under `config/boards/shields/lpm_view/widgets/`:

- Own the BLE GATT service and write callback.
- Validate payloads.
- Store latest accepted lines and timestamp.
- Expose a small read API for the status widget.
- Submit display work after valid updates.

Modify `widgets/status.c`:

- Include live-data header.
- Replace WPM chart drawing with a 4-line live-data text panel.
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
  - `--interval 30`
  - `--once`
- Sends rotating mock frames:
  - `KP1|SUNNY|TMP 24C|AQI 42|12:34`
  - `KP1|CLOUDY|TMP 19C|HUM 62%|12:35`
  - `KP1|RAIN|TMP 17C|WIND 3M|12:36`

## Testing

- Add Python tests for payload contract constants and demo frame validation.
- Add static firmware tests that verify:
  - WPM chart calls were removed from central status drawing.
  - Live-data module is compiled in central `lpm_view` build path.
  - Payload limits in docs, sender, and firmware stay aligned.
- Run existing repository tests with `uv run pytest`.
- Full firmware build may require a ZMK west workspace not present in this
  config-only checkout.
