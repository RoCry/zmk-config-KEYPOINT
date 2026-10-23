"""Full-glass regressions from the photographed white surface and image gap."""

from pathlib import Path

import pytest
from keypoint_native import render_left_screen, render_right_screen, right_images
from lpm_c_array_preview import decode_c_array_preview
from PIL import Image
from test_keypoint_status_preview import BLACK, FRAME, STATE


def test_full_glass_background_is_black_including_unoccupied_bottom_edge():
    image = render_left_screen(STATE, FRAME)
    assert image.getpixel((71, 143)) == BLACK
    assert image.getpixel((0, 24)) == BLACK


GALLERY = ("al_pacino", "favorite_69b97550", "rezaul_karim", "minion")


def test_gallery_contains_only_the_four_approved_fullscreen_pictures():
    assert right_images() == GALLERY


@pytest.mark.parametrize("name", GALLERY)
def test_fullscreen_portrait_reaches_bottom_below_one_black_status_strip(name):
    source = Path(__file__).resolve().parents[1] / f"config/boards/shields/lpm_view/widgets/picture/{name}.c"
    original = decode_c_array_preview(source).convert("RGB").transpose(Image.Transpose.ROTATE_270)
    # Exercise repeated overlay updates, including the charging glyph. The
    # independent indexed-image decoder is the oracle for unoccluded pixels.
    for charging in (False, True, False):
        glass = render_right_screen(image=name, charging=charging)
        assert glass.crop((0, 18, 72, 144)).tobytes() == original.crop((0, 18, 72, 144)).tobytes()
        assert set(glass.crop((34, 0, 52, 18)).get_flattened_data()) == {BLACK}
        assert glass.getpixel((33, 17)) == BLACK
