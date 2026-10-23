"""Run the firmware RGB core against literal JDI rev03 RGB/line-frame goldens."""

from __future__ import annotations

import ctypes
import shutil
import subprocess
from pathlib import Path

import pytest

DRIVER = Path(__file__).resolve().parents[1] / "config/boards/shields/lpm_view/display_driver"


class Frame(ctypes.Structure):
    _fields_ = [("pixels", (ctypes.c_uint8 * 27) * 144), ("dirty", ctypes.c_bool * 144)]


class Rect(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_uint16),
        ("y", ctypes.c_uint16),
        ("width", ctypes.c_uint16),
        ("height", ctypes.c_uint16),
        ("pitch", ctypes.c_uint16),
        ("buf_size", ctypes.c_size_t),
    ]


Write = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t)
End = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)


class Transport(ctypes.Structure):
    _fields_ = [("write", Write), ("end", End), ("context", ctypes.c_void_p)]


class Bus:
    def __init__(self, fail_write: int = 0, end_error: int = 0) -> None:
        self.packets: list[bytes] = []
        self.ends = 0
        self.fail_write = fail_write
        self.end_error = end_error
        self.transport = Transport(Write(self.write), End(self.end), None)

    def write(self, _context: int, data: ctypes.Array, size: int) -> int:
        self.packets.append(bytes(data[:size]))
        return -71 if len(self.packets) == self.fail_write else 0

    def end(self, _context: int) -> int:
        self.ends += 1
        return self.end_error


