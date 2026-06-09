#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LPM_VIEW = ROOT / "config/boards/shields/lpm_view"


def test_al_pacino_asset_is_wired_into_peripheral_firmware() -> None:
    asset = LPM_VIEW / "widgets/picture/al_pacino.c"
    cmake = (LPM_VIEW / "CMakeLists.txt").read_text()
    status = (LPM_VIEW / "widgets/peripheral_status.c").read_text()

    assert asset.is_file()
    assert "widgets/picture/al_pacino.c" in cmake
    assert "LV_IMG_DECLARE(al_pacino);" in status
    assert "&al_pacino" in status

    source = asset.read_text()
    assert "const lv_img_dsc_t al_pacino" in source
    assert ".header.cf = LV_IMG_CF_INDEXED_1BIT" in source
    assert ".header.w = 120" in source
    assert ".header.h = 72" in source
    assert ".data_size = 1088" in source


if __name__ == "__main__":
    test_al_pacino_asset_is_wired_into_peripheral_firmware()
