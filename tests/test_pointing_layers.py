"""The layer numbers the pointing devices depend on, held across two files.

The TrackPoint does not decide for itself when to scroll. The right half only
ever reports cursor motion; the central half's `trackpoint_listener` remaps
those axes to the wheel while a layer is held, and raises a second layer for a
moment after any motion so the thumb keys can act as mouse buttons.

Both of those are plain integers in `zitaotech_keypoint_left.dts`, and the
layers they name live in `keypoint.keymap` -- a different file, with its own
`#define`s, that the board file cannot see. Nothing in the build connects them.
Reorder the layer nodes, or renumber a `#define`, and the firmware still
compiles and flashes: the TrackPoint simply stops scrolling, or POINTING lands
on the wrong layer. That is the failure this module exists to catch.

Note the layer *numbers* are positional -- a layer's index is where its node
sits in the keymap, not what any `#define` says -- so that is what gets derived
here, and the `#define`s are checked against it rather than trusted.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KEYMAP = ROOT / "config/keypoint.keymap"
LEFT_BOARD = ROOT / "config/boards/arm/zitaotech_keypoint/zitaotech_keypoint_left.dts"

# keymap `#define` -> the layer node it names. The default layer is index 0 and
# has no #define; every other layer must be listed here.
LAYER_DEFINES = {
    "LOWER": "lower_layer",
    "SYMBOL": "symbol_layer",
    "FN": "fn_layer",
    "POINTING": "pointing_layer",
}


def _defines(source: str) -> dict[str, int]:
    """Every `#define NAME <int>` in a file."""
    return {name: int(value) for name, value in re.findall(r"^#define\s+(\w+)\s+(\d+)\s*$", source, re.MULTILINE)}


def _layer_order(source: str) -> list[str]:
    """The keymap's layer nodes, in the order ZMK numbers them."""
    keymap_block = re.search(r"keymap\s*\{(.*)\n\s*\};\s*\n\s*\};", source, re.DOTALL)
    assert keymap_block, "no keymap node found in keypoint.keymap"

    return re.findall(r"^\s{8}(\w+)\s*\{", keymap_block.group(1), re.MULTILINE)


KEYMAP_SOURCE = KEYMAP.read_text()
BOARD_SOURCE = LEFT_BOARD.read_text()

KEYMAP_DEFINES = _defines(KEYMAP_SOURCE)
BOARD_DEFINES = _defines(BOARD_SOURCE)
LAYER_ORDER = _layer_order(KEYMAP_SOURCE)


def test_the_keymap_declares_the_layers_this_module_knows_about() -> None:
    """A new layer must be taught to this file before it can silently break one."""
    assert LAYER_ORDER[0] == "default_layer", "layer 0 is the default layer by construction"
    assert LAYER_ORDER[1:] == list(LAYER_DEFINES.values()), (
        f"keymap layer nodes {LAYER_ORDER[1:]} no longer match {list(LAYER_DEFINES.values())}; "
        "update LAYER_DEFINES, and check every layer number in zitaotech_keypoint_left.dts"
    )


@pytest.mark.parametrize(("define", "node"), LAYER_DEFINES.items())
def test_each_keymap_define_matches_its_layers_real_index(define: str, node: str) -> None:
    """`#define LOWER 1` is a claim about position; here it has to earn it."""
    assert define in KEYMAP_DEFINES, f"keypoint.keymap no longer defines {define}"
    assert KEYMAP_DEFINES[define] == LAYER_ORDER.index(node), (
        f"{define} is defined as {KEYMAP_DEFINES[define]} but {node} sits at index {LAYER_ORDER.index(node)}"
    )


def test_the_trackpoint_scrolls_on_the_layer_the_keymap_calls_lower() -> None:
    """The scroll gesture: hold a LOWER layer-tap, push the TrackPoint.

    A layer-tap held sends nothing to the host, which is the whole reason this
    lives on a layer rather than on a mod-tap. If these two numbers drift, the
    gesture goes dead with no other symptom.
    """
    assert BOARD_DEFINES["TRACKPOINT_SCROLL_LAYER"] == KEYMAP_DEFINES["LOWER"]


def test_the_trackpoint_raises_the_layer_the_keymap_calls_pointing() -> None:
    """Any TrackPoint motion raises POINTING for a moment, where the thumb keys
    become mouse buttons. Point it at the wrong layer and it rewrites whichever
    layer that is, mid-typing."""
    assert BOARD_DEFINES["TRACKPOINT_POINTING_LAYER"] == KEYMAP_DEFINES["POINTING"]


def test_the_listener_uses_the_named_scroll_layer_and_not_a_bare_number() -> None:
    """The check above only bites while the listener reads the macro.

    `layers = <1>;` would compile identically and silently escape every
    assertion in this file.
    """
    listener = re.search(r"&trackpoint_listener\s*\{(.*?)\n\};", BOARD_SOURCE, re.DOTALL)
    assert listener, "no &trackpoint_listener override found in zitaotech_keypoint_left.dts"

    assert "layers = <TRACKPOINT_SCROLL_LAYER>;" in listener.group(1), (
        "the TrackPoint scroll layer must be spelled TRACKPOINT_SCROLL_LAYER, "
        "or the keymap can renumber LOWER without failing a test"
    )
    assert "<&zip_temp_layer TRACKPOINT_POINTING_LAYER" in listener.group(1)


def test_the_trackpoint_scroll_chain_inverts_the_vertical_axis() -> None:
    """Remapping X/Y onto the wheel needs a Y flip, and it is not a preference.

    REL_X and HWHEEL are both positive-right, but REL_Y is positive-*down* while
    WHEEL is positive-*up*. A code mapper only rewrites the code, so without this
    the TrackPoint scrolls backwards: push up, page goes down -- and it disagrees
    with the trackpad, which negates this exact axis in a320.c.

    Drop the transform and nothing breaks loudly; scrolling just runs the wrong
    way. Order matters too: the transform acts on the wheel codes, so it has to
    come after the mapper that produces them.
    """
    listener = re.search(r"&trackpoint_listener\s*\{(.*?)\n\};", BOARD_SOURCE, re.DOTALL)
    assert listener, "no &trackpoint_listener override found in zitaotech_keypoint_left.dts"

    mapper = listener.group(1).find("&zip_xy_to_scroll_mapper")
    invert = listener.group(1).find("&zip_scroll_transform INPUT_TRANSFORM_Y_INVERT")

    assert mapper != -1, "the TrackPoint scroll chain must map cursor axes to the wheel"
    assert invert != -1, "the TrackPoint scroll chain must invert the wheel's Y axis"
    assert mapper < invert, "the wheel Y invert has to run after the mapper that creates the wheel codes"
