#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["pillow>=12.2"]
# ///
"""Native LVGL 8.3.7 preview: executes shared firmware UI, rotation and RGB111 packing.

Build once with uv run scripts/build_preview.py. This shows digital panel
pixels; reflective panel pigments, lighting and physical timing still need
device validation.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

import kp4
from keypoint_native import StatusState, render_left_screen
from PIL import Image


@dataclass(frozen=True, slots=True)
class PreviewCase:
    name: str
    state: StatusState
    frame: str | None = None
    stale: bool = False


_PROFILES_CONNECTED = (True, False, False, False)
_PROFILES_BONDED = (True, True, False, False)

#: Generation the demo deck is stamped with; any two-hex-digit value will do.
_DEMO_GENERATION = 0xA0

# The KEYPOINT keyboard only ever shows the claude + codex usage cards built by
# rcink (producer/rcink/keypoint_cards.py, CARD_ORDER = ("claude", "codex")),
# whose shape kp4.usage_card() owns: title + a window row (countdown to reset)
# and a [bar] utilisation row per window (5H/7D), then L6 -- the highest
# model-scoped limit when the plan has one, empty when it does not. No timestamp
# line (show_timestamp=False), no weather. The countdown strings below follow
# rcink's fmt_countdown (NOW / 12m / 1h23m / 18h / 4d).
DEMO_CASES: tuple[PreviewCase, ...] = (
    PreviewCase(
        # Fresh claude card, low usage, BLE connected on the base layer.
        name="claude_fresh",
        state=StatusState(78, False, "ble", 0, _PROFILES_CONNECTED, _PROFILES_BONDED, 0),
        frame=kp4.claude_card(
            "1h23m", 22, "4d", 41, led_hint=0, row_roles=(0, 0, 1, 0, 1, 0), generation=_DEMO_GENERATION
        ),
    ),
    PreviewCase(
        # The claude card as it usually arrives: a model-scoped limit fills L6,
        # the only line the usage cards otherwise leave blank.
        name="claude_scoped_limit",
        state=StatusState(78, False, "ble", 0, _PROFILES_CONNECTED, _PROFILES_BONDED, 0),
        frame=kp4.claude_card(
            "1h30m",
            76,
            "4d",
            88,
            scoped_limit=("FB", 68),
            led_hint=2,
            row_roles=(0, 0, 2, 0, 2, 1),
            generation=_DEMO_GENERATION,
        ),
    ),
    PreviewCase(
        # Codex card, one window into the attention band (>=75%) -> LED hint 2,
        # USB charging on the lower layer.
        name="codex_attention",
        state=StatusState(47, True, "usb", 0, _PROFILES_CONNECTED, _PROFILES_BONDED, 1, "LOWER"),
        frame=kp4.codex_card(
            "12m", 78, "2d", 54, led_hint=2, row_roles=(0, 0, 2, 0, 1, 0), generation=_DEMO_GENERATION
        ),
    ),
    PreviewCase(
        # Claude near the 5H limit: countdown reads NOW, bars near full, warning.
        name="claude_warning",
        state=StatusState(93, False, "ble", 0, _PROFILES_CONNECTED, _PROFILES_BONDED, 0),
        frame=kp4.claude_card(
            "NOW", 96, "18h", 89, led_hint=3, row_roles=(0, 0, 3, 0, 2, 0), generation=_DEMO_GENERATION
        ),
    ),
    PreviewCase(
        # Bonded but disconnected active profile -> LV_SYMBOL_CLOSE; stale data
        # stays readable, the segmented health strip flags the staleness.
        name="codex_stale",
        state=StatusState(64, False, "ble", 1, _PROFILES_CONNECTED, _PROFILES_BONDED, 0),
        frame=kp4.codex_card(
            "3h5m", 45, "5d", 12, led_hint=0, row_roles=(0, 0, 1, 0, 1, 0), generation=_DEMO_GENERATION
        ),
        stale=True,
    ),
    PreviewCase(
        # The real two-card deck (claude + codex): viewing page 2/2 shows the
        # page rail with the thumb riding to the right.
        name="claude_codex_deck",
        state=StatusState(78, False, "ble", 0, _PROFILES_CONNECTED, _PROFILES_BONDED, 0),
        frame=kp4.codex_card(
            "1h5m", 33, "6d", 8, led_hint=0, row_roles=(0, 0, 1, 0, 1, 0), generation=_DEMO_GENERATION, index=1, total=2
        ),
    ),
    PreviewCase(
        # Open (unbonded) active profile -> LV_SYMBOL_SETTINGS; no frame ever
        # received -> centered NO DATA / WAITING tip.
        name="no_data_waiting",
        state=StatusState(15, False, "ble", 2, _PROFILES_CONNECTED, _PROFILES_BONDED, 2, "SYMBOL"),
    ),
)


def scale_image(image: Image.Image, scale: int) -> Image.Image:
    if scale <= 1:
        return image
    return image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)


def write_preview_set(output_dir: Path, scale: int = 4) -> list[Path]:
    """Regenerate the whole preview set.

    Every PNG already in the directory is dropped first: the directory holds
    nothing but this renderer's output, so renaming or removing a demo case
    cannot leave a stale image behind pretending to be current.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for previous in output_dir.glob("*.png"):
        if previous.is_file():
            previous.unlink()

    written: list[Path] = []
    for case in DEMO_CASES:
        image = render_left_screen(case.state, case.frame, stale=case.stale)
        output = output_dir / f"left_screen_{case.name}.png"
        scale_image(image, scale).save(output)
        written.append(output)
    return written


def write_frame_preview(frame: str, output: Path, scale: int = 4, stale: bool = False) -> Path:
    """Producer helper: validate one KP4 frame and render the resulting glass."""
    image = render_left_screen(DEMO_CASES[0].state, frame, stale=stale)
    output.parent.mkdir(parents=True, exist_ok=True)
    scale_image(image, scale).save(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Render pixel-exact KEYPOINT left-screen (72x144 glass) previews.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tmp/status-preview"),
        help="Where the PNGs land. The demo set regenerates it: every PNG already there is dropped first.",
    )
    parser.add_argument("--scale", type=int, default=4)
    parser.add_argument("--frame", help="Render this single KP4 frame instead of the demo set.")
    parser.add_argument("--stale", action="store_true", help="Render --frame in the stale state.")
    args = parser.parse_args()

    if args.frame:
        print(write_frame_preview(args.frame, args.output_dir / "left_screen_frame.png", args.scale, args.stale))
        return

    for path in write_preview_set(args.output_dir, scale=args.scale):
        print(path)


if __name__ == "__main__":
    main()
