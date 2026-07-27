"""Executable tests for the real firmware motion shaping, compiled and driven here.

`motion_shaping.c` is Zephyr-free by construction, so the host cc can build it
and ctypes can drive it. Both pointing drivers are thin adapters over this one
module, so these tests are the only place the cursor / scroll / arrow math is
checked -- and the only defence the feel of the two halves has.

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
class ArrowConfig:
    deadzone: int
    divisor_slow: int
    divisor_fast: int


@dataclass(frozen=True, slots=True)
class CursorConfig:
    prescale_num: int
    prescale_den: int
    base_speed: float
    sens_base: float
    sens_step: float
    slow_multiplier: float


ARROW_CONFIGS = {
    "trackpad": ArrowConfig(
        deadzone=LEFT["A320_ARROW_DEADZONE"],
        divisor_slow=LEFT["A320_ARROW_DIVISOR_SLOW"],
        divisor_fast=LEFT["A320_ARROW_DIVISOR_FAST"],
    ),
    "trackpoint": ArrowConfig(
        deadzone=RIGHT["TRACKPOINT_ARROW_DEADZONE"],
        divisor_slow=RIGHT["TRACKPOINT_ARROW_DIVISOR_SLOW"],
        divisor_fast=RIGHT["TRACKPOINT_ARROW_DIVISOR_FAST"],
    ),
}

# prescale and base speed as the adapters declare them (a320.c, trackpoint_0x15.c);
# everything else comes from the shields' Kconfig.
CURSOR_CONFIGS = {
    "trackpad": CursorConfig(
        prescale_num=3,
        prescale_den=4,
        base_speed=1.0,
        sens_base=LEFT["A320_MOUSE_SENS_BASE_PERCENT"] / 100,
        sens_step=LEFT["A320_MOUSE_SENS_STEP_PERCENT"] / 100,
        slow_multiplier=0.5,
    ),
    "trackpoint": CursorConfig(
        prescale_num=1,
        prescale_den=1,
        base_speed=RIGHT["TRACKPOINT_MOUSE_BASE_SPEED_PERCENT"] / 100,
        sens_base=RIGHT["TRACKPOINT_MOUSE_SENS_BASE_PERCENT"] / 100,
        sens_step=RIGHT["TRACKPOINT_MOUSE_SENS_STEP_PERCENT"] / 100,
        slow_multiplier=0.5,
    ),
}

DEVICES = tuple(ARROW_CONFIGS)
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
        ctypes.c_float,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_float,
    ]
    return lib


class Arrow:
    """One axis of arrow mode, with its own residue."""

    def __init__(self, lib: ctypes.CDLL, config: ArrowConfig) -> None:
        self._lib = lib
        self._config = config
        self.residue = ctypes.c_int16(0)

    def divisor(self, delta: int) -> int:
        return self._lib.motion_shim_arrow_divisor(
            self._config.deadzone, self._config.divisor_slow, self._config.divisor_fast, delta
        )

    def step(self, delta: int) -> tuple[int, int]:
        """-> (pulses, direction)."""
        direction = ctypes.c_int()
        pulses = self._lib.motion_shim_arrow_step(
            self._config.deadzone,
            self._config.divisor_slow,
            self._config.divisor_fast,
            delta,
            ctypes.byref(self.residue),
            ctypes.byref(direction),
        )
        return pulses, direction.value


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
    slow: bool = False,
    boost: float = 1.0,
) -> float:
    return lib.motion_shim_cursor_scale(
        config.prescale_num,
        config.prescale_den,
        config.base_speed,
        config.sens_base,
        config.sens_step,
        config.slow_multiplier,
        delta,
        speed_preference,
        int(slow),
        boost,
    )


# ---------------------------------------------------------------------------
# The arrow speed curve: the regression pin for the clamp/normalise bug
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("device", DEVICES)
def test_the_arrow_curve_never_leaves_its_intended_range(motion: ctypes.CDLL, device: str) -> None:
    """The whole point of the fix.

    The divisor is the cost of one arrow press: SLOW gives the finest control,
    FAST the quickest repeat, and nothing outside that band is a speed anyone
    asked for. The old code clamped the delta by the arrow max but normalised it
    by the *scroll* max, so past the scroll max the curve factor overshot, the
    divisor went negative, and a `< 1` floor pinned it at 1 -- eight times more
    sensitive than FAST, on exactly the fast flicks where that hurts most.
    """
    arrow = Arrow(motion, ARROW_CONFIGS[device])
    config = ARROW_CONFIGS[device]

    for delta in DELTA_DOMAIN:
        divisor = arrow.divisor(delta)
        assert config.divisor_fast <= divisor <= config.divisor_slow, (
            f"delta={delta} shaped to divisor {divisor}, outside [{config.divisor_fast}, {config.divisor_slow}]"
        )


@pytest.mark.parametrize("device", DEVICES)
def test_the_arrow_curve_reaches_both_of_its_ends(motion: ctypes.CDLL, device: str) -> None:
    """A curve pinned inside a range must still span it, or the range proves nothing."""
    arrow = Arrow(motion, ARROW_CONFIGS[device])
    config = ARROW_CONFIGS[device]

    assert arrow.divisor(0) == config.divisor_slow, "at rest, the finest steps"
    assert arrow.divisor(-128) == config.divisor_fast, "at full scale, the fastest repeat"


@pytest.mark.parametrize("device", DEVICES)
def test_the_arrow_curve_only_ever_speeds_up(motion: ctypes.CDLL, device: str) -> None:
    """Push harder, repeat faster: the divisor must not rise with |delta|."""
    arrow = Arrow(motion, ARROW_CONFIGS[device])

    divisors = [arrow.divisor(delta) for delta in range(0, 128)]
    assert divisors == sorted(divisors, reverse=True)


@pytest.mark.parametrize("device", DEVICES)
def test_the_arrow_curve_is_sign_symmetric(motion: ctypes.CDLL, device: str) -> None:
    arrow = Arrow(motion, ARROW_CONFIGS[device])

    for delta in range(1, 128):
        assert arrow.divisor(delta) == arrow.divisor(-delta)


def test_the_old_normalisation_would_fail_the_range_pin() -> None:
    """The pin above has to discriminate, so here is the formula it rejects.

    This is the shipped A320 arithmetic before the fix -- clamp by the arrow max
    (128), normalise by the scroll max (64) -- kept only to prove the range test
    is not vacuous.
    """
    scroll_input_max, arrow_input_max = 64, 128
    divisor_slow, divisor_fast = 60, 8

    def old_divisor(delta: int) -> int:
        abs_delta = min(abs(delta), arrow_input_max)
        t = (abs_delta / scroll_input_max) ** 2
        return max(int(divisor_slow - (divisor_slow - divisor_fast) * t), 1)

    out_of_range = [d for d in DELTA_DOMAIN if not divisor_fast <= old_divisor(d) <= divisor_slow]
    assert out_of_range, "the old formula must break the range, or the pin tests nothing"
    assert old_divisor(90) == 1, "a fast flick used to land on maximum sensitivity"


# ---------------------------------------------------------------------------
# Arrow repeat: deadzone, accumulation, decay
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("device", DEVICES)
def test_a_delta_inside_the_deadzone_emits_nothing_and_leaves_no_trace(motion: ctypes.CDLL, device: str) -> None:
    """Hand tremor must not move the cursor, nor build up to moving it later."""
    config = ARROW_CONFIGS[device]
    arrow = Arrow(motion, config)

    for _ in range(200):
        for delta in range(-config.deadzone, config.deadzone + 1):
            assert arrow.step(delta) == (0, 0)

    assert arrow.residue.value == 0


@pytest.mark.parametrize("device", DEVICES)
def test_deltas_too_small_for_one_press_accumulate_into_one(motion: ctypes.CDLL, device: str) -> None:
    """One slow sample is never a keypress; enough of them in a row are."""
    config = ARROW_CONFIGS[device]
    arrow = Arrow(motion, config)
    delta = 30

    assert delta < arrow.divisor(delta), "the fixture needs a delta below one press"
    assert arrow.step(delta) == (0, 0), "so the first sample must emit nothing"

    for _ in range(200):
        pulses, direction = arrow.step(delta)
        if pulses:
            assert direction == 1
            break
    else:
        pytest.fail("a held drag never produced an arrow press")


@pytest.mark.parametrize("device", DEVICES)
def test_a_drag_slower_than_the_decay_never_repeats(motion: ctypes.CDLL, device: str) -> None:
    """The decay sets the real threshold, well above the deadzone.

    Each sample keeps three quarters of what it had, so a drag of `d` per sample
    settles at 3*d of residue -- a little under, once the integer truncation has
    its say -- and stops there. Below divisor/3 the arrow simply never fires,
    which is what keeps a resting thumb quiet.
    """
    config = ARROW_CONFIGS[device]
    arrow = Arrow(motion, config)
    delta = config.deadzone + 1
    divisor = arrow.divisor(delta)

    assert 3 * delta < divisor, "the fixture needs a drag that settles below one press"

    for _ in range(500):
        assert arrow.step(delta) == (0, 0)

    assert 0 < arrow.residue.value <= 3 * delta


@pytest.mark.parametrize("device", DEVICES)
def test_the_residue_decays_by_a_quarter_on_every_sample(motion: ctypes.CDLL, device: str) -> None:
    """Pinned exactly, because the decay is what stops a lifted finger repeating."""
    config = ARROW_CONFIGS[device]

    for sign in (1, -1):
        arrow = Arrow(motion, config)
        delta = sign * (config.deadzone + 1)
        expected = 0

        for _ in range(10):
            arrow.step(delta)
            expected += delta
            if (ticks := c_div(expected, arrow.divisor(delta))) != 0:
                expected -= ticks * arrow.divisor(delta)
            expected = c_div(expected * 3, 4)
            assert arrow.residue.value == expected


@pytest.mark.parametrize("device", DEVICES)
def test_arrow_direction_follows_the_sign_of_the_drag(motion: ctypes.CDLL, device: str) -> None:
    config = ARROW_CONFIGS[device]

    for sign in (1, -1):
        arrow = Arrow(motion, config)
        for _ in range(200):
            pulses, direction = arrow.step(sign * 100)
            if pulses:
                assert direction == sign
                break
        else:
            pytest.fail("a sustained flick never produced an arrow press")


@pytest.mark.parametrize("device", DEVICES)
def test_a_flick_repeats_faster_than_a_drag(motion: ctypes.CDLL, device: str) -> None:
    """The curve has to buy something: more presses per sample when pushed hard."""
    config = ARROW_CONFIGS[device]

    def presses(delta: int, samples: int = 60) -> int:
        arrow = Arrow(motion, config)
        return sum(arrow.step(delta)[0] for _ in range(samples))

    assert presses(120) > presses(40) > 0


# ---------------------------------------------------------------------------
# Scroll residual accumulation
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


@pytest.mark.parametrize("device", DEVICES)
def test_the_slow_key_halves_the_cursor(motion: ctypes.CDLL, device: str) -> None:
    config = CURSOR_CONFIGS[device]

    normal = cursor_scale(motion, config, 100, 128)
    slow = cursor_scale(motion, config, 100, 128, slow=True)

    assert slow == pytest.approx(normal * config.slow_multiplier, rel=1e-5)


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
# Dominant axis
# ---------------------------------------------------------------------------


def dominant(lib: ctypes.CDLL, dx: int, dy: int, numerator: int = 3, denominator: int = 2) -> tuple[int, int]:
    out_x, out_y = ctypes.c_int(dx), ctypes.c_int(dy)
    lib.motion_shim_dominant_axis(numerator, denominator, ctypes.byref(out_x), ctypes.byref(out_y))
    return out_x.value, out_y.value


def test_the_leading_axis_survives_alone(motion: ctypes.CDLL) -> None:
    assert dominant(motion, 100, 5) == (100, 0)
    assert dominant(motion, -100, 5) == (-100, 0)
    assert dominant(motion, 5, 100) == (0, 100)
    assert dominant(motion, 5, -100) == (0, -100)


def test_an_ambiguous_drag_moves_nothing(motion: ctypes.CDLL) -> None:
    """Neither axis leading by 3:2 means the user aimed at neither arrow."""
    assert dominant(motion, 50, 50) == (0, 0)
    assert dominant(motion, 0, 0) == (0, 0)
    assert dominant(motion, 60, 50) == (0, 0)


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
