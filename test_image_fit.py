"""Adjusting an image to a slot's exact size: the placement maths (no window needed)."""
from image_fit import image_rect


def test_fill_covers_the_frame_and_crops_the_long_side():
    r = image_rect(1600, 1000, 1080, 1602, 'fill')
    assert r.height() == 1602 and r.width() > 1080          # wide image: height fits, sides cropped
    assert abs(r.x() + r.width() / 2 - 540) < 1e-6           # centred


def test_fill_offset_shows_the_left_edge():
    r = image_rect(1600, 1000, 1080, 1602, 'fill', 1.0, (-1.0, 0.0))
    assert abs(r.x()) < 1e-6                                 # left edge of the image at the frame's left


def test_fit_keeps_the_whole_image_inside():
    r = image_rect(1600, 1000, 1080, 1602, 'fit')
    assert r.width() == 1080 and r.height() < 1602


def test_stretch_fills_exactly():
    r = image_rect(1600, 1000, 1080, 1602, 'stretch')
    assert (r.x(), r.y(), r.width(), r.height()) == (0, 0, 1080, 1602)
