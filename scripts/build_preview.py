#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Build shared firmware renderer against the LVGL revision pinned by ZMK 0.3.0."""

import hashlib
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = "8a6a2d1d29d17d1e4bdc94c243c146a39d635fdd"
SHA256 = "26468bc82fc19137563e2c49acdc2439feddb32766c2b7d5bc136e9c068f5d33"
CACHE = ROOT / "tmp/native-preview"


def main() -> None:
    for tool in ("cmake", "ninja"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} is required to build the native preview")
    source = CACHE / f"lvgl-{REVISION}"
    if not source.is_dir():
        CACHE.mkdir(parents=True, exist_ok=True)
        archive = CACHE / "lvgl.tar.gz"
        url = f"https://codeload.github.com/zephyrproject-rtos/lvgl/tar.gz/{REVISION}"
        with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        with archive.open("rb") as content:
            if hashlib.file_digest(content, "sha256").hexdigest() != SHA256:
                raise SystemExit("LVGL archive checksum mismatch")
        with tarfile.open(archive) as tar:
            tar.extractall(CACHE, filter="data")
    subprocess.run(
        [
            "cmake",
            "-S",
            str(ROOT / "scripts/native_preview"),
            "-B",
            str(CACHE / "build"),
            "-G",
            "Ninja",
            f"-DLVGL_SOURCE_DIR={source}",
            "-DCMAKE_BUILD_TYPE=Release",
        ],
        check=True,
    )
    subprocess.run(["cmake", "--build", str(CACHE / "build"), "--target", "keypoint_preview"], check=True)


if __name__ == "__main__":
    main()
