"""Executable tests for the real firmware motion shaping, compiled and driven here.

`motion_shaping.c` is Zephyr-free by construction, so the host cc can build it
and ctypes can drive it. Both pointing drivers are thin adapters over this one
module, so these tests are the only place the cursor / scroll math is checked --
and the only defence the feel of the two halves has.

The device parameters are read out of the shields' Kconfig at import, not
retyped, so a knob that moves moves here too.
"""

from __future__ import annotations

import ctypes
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOTION = ROOT / "config/motion"
SHIM = Path(__file__).resolve().parent / "motion_shaping_shim.c"
LEFT_SHIELD = ROOT / "config/boards/shields/left_bbtrackpad_keypoint"
RIGHT_SHIELD = ROOT / "config/boards/shields/right_trackpoint_keypoint"
LEFT_KCONFIG = LEFT_SHIELD / "Kconfig.shield"
RIGHT_KCONFIG = RIGHT_SHIELD / "Kconfig.shield"


def _kconfig_defaults(path: Path) -> dict[str, int]:
    """Every `config NAME` / `default <int>` pair in a shield's Kconfig."""
    defaults: dict[str, int] = {}
    name: str | None = None

    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("config "):
            name = stripped.split(None, 1)[1]
        elif stripped.startswith("default ") and name is not None:
            value = stripped.split(None, 1)[1]
            if re.fullmatch(r"-?\d+", value):
                defaults[name] = int(value)
            name = None

    return defaults


LEFT = _kconfig_defaults(LEFT_KCONFIG)
RIGHT = _kconfig_defaults(RIGHT_KCONFIG)


@dataclass(frozen=True, slots=True)
class CursorConfig:
    prescale_num: int
    prescale_den: int
    base_speed: float
    sens_base: float
    sens_step: float


# prescale and base speed as the adapters declare them (a320.c, trackpoint_0x15.c);
# everything else comes from the shields' Kconfig.
CURSOR_CONFIGS = {
    "trackpad": CursorConfig(
        prescale_num=3,
        prescale_den=4,
        base_speed=1.0,
        sens_base=LEFT["A320_MOUSE_SENS_BASE_PERCENT"] / 100,
        sens_step=LEFT["A320_MOUSE_SENS_STEP_PERCENT"] / 100,
    ),
    "trackpoint": CursorConfig(
        prescale_num=1,
        prescale_den=1,
        base_speed=RIGHT["TRACKPOINT_MOUSE_BASE_SPEED_PERCENT"] / 100,
        sens_base=RIGHT["TRACKPOINT_MOUSE_SENS_BASE_PERCENT"] / 100,
        sens_step=RIGHT["TRACKPOINT_MOUSE_SENS_STEP_PERCENT"] / 100,
    ),
}

DEVICES = tuple(CURSOR_CONFIGS)
DELTA_DOMAIN = tuple(range(-128, 128))


def c_div(numerator: int, denominator: int) -> int:
    """C integer division: truncates toward zero, unlike Python's floor."""
    return math.trunc(numerator / denominator)


