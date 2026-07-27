#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIMARY_KEYMAP = ROOT / "config/keypoint.keymap"
BOARD_KEYMAP = ROOT / "config/boards/arm/zitaotech_keypoint/zitaotech_keypoint.keymap"
KEYMAPS = [
    BOARD_KEYMAP,
    PRIMARY_KEYMAP,
]
BOARD_KEYMAP_INCLUDE = '#include "../../../keypoint.keymap"'

# In the order ZMK numbers them. tests/test_pointing_layers.py owns the claim
# that these indices match the keymap's #defines and the board file's layer
# numbers; nothing here may restate a layer number.
LAYER_NAMES = (
    "default_layer",
    "lower_layer",
    "symbol_layer",
    "fn_layer",
    "pointing_layer",
)

BINDING_CELLS = {
    "&bl": 1,
    "&bootloader": 0,
    "&bt": 1,
    "&cmd_grave": 0,
    "&cmd_space": 0,
    "&gresc": 0,
    "&kp": 1,
    "&lt": 2,
    "&mkp": 1,
    "&mo": 1,
    "&msc": 1,
    "&mt": 2,
    "&none": 0,
    "&trans": 0,
}

EXPECTED_DEFAULT_BINDINGS = {
    18: "&mkp LCLK",  # left pointing-device click key
    19: "&mkp LCLK",  # right pointing-device click key
    32: "&none",  # left center-cluster: live-data NEXT page (driven by live_data.c listener)
    33: "&none",  # left center-cluster: live-data PREV page (driven by live_data.c listener)
    35: "&mkp RCLK",  # right center-cluster: the only right click on this layer
    40: "&kp UP",  # reserve layer removed; right key is plain Up
    45: "&kp C_MUTE",  # left encoder press
    47: "&mt LGUI ESC",  # left thumb: hold Command, tap Escape
    51: "&mt LC(LA(LS(LGUI))) RALT",  # right Alt: hold Hyper, tap right Alt
    52: "&kp C_PP",  # right encoder press: play/pause, mirroring Mute on the left
}

EXPECTED_LOWER_BINDINGS = {
    1: "&kp N1",
    2: "&kp N2",
    3: "&kp N3",
    4: "&kp N0",
    5: "&kp N0",
    13: "&kp N4",
    14: "&kp N5",
    15: "&kp N6",
    16: "&kp N0",
    17: "&kp N0",
    27: "&kp N7",
    28: "&kp N8",
    29: "&kp N9",
    30: "&kp N0",
    31: "&cmd_grave",  # Cmd+` window switch macro
}

EXPECTED_SYMBOL_BINDINGS: dict[int, str] = {}

# Both encoder presses, and nowhere else. LOWER and SYMBOL are held to put a
# pointing device into scroll mode, so the bootloader may not live there --
# tests/test_live_data_contract.py states that rule and enforces it.
EXPECTED_FN_BINDINGS = {
    45: "&bootloader",  # left encoder press
    52: "&bootloader",  # right encoder press
}

EXPECTED_MACROS = {
    "cmd_space": "bindings = <&macro_press &kp LGUI>, <&macro_tap &kp SPACE>, <&macro_release &kp LGUI>;",
    "cmd_grave": "bindings = <&macro_press &kp LGUI>, <&macro_tap &kp GRAVE>, <&macro_release &kp LGUI>;",
}

EXPECTED_COMBOS = {
    "combo_jk_cmd_space": "key-positions = <21 22>;",
    "combo_df_cmd_space": "key-positions = <15 16>;",
}

EXPECTED_POINTING_BINDINGS = {
    49: "&mkp LCLK",  # right thumb BSPC position becomes left click while pointing
    50: "&mkp RCLK",  # right thumb TAB position becomes right click while pointing
}

KEY_COUNT = 56

EXPECTED_BINDINGS = {
    "default_layer": EXPECTED_DEFAULT_BINDINGS,
    "lower_layer": EXPECTED_LOWER_BINDINGS,
    "symbol_layer": EXPECTED_SYMBOL_BINDINGS,
    "fn_layer": EXPECTED_FN_BINDINGS,
    "pointing_layer": EXPECTED_POINTING_BINDINGS,
}
assert tuple(EXPECTED_BINDINGS) == LAYER_NAMES, "every layer needs an expectations table, even an empty one"


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*", "", text)


def normalize_dts(text: str) -> str:
    return re.sub(r"\s+", " ", strip_comments(text)).strip()


