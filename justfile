default:
    @just --list

test:
    uv run scripts/check.py -q

preview:
    uv run scripts/build_preview.py
    uv run scripts/preview_keypoint_status.py
