#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["pytest>=8", "pillow>=12.2"]
# ///
"""Build the real renderer, then run host checks in one dependency-managed command."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, str(ROOT / "scripts/build_preview.py")], check=True)
raise SystemExit(pytest.main([str(ROOT / "tests"), *sys.argv[1:]]))
