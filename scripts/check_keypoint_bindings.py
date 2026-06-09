#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYMAPS = [
    ROOT / "config/boards/arm/zitaotech_keypoint/zitaotech_keypoint.keymap",
    ROOT / "config/keypoint.keymap",
]
LEFT_DTS = ROOT / "config/boards/arm/zitaotech_keypoint/zitaotech_keypoint_left.dts"

BINDING_CELLS = {
    "&bl": 1,
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
    40: "&kp UP",  # reserve layer removed; right key is plain Up
    45: "&kp C_MUTE",  # left encoder press
    47: "&mt LGUI ESC",  # left thumb: hold Command, tap Escape
    51: "&mt LC(LA(LS(LGUI))) RALT",  # right Alt: hold Hyper, tap right Alt
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


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*", "", text)


def normalize_dts(text: str) -> str:
    return re.sub(r"\s+", " ", strip_comments(text)).strip()


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

    left_dts_text = LEFT_DTS.read_text()
    normalized_left_dts = normalize_dts(left_dts_text)
    for expected in [
        "#define TRACKPOINT_POINTING_LAYER 4",
        "#define TRACKPOINT_POINTING_TIMEOUT_MS 1500",
        "<&zip_temp_layer TRACKPOINT_POINTING_LAYER TRACKPOINT_POINTING_TIMEOUT_MS>",
    ]:
        if expected not in normalized_left_dts:
            failures.append(f"{LEFT_DTS}: missing TrackPoint pointing-layer wiring {expected!r}")

    for keymap in KEYMAPS:
        text = keymap.read_text()

        normalized_text = normalize_dts(text)
        for removed in ["#define RES", "RES_layer", 'display-name = "RESERVE";', "&lt RES UP"]:
            if removed in normalized_text:
                failures.append(f"{keymap}: removed reserve-layer marker still present: {removed!r}")

        default_bindings = layer_bindings(text, "default_layer")
        if len(default_bindings) != 56:
            failures.append(f"{keymap}: default_layer has {len(default_bindings)} bindings, expected 56")
            continue

        for index, expected in EXPECTED_DEFAULT_BINDINGS.items():
            actual = default_bindings[index]
            if actual != expected:
                failures.append(f"{keymap}: default_layer[{index}] is {actual!r}, expected {expected!r}")

        lower_bindings = layer_bindings(text, "lower_layer")
        if len(lower_bindings) != 56:
            failures.append(f"{keymap}: lower_layer has {len(lower_bindings)} bindings, expected 56")
            continue

        for index, expected in EXPECTED_LOWER_BINDINGS.items():
            actual = lower_bindings[index]
            if actual != expected:
                failures.append(f"{keymap}: lower_layer[{index}] is {actual!r}, expected {expected!r}")

        try:
            pointing_bindings = layer_bindings(text, "pointing_layer")
        except ValueError:
            failures.append(f"{keymap}: missing pointing_layer")
            continue

        if len(pointing_bindings) != 56:
            failures.append(f"{keymap}: pointing_layer has {len(pointing_bindings)} bindings, expected 56")
            continue

        for index, expected in EXPECTED_POINTING_BINDINGS.items():
            actual = pointing_bindings[index]
            if actual != expected:
                failures.append(f"{keymap}: pointing_layer[{index}] is {actual!r}, expected {expected!r}")

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
