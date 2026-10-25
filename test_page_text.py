"""Tests for typed-text page rendering (page_text)."""
import tempfile

import numpy as np
from PIL import Image

from page_text import text_image, text_png, wrap_lines


def test_blank_text_gives_none():
    assert text_image('', 400, 560) is None
    assert text_image('   ', 400, 560) is None


def test_text_image_has_ink():
    img = text_image('The Truth Project', 400, 560)
    assert img is not None and img.size == (400, 560)
    a = np.array(img)[..., 3]
    assert a.max() > 200                     # some fully opaque ink
    assert a.min() == 0                       # transparent background
    assert (a > 0).sum() > 500                # a visible amount of text


def test_wrap_breaks_long_lines():
    from PIL import ImageDraw
    d = ImageDraw.Draw(Image.new('RGBA', (10, 10)))
    from page_text import _font
    f = _font(24)
    lines = wrap_lines(d, 'one two three four five six', f, 60)
    assert len(lines) > 1
    assert all(d.textlength(ln, font=f) <= 60 for ln in lines)


def test_text_png_writes_file():
    with tempfile.TemporaryDirectory() as tmp:
        p = tmp + '/page.png'
        assert text_png('Hello', p, 400, 560)
        img = Image.open(p)
        assert img.size == (400, 560)
        assert np.array(img)[..., 3].max() > 0


def test_sides_to_images_maps_text_to_png():
    from page_text import sides_to_images
    with tempfile.TemporaryDirectory() as tmp:
        sides = ['/x/a.png', None, {'kind': 'text', 'text': 'Once upon a time'}, {'kind': 'blank'}]
        imgs = sides_to_images(sides, tmp, page_aspect=1.4)
        assert imgs[0] == '/x/a.png'
        assert imgs[1] is None
        assert imgs[2] and imgs[2].startswith(tmp) and imgs[2].endswith('.png')
        assert imgs[3] is None
        assert Image.open(imgs[2]).size[0] == 700


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