def read_keymap_text(path: Path, seen: set[Path] | None = None) -> str:
    seen = set() if seen is None else seen
    path = path.resolve()
    if path in seen:
        raise AssertionError(f"recursive include while reading {path}")
    seen.add(path)

    text = path.read_text()

    def expand_include(match: re.Match[str]) -> str:
        include_path = path.parent / match.group(1)
        return read_keymap_text(include_path, seen)

    return re.sub(r'#include\s+"([^"]+)"', expand_include, text)


def node_block(text: str, marker: str) -> str:
    marker_start = text.index(marker)
    block_start = text.index("{", marker_start)

    depth = 0
    for index, char in enumerate(text[block_start:], start=block_start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[block_start : index + 1]

    raise AssertionError(f"unclosed node {marker!r}")


def layer_bindings(text: str, layer_name: str) -> list[str]:
    marker = f"{layer_name} {{"
    layer_start = text.index(marker)
    bindings_start = text.index("bindings", layer_start)
    block_start = text.index("<", bindings_start)
    block_end = text.index(">;", block_start)
    tokens = strip_comments(text[block_start + 1 : block_end]).split()

    bindings: list[str] = []
    i = 0
    while i < len(tokens):
        behavior = tokens[i]
        if not behavior.startswith("&"):
            raise AssertionError(f"unexpected bare token {behavior!r} in {layer_name}")

        cell_count = BINDING_CELLS.get(behavior)
        if behavior == "&bt" and i + 1 < len(tokens) and tokens[i + 1] == "BT_SEL":
            cell_count = 2
        if cell_count is None:
            raise AssertionError(f"unknown behavior {behavior!r} in {layer_name}")

        end = i + 1 + cell_count
        bindings.append(" ".join(tokens[i:end]))
        i = end

    return bindings


def main() -> None:
    failures: list[str] = []

    board_keymap_text = BOARD_KEYMAP.read_text()
    if BOARD_KEYMAP_INCLUDE not in board_keymap_text:
        failures.append(f"{BOARD_KEYMAP}: should include the primary keymap with {BOARD_KEYMAP_INCLUDE!r}")
    if 'compatible = "zmk,keymap";' in strip_comments(board_keymap_text):
        failures.append(
            f"{BOARD_KEYMAP}: should not duplicate keymap bindings; keep {PRIMARY_KEYMAP} as source of truth"
        )

    for keymap in KEYMAPS:
        text = read_keymap_text(keymap)

        normalized_text = normalize_dts(text)
        for removed in ["#define RES", "RES_layer", 'display-name = "RESERVE";', "&lt RES UP"]:
            if removed in normalized_text:
                failures.append(f"{keymap}: removed reserve-layer marker still present: {removed!r}")

        layers: dict[str, list[str]] = {}
        for layer_name in LAYER_NAMES:
            try:
                bindings = layer_bindings(text, layer_name)
            except ValueError:
                failures.append(f"{keymap}: missing {layer_name}")
                continue

            if len(bindings) != KEY_COUNT:
                failures.append(f"{keymap}: {layer_name} has {len(bindings)} bindings, expected {KEY_COUNT}")
                continue

            layers[layer_name] = bindings
            for index, expected in EXPECTED_BINDINGS[layer_name].items():
                if (actual := bindings[index]) != expected:
                    failures.append(f"{keymap}: {layer_name}[{index}] is {actual!r}, expected {expected!r}")

        if "&bt BT_CLR" in layers.get("lower_layer", []):
            failures.append(f"{keymap}: lower_layer should not contain BT_CLR")

        for macro_name, expected_bindings in EXPECTED_MACROS.items():
            try:
                macro = normalize_dts(node_block(text, f"{macro_name}: {macro_name}"))
            except ValueError:
                failures.append(f"{keymap}: missing macro {macro_name!r}")
                continue

            if 'compatible = "zmk,behavior-macro";' not in macro:
                failures.append(f"{keymap}: macro {macro_name!r} is not a zmk behavior macro")
            if "#binding-cells = <0>;" not in macro:
                failures.append(f"{keymap}: macro {macro_name!r} should take no binding cells")
            if expected_bindings not in macro:
                failures.append(f"{keymap}: macro {macro_name!r} should contain {expected_bindings!r}")

        for combo_name, key_positions in EXPECTED_COMBOS.items():
            try:
                combo = normalize_dts(node_block(text, combo_name))
            except ValueError:
                failures.append(f"{keymap}: missing {combo_name}")
                continue

            for expected in [
                "timeout-ms = <50>;",
                key_positions,
                "bindings = <&cmd_space>;",
                "layers = <0>;",
            ]:
                if expected not in combo:
                    failures.append(f"{keymap}: {combo_name} should contain {expected!r}")

    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
