#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
KEYMAPS = [
    ROOT / "config/boards/arm/zitaotech_keypoint/zitaotech_keypoint.keymap",
    ROOT / "config/keypoint.keymap",
]

BINDING_CELLS = {
    "&bl": 1,
    "&bt": 1,
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
    18: "&mkp LCLK",      # left pointing-device click key
    19: "&mkp LCLK",      # right pointing-device click key
    45: "&kp C_MUTE",     # left encoder press
    47: "&mt LGUI ESC",   # left thumb: hold Command, tap Escape
}


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*", "", text)


def layer_bindings(text: str, layer_name: str) -> list[str]:
    marker = f"{layer_name} {{"
    layer_start = text.index(marker)
    bindings_start = text.index("bindings", layer_start)
    block_start = text.index("<", bindings_start)
    block_end = text.index(">;", block_start)
    tokens = strip_comments(text[block_start + 1:block_end]).split()

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

    for keymap in KEYMAPS:
        bindings = layer_bindings(keymap.read_text(), "default_layer")
        if len(bindings) != 56:
            failures.append(f"{keymap}: default_layer has {len(bindings)} bindings, expected 56")
            continue

        for index, expected in EXPECTED_DEFAULT_BINDINGS.items():
            actual = bindings[index]
            if actual != expected:
                failures.append(
                    f"{keymap}: default_layer[{index}] is {actual!r}, expected {expected!r}"
                )

    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
