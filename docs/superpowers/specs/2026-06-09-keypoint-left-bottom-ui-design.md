# KEYPOINT Left Bottom UI Design

## Goal

Improve the left-hand status screen area that currently shows large `1 2 3 4`
BLE profile circles and a plain layer label.

## Scope

- Change only the central/left `lpm_view` status widget.
- Keep live data, battery, transport icon, BLE service, and keymap behavior
  unchanged.
- Preserve the same three-canvas layout already used by `status.c`.

## Profile Area

Replace the large decorative profile circles with a compact 2x2 profile grid.
Each slot still uses profile numbers `1` through `4`, but the rendering must be
based on real per-profile state:

- active profile: inverted number block
- connected profile: filled status mark
- paired but disconnected profile: outline status mark
- open/unpaired profile: plus marker

Firmware state should store per-profile `connected` and `bonded` flags using
ZMK BLE APIs:

- `zmk_ble_profile_is_connected(index)`
- `!zmk_ble_profile_is_open(index)`

## Layer Area

Replace the plain layer label with a compact layer chip:

- draw a simple outline/chip around the label
- show `BASE` for layer `0`
- otherwise show the configured layer label when present
- fall back to `LAYER n` when no label exists

## Testing

Add static contract tests that verify:

- `status_state` carries per-profile connected/bonded arrays
- firmware reads per-profile BLE state
- profile drawing uses a compact profile-grid helper instead of the old large
  arc-only profile circles
- layer drawing uses a layer-chip helper and `BASE` label for layer `0`
