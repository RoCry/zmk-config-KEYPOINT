#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LPM_VIEW = ROOT / "config/boards/shields/lpm_view"

SOURCES_CALL = re.compile(r"zephyr_library_sources\(([^)]*)\)")


def wired_sources() -> set[str]:
    """Shield-relative paths every CMake target compiles."""
    text = (LPM_VIEW / "CMakeLists.txt").read_text()
    return {entry for call in SOURCES_CALL.finditer(text) for entry in call.group(1).split()}


def existing_sources() -> set[str]:
    return {path.relative_to(LPM_VIEW).as_posix() for path in LPM_VIEW.rglob("*.c")}


def test_every_display_source_is_wired_into_a_cmake_target() -> None:
    wired = wired_sources()
    existing = existing_sources()

    assert existing, f"no display sources under {LPM_VIEW}"
    assert not existing - wired, f"sources no CMake target compiles: {sorted(existing - wired)}"
    assert not wired - existing, f"CMake compiles missing sources: {sorted(wired - existing)}"


def test_al_pacino_asset_is_wired_into_peripheral_firmware() -> None:
    asset = LPM_VIEW / "widgets/picture/al_pacino.c"
    status = (LPM_VIEW / "widgets/peripheral_status.c").read_text()

    assert asset.is_file()
    assert "widgets/picture/al_pacino.c" in wired_sources()
    assert "LV_IMG_DECLARE(al_pacino);" in status
    assert "&al_pacino" in status

    source = asset.read_text()
    assert "const lv_img_dsc_t al_pacino" in source
    assert ".header.cf = LV_IMG_CF_INDEXED_1BIT" in source
    assert ".header.w = 120" in source
    assert ".header.h = 72" in source
    assert ".data_size = 1088" in source


if __name__ == "__main__":
    test_every_display_source_is_wired_into_a_cmake_target()
    test_al_pacino_asset_is_wired_into_peripheral_firmware()
