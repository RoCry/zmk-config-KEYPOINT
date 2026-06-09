#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LPM_VIEW = ROOT / "config/boards/shields/lpm_view"

DISABLED_PERIPHERAL_IMAGES = ("cat", "mounta", "plane", "vader")


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


def test_disabled_images_are_not_wired_into_peripheral_firmware() -> None:
    cmake = (LPM_VIEW / "CMakeLists.txt").read_text()
    status = (LPM_VIEW / "widgets/peripheral_status.c").read_text()

    assert "widgets/art.c" not in cmake
    assert "widgets/landspace/landspace1.c" not in cmake
    assert "widgets/bunnygirl_anima/ballon.c" not in cmake

    for image in DISABLED_PERIPHERAL_IMAGES:
        assert f"widgets/picture/{image}.c" not in cmake
        assert f"LV_IMG_DECLARE({image});" not in status
        assert f"&{image}" not in status


if __name__ == "__main__":
    test_al_pacino_asset_is_wired_into_peripheral_firmware()
    test_disabled_images_are_not_wired_into_peripheral_firmware()
