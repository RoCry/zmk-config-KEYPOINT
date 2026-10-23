"""Python adapter for the firmware's LVGL renderer; no duplicate UI drawing code."""

import ctypes
import sys
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import kp4
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
_LOCK = threading.Lock()  # LVGL's singleton state is not thread-safe.


@dataclass(frozen=True, slots=True)
class StatusState:
    battery: int
    charging: bool
    transport: str
    active_profile_index: int
    profile_connected: tuple[bool, ...]
    profile_bonded: tuple[bool, ...]
    layer_index: int
    layer_label: str | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.battery <= 100:
            raise ValueError("battery must be in 0..100")
        if self.transport not in ("usb", "ble"):
            raise ValueError("transport must be usb or ble")
        if len(self.profile_connected) != 4 or len(self.profile_bonded) != 4:
            raise ValueError("exactly four BLE profile states required")
        if not 0 <= self.active_profile_index < 4:
            raise ValueError("active profile must be in 0..3")
        if not 0 <= self.layer_index <= 255:
            raise ValueError("layer index must fit a byte")
        if self.layer_label is not None:
            if any(not 32 <= ord(c) <= 126 for c in self.layer_label):
                raise ValueError("layer label must be printable ASCII")
            if len(self.layer_label.strip()) > 8:
                raise ValueError("layer label exceeds 68-pixel display width")


@lru_cache(maxsize=1)
def _library() -> ctypes.CDLL:
    suffix = "dylib" if sys.platform == "darwin" else "so"
    path = ROOT / f"tmp/native-preview/build/libkeypoint_preview.{suffix}"
    if not path.is_file():
        raise RuntimeError("Native preview missing: run uv run scripts/build_preview.py first")
    lib = ctypes.CDLL(str(path))
    lib.keypoint_preview.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_size_t,
        ctypes.c_char_p,
        ctypes.c_bool,
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    lib.keypoint_preview.restype = ctypes.c_int
    lib.keypoint_preview_dimension.argtypes = [ctypes.c_int]
    lib.keypoint_preview_dimension.restype = ctypes.c_int
    return lib


def _render(state: StatusState, frame: str | None, stale: bool, mode: int) -> Image.Image:
    encoded = None
    if frame is not None:
        kp4.parse(frame)
        encoded = frame.encode("ascii")
    lib = _library()
    width = lib.keypoint_preview_dimension(0)
    height = lib.keypoint_preview_dimension(1 if mode == 0 else 0)
    pixels = (ctypes.c_uint8 * (width * height * 3))()
    connected = sum(int(value) << i for i, value in enumerate(state.profile_connected))
    bonded = sum(int(value) << i for i, value in enumerate(state.profile_bonded))
    values = (ctypes.c_int * 7)(
        state.battery,
        state.charging,
        state.transport == "usb",
        state.active_profile_index,
        connected,
        bonded,
        state.layer_index,
    )
    label = state.layer_label.encode("ascii") if state.layer_label else None
    with _LOCK:
        result = lib.keypoint_preview(pixels, len(pixels), encoded, stale, values, label, mode)
    if result:
        raise RuntimeError(f"Firmware renderer rejected input: {result}")
    return Image.frombytes("RGB", (width, height), bytes(pixels))


def render_left_screen(state: StatusState, frame: str | None, stale: bool = False) -> Image.Image:
    return _render(state, frame, stale, 0)


def render_canvas(state: StatusState, frame: str | None, *, section: str, stale: bool = False) -> Image.Image:
    if section not in ("top", "middle"):
        raise ValueError("section must be top or middle")
    return _render(state, frame, stale, 1 if section == "top" else 2)