@pytest.fixture(scope="session")
def core(tmp_path_factory: pytest.TempPathFactory) -> ctypes.CDLL:
    compiler = shutil.which("cc")
    if compiler is None:
        raise RuntimeError("RGB display core tests require a host C compiler")
    library = tmp_path_factory.mktemp("lpm-color") / "lpm-color.so"
    subprocess.run(
        [
            compiler,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-shared",
            "-fPIC",
            str(DRIVER / "lpm009m360a_core.c"),
            "-o",
            str(library),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    lib = ctypes.CDLL(str(library))
    lib.lpm_frame_init.argtypes = [ctypes.POINTER(Frame)]
    lib.lpm_frame_write_rgb565.argtypes = [ctypes.POINTER(Frame), ctypes.POINTER(Rect), ctypes.c_void_p]
    lib.lpm_frame_flush.argtypes = [ctypes.POINTER(Frame), ctypes.POINTER(Transport)]
    return lib


def write(core: ctypes.CDLL, frame: Frame, rect: Rect, colors: list[int]) -> int:
    source = (ctypes.c_uint16 * len(colors))(*colors)
    return core.lpm_frame_write_rgb565(ctypes.byref(frame), ctypes.byref(rect), source)


def flush(core: ctypes.CDLL, frame: Frame, bus: Bus) -> int:
    return core.lpm_frame_flush(ctypes.byref(frame), ctypes.byref(bus.transport))


@pytest.fixture
def clean_frame(core: ctypes.CDLL) -> Frame:
    frame = Frame()
    core.lpm_frame_init(ctypes.byref(frame))
    assert flush(core, frame, Bus()) == 0
    return frame


def test_full_white_frame_binary_addresses_and_one_final_dummy(core: ctypes.CDLL) -> None:
    frame = Frame()
    core.lpm_frame_init(ctypes.byref(frame))
    bus = Bus()
    assert flush(core, frame, bus) == 0
    # JDI rev03: first M0=1 (compact RGB), AG=1; continuation M=0,
    # AG=144 (normal binary, not Sharp bit-reversed); final 16 dummy clocks.
    assert bus.packets[0] == b"\x80\x01" + b"\xff" * 27
    assert bus.packets[143] == b"\x00\x90" + b"\xff" * 27
    assert bus.packets[144:] == [b"\x00\x00"]
    assert len(bus.packets) == 145
    assert bus.ends == 1


def test_eight_rgb_endpoints_cross_byte_boundaries_and_partial_preservation(
    core: ctypes.CDLL, clean_frame: Frame
) -> None:
    # Native RGB sequence 000 001 010 011 100 101 110 111 => 05 39 77.
    colors = [0x0000, 0x001F, 0x07E0, 0x07FF, 0xF800, 0xF81F, 0xFFE0, 0xFFFF]
    assert write(core, clean_frame, Rect(143, 0, 1, 8, 1, 16), colors) == 0
    bus = Bus()
    assert flush(core, clean_frame, bus) == 0
    assert bus.packets == [b"\x80\x01\x05\x39\x77" + b"\xff" * 24, b"\x00\x00"]

    # Replace blue with red only; all seven neighbors survive (11 39 77).
    assert write(core, clean_frame, Rect(143, 1, 1, 1, 1, 2), [0xF800]) == 0
    bus = Bus()
    assert flush(core, clean_frame, bus) == 0
    assert bus.packets[0] == b"\x80\x01\x11\x39\x77" + b"\xff" * 24


def test_pitched_rectangle_maps_landscape_to_native_rows(core: ctypes.CDLL, clean_frame: Frame) -> None:
    # Two logical rows, pitch=3: blue/white padding must not reach the panel.
    assert (
        write(
            core,
            clean_frame,
            Rect(142, 2, 2, 2, 3, 10),
            [0xF800, 0x07E0, 0x001F, 0x07FF, 0xF81F],
        )
        == 0
    )
    bus = Bus()
    assert flush(core, clean_frame, bus) == 0
    assert bus.packets == [
        b"\x80\x01\xfd\x5f" + b"\xff" * 25,
        b"\x00\x02\xfe\x3f" + b"\xff" * 25,
        b"\x00\x00",
    ]


def test_opposite_corner_and_unchanged_pixels_need_no_transfer(core: ctypes.CDLL, clean_frame: Frame) -> None:
    assert write(core, clean_frame, Rect(0, 71, 1, 1, 1, 2), [0]) == 0
    bus = Bus()
    assert flush(core, clean_frame, bus) == 0
    assert bus.packets == [b"\x80\x90" + b"\xff" * 26 + b"\xf8", b"\x00\x00"]
    assert write(core, clean_frame, Rect(0, 71, 1, 1, 1, 2), [0]) == 0
    bus = Bus()
    assert flush(core, clean_frame, bus) == 0
    assert (bus.packets, bus.ends) == ([], 0)


@pytest.mark.parametrize(
    "rect",
    [
        Rect(0, 0, 0, 1, 1, 2),
        Rect(0, 0, 1, 0, 1, 2),
        Rect(144, 0, 1, 1, 1, 2),
        Rect(0, 72, 1, 1, 1, 2),
        Rect(143, 0, 2, 1, 2, 4),
        Rect(0, 71, 1, 2, 1, 4),
        Rect(0, 0, 2, 1, 1, 4),
        Rect(0, 0, 1, 1, 1, 1),
        Rect(0, 0, 1, 2, 3, 7),
        Rect(65535, 65535, 65535, 65535, 65535, 0),
    ],
)
def test_invalid_descriptor_rejected_before_any_mutation(core: ctypes.CDLL, clean_frame: Frame, rect: Rect) -> None:
    before = bytes(clean_frame)
    assert write(core, clean_frame, rect, [0, 0, 0, 0]) < 0
    assert bytes(clean_frame) == before


@pytest.mark.parametrize("failed_write,end_error", [(1, 0), (2, 0), (3, 0), (0, -72), (1, -72)])
def test_partial_transfer_or_cs_release_failure_retries_all_desired_pixels(
    core: ctypes.CDLL, clean_frame: Frame, failed_write: int, end_error: int
) -> None:
    assert write(core, clean_frame, Rect(142, 0, 2, 1, 2, 4), [0xF800, 0x07E0]) == 0
    before = bytes(clean_frame)
    bus = Bus(fail_write=failed_write, end_error=end_error)
    assert flush(core, clean_frame, bus) == (-71 if failed_write else -72)
    assert bus.ends == 1
    assert bytes(clean_frame) == before
    # A later update does not lose either partially transmitted pending row.
    assert write(core, clean_frame, Rect(0, 71, 1, 1, 1, 2), [0]) == 0
    retry = Bus()
    assert flush(core, clean_frame, retry) == 0
    assert retry.packets == [
        b"\x80\x01\x5f" + b"\xff" * 26,
        b"\x00\x02\x9f" + b"\xff" * 26,
        b"\x00\x90" + b"\xff" * 26 + b"\xf8",
        b"\x00\x00",
    ]
    empty = Bus()
    assert flush(core, clean_frame, empty) == 0
    assert empty.packets == []
