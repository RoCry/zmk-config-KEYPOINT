# KEYPOINT Left Bottom UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the left-hand decorative profile/layer bottom UI with a compact profile grid and layer chip.

**Architecture:** Keep the existing `status.c` canvas structure. Extend status state with per-profile flags, collect those flags from ZMK BLE APIs, and isolate rendering into small helper functions.

**Tech Stack:** ZMK firmware C, LVGL canvas drawing, pytest static contract tests.

---

### Task 1: Contract Tests

**Files:**
- Modify: `tests/test_live_data_contract.py`

- [ ] Add static tests requiring per-profile state arrays, per-profile ZMK BLE API calls, a compact profile-grid helper, and a layer-chip helper.
- [ ] Run `uv run --isolated --with pytest --with Pillow pytest -q tests/test_live_data_contract.py`.
- [ ] Expected red result: new bottom UI tests fail against the current decorative circles/plain layer label.

### Task 2: Firmware UI

**Files:**
- Modify: `config/boards/shields/lpm_view/widgets/util.h`
- Modify: `config/boards/shields/lpm_view/widgets/status.c`

- [ ] Add `KEYPOINT_STATUS_PROFILE_COUNT`.
- [ ] Store `profile_connected[]` and `profile_bonded[]` in central status state.
- [ ] Populate those arrays from `zmk_ble_profile_is_connected()` and `zmk_ble_profile_is_open()`.
- [ ] Replace the old profile-circle loop with compact profile slot/grid helpers.
- [ ] Replace plain layer drawing with a layer-chip helper.

### Task 3: Verification

**Files:**
- Test: `tests/test_live_data_contract.py`

- [ ] Run `uv run --isolated --with pytest --with Pillow pytest -q`.
- [ ] Run `uv run --isolated --with ruff ruff check tests/test_live_data_contract.py`.
- [ ] Run `git diff --check`.
- [ ] Commit, push, watch GitHub Actions, and download firmware to `/tmp`.