@pytest.fixture(scope="session")
def motion(tmp_path_factory: pytest.TempPathFactory) -> ctypes.CDLL:
    """Compile the pure module + ctypes shim with the host cc."""
    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None:
        raise RuntimeError("no host C compiler found; the motion shaping tests need cc or gcc")

    library = tmp_path_factory.mktemp("motion") / "libmotion.so"
    subprocess.run(
        [
            compiler,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-shared",
            "-fPIC",
            f"-I{MOTION}",
            str(SHIM),
            str(MOTION / "motion_shaping.c"),
            "-lm",
            "-o",
            str(library),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    lib = ctypes.CDLL(str(library))
    lib.motion_shim_cursor_scale.restype = ctypes.c_float
    lib.motion_shim_cursor_scale.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_float,
        ctypes.c_float,
        ctypes.c_float,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_float,
    ]
    return lib


class Scroll:
    """Both scroll axes, with the fractional residue they carry between samples."""

    def __init__(self, lib: ctypes.CDLL) -> None:
        self._lib = lib
        self.residue = (ctypes.c_float * 2)(0.0, 0.0)

    def accumulate(self, dx: int, dy: int) -> tuple[int, int]:
        tick_x, tick_y = ctypes.c_int16(), ctypes.c_int16()
        self._lib.motion_shim_scroll_accumulate(self.residue, dx, dy, ctypes.byref(tick_x), ctypes.byref(tick_y))
        return tick_x.value, tick_y.value


def cursor_scale(
    lib: ctypes.CDLL,
    config: CursorConfig,
    delta: int,
    speed_preference: int,
    *,
    boost: float = 1.0,
) -> float:
    return lib.motion_shim_cursor_scale(
        config.prescale_num,
        config.prescale_den,
        config.base_speed,
        config.sens_base,
        config.sens_step,
        delta,
        speed_preference,
        boost,
    )


# ---------------------------------------------------------------------------
# Scroll residual accumulation
#
# Only the trackpad reaches this code. The TrackPoint scrolls on the central
# half instead, where `trackpoint_listener` remaps its cursor axes to the wheel
# while LOWER is held -- see tests/test_pointing_layers.py.
# ---------------------------------------------------------------------------


def test_a_slow_scroll_drag_accumulates_before_it_emits(motion: ctypes.CDLL) -> None:
    """At the slowest gain one sample is worth 0.015 of a tick; it must not be lost."""
    scroll = Scroll(motion)

    assert scroll.accumulate(1, 0) == (0, 0)
    assert scroll.residue[0] == pytest.approx(0.015, rel=1e-5)

    ticks = [scroll.accumulate(1, 0)[0] for _ in range(200)]
    assert sum(ticks) > 0, "a sustained slow drag must eventually scroll"


def test_the_scroll_residue_only_ever_holds_a_fraction(motion: ctypes.CDLL) -> None:
    """Whole ticks are handed out immediately; only the remainder is carried."""
    scroll = Scroll(motion)

    for _ in range(500):
        scroll.accumulate(120, -120)
        assert abs(scroll.residue[0]) < 1.0
        assert abs(scroll.residue[1]) < 1.0


def test_scroll_is_sign_symmetric(motion: ctypes.CDLL) -> None:
    """Scrolling back must undo scrolling forward, tick for tick."""
    forward, backward = Scroll(motion), Scroll(motion)

    for delta in (1, 3, 7, 21, 60, 127):
        for _ in range(40):
            up = forward.accumulate(delta, delta)
            down = backward.accumulate(-delta, -delta)
            assert up == (-down[0], -down[1])
            assert forward.residue[0] == pytest.approx(-backward.residue[0])
            assert forward.residue[1] == pytest.approx(-backward.residue[1])


def test_a_fast_swipe_scrolls_further_than_a_slow_one(motion: ctypes.CDLL) -> None:
    def ticks(delta: int, samples: int = 100) -> int:
        scroll = Scroll(motion)
        return sum(scroll.accumulate(delta, 0)[0] for _ in range(samples))

    assert ticks(120) > ticks(30) > ticks(2)


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("speed_preference", (0, 10, 100, 255))
def test_cursor_scale_matches_the_shipped_formula(motion: ctypes.CDLL, device: str, speed_preference: int) -> None:
    """The pre-scale truncates in integers before any float math -- that is the feel."""
    config = CURSOR_CONFIGS[device]

    for delta in DELTA_DOMAIN:
        prescaled = c_div(delta * config.prescale_num, config.prescale_den)
        expected = prescaled * config.base_speed * (config.sens_base + config.sens_step * speed_preference)
        assert cursor_scale(motion, config, delta, speed_preference) == pytest.approx(expected, rel=1e-5, abs=1e-6)


@pytest.mark.parametrize("device", DEVICES)
def test_a_higher_speed_preference_moves_the_cursor_further(motion: ctypes.CDLL, device: str) -> None:
    config = CURSOR_CONFIGS[device]
    scales = [cursor_scale(motion, config, 100, preference) for preference in range(0, 256, 5)]

    assert scales == sorted(scales)
    assert scales[0] < scales[-1]


def test_the_boost_multiplies_the_cursor(motion: ctypes.CDLL) -> None:
    """The TrackPoint's exponential acceleration rides in as `boost`."""
    config = CURSOR_CONFIGS["trackpoint"]

    plain = cursor_scale(motion, config, 40, 128)
    boosted = cursor_scale(motion, config, 40, 128, boost=2.0)

    assert boosted == pytest.approx(plain * 2.0, rel=1e-5)


@pytest.mark.parametrize("device", DEVICES)
def test_cursor_scale_is_sign_symmetric(motion: ctypes.CDLL, device: str) -> None:
    config = CURSOR_CONFIGS[device]

    for delta in range(1, 128):
        forward = cursor_scale(motion, config, delta, 128)
        backward = cursor_scale(motion, config, -delta, 128)
        assert forward == pytest.approx(-backward, rel=1e-5)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shield", (LEFT_SHIELD, RIGHT_SHIELD), ids=("left", "right"))
def test_both_pointing_drivers_compile_the_shared_module(shield: Path) -> None:
    """A shared module only one half builds is a shared module in name only.

    Firmware compilation is a CI-only signal here, so the CMake wiring is worth
    checking where it is cheap to check.
    """
    cmake = (shield / "CMakeLists.txt").read_text()
    relative = Path("../../..") / MOTION.relative_to(ROOT / "config")

    assert f"zephyr_library_sources({relative / 'motion_shaping.c'})" in cmake
    assert f"zephyr_library_include_directories({relative})" in cmake
    assert (shield / relative / "motion_shaping.c").resolve().is_file()
