"""Pictures placed on a page, like layers in After Effects, and "Ink on the page".

A page side can carry any number of layers. Each layer is a picture with a place on the page
(centre x/y as a fraction of the page, width as a fraction of the page width, rotation,
opacity) and, optionally, "Ink on the page" (ported from StrokeScribe's picture_look.py):
the picture's own paper tone becomes see-through and its lines become ink, so it looks
printed on whatever page it sits on, with the page's grain showing through and no square
around it. Its edges can fade softly or in an oval.

The layers are flattened here into one transparent page-size PNG, so the live preview and
the Blender render receive the very same picture (transparent areas show the book's paper).
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

EDGES = {'Soft edges': 'soft', 'Oval fade': 'oval', 'No fading': 'none'}
INK_COLOURS = {'Dark grey (like printed text)': (41, 41, 44), 'Black': (12, 12, 12),
               'Sepia': (74, 52, 34), 'Brown ink': (60, 38, 22), "The picture's own colours": None}

LAYER_DEFAULTS = dict(image='', x=0.5, y=0.5, w=0.6, rot=0.0, opacity=100.0, flip=False,
                      ink_on=True, ink_edges='Soft edges', ink_removal=50.0, ink_strength=100.0,
                      ink_colour='Dark grey (like printed text)', ink_edge_size=15.0)
INK_MAX = 2048            # the ink is worked out on at most this many pixels across (speed)


def new_layer(image, **kw):
    d = dict(LAYER_DEFAULTS)
    d.update(kw, image=str(image))
    return d


def layer_get(layer, key):
    return layer.get(key, LAYER_DEFAULTS[key])


# ---------------------------------------------------------------- ink (from StrokeScribe)
def _lum(rgb):
    return rgb[..., 0] * .299 + rgb[..., 1] * .587 + rgb[..., 2] * .114


def ink(rgba, removal=50., strength=100., colour_rgb=(41, 41, 44)):
    """Ink with transparency: paper tone -> see-through, lines -> ink. rgba: float 0..1."""
    rgb, alpha = rgba[..., :3], rgba[..., 3]
    lum = _lum(rgb)
    seen = alpha > .25
    values = lum[seen] if seen.any() else lum.ravel()
    # The picture's own paper: the bright end of its tones. More removal = a darker tone counts as paper.
    white = np.percentile(values, 99. - .6 * float(removal))
    # The darkest ink: at least a little darker than the paper, so a picture that is all
    # paper (one even tone) comes out see-through, not as one block of ink.
    black = min(float(np.percentile(values, 1.)), float(white) - .2)
    t = np.clip((lum - black) / max(1e-3, white - black), 0, 1)
    amount = (1 - t) * (float(strength) / 100.)
    out = np.empty_like(rgba)
    if colour_rgb is None:
        out[..., :3] = rgb                                        # the picture's own colours, as ink
    else:
        out[..., :3] = np.asarray(colour_rgb, np.float32) / 255.
    out[..., 3] = np.clip(amount, 0, 1) * alpha
    return out


def edge_fade(h, w, edges='soft', edge_size=15.):
    """0..1 mask that fades the picture's edges (soft rectangle or oval); None = no fading."""
    if edges not in ('soft', 'oval') or edge_size <= 0:
        return None
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if edges == 'soft':
        d = np.minimum.reduce([xx, w - 1 - xx, yy, h - 1 - yy])
        f = np.clip(d / max(1., edge_size / 100. * min(w, h)), 0, 1)
    else:
        r = np.sqrt(((xx - (w - 1) / 2) / (w / 2)) ** 2 + ((yy - (h - 1) / 2) / (h / 2)) ** 2)
        f = np.clip((1 - r) / max(.02, edge_size / 100. * 3), 0, 1)
    return f * f * (3 - 2 * f)


def layer_picture(layer, max_side=INK_MAX):
    """The layer's picture (PIL RGBA) with its look applied, before placing it on the page."""
    img = Image.open(layer_get(layer, 'image')).convert('RGBA')
    if max(img.size) > max_side:
        s = max_side / max(img.size)
        img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
    if layer_get(layer, 'flip'):
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    a = np.asarray(img, np.float32) / 255.
    if layer_get(layer, 'ink_on'):
        a = ink(a, float(layer_get(layer, 'ink_removal')), float(layer_get(layer, 'ink_strength')),
                INK_COLOURS.get(layer_get(layer, 'ink_colour'), INK_COLOURS['Dark grey (like printed text)']))
    else:
        a = a.copy()
    fade = edge_fade(a.shape[0], a.shape[1], EDGES.get(layer_get(layer, 'ink_edges'), 'none'),
                     float(layer_get(layer, 'ink_edge_size')))
    if fade is not None:
        a[..., 3] *= fade
    a[..., 3] *= max(0., min(1., float(layer_get(layer, 'opacity')) / 100.))
    return Image.fromarray(np.ascontiguousarray((np.clip(a, 0, 1) * 255 + .5).astype(np.uint8)), 'RGBA')


def placed_size(layer, src_size, page_size):
    """Pixel size of the layer on the page (before rotation), keeping the picture's shape."""
    pw, _ = page_size
    w = max(1, round(float(layer_get(layer, 'w')) * pw))
    h = max(1, round(w * src_size[1] / max(1, src_size[0])))
    return w, h


def place(page, picture, layer):
    """Paste `picture` (PIL RGBA) onto `page` (PIL RGBA, modified) where the layer says."""
    pw, ph = page.size
    w, h = placed_size(layer, picture.size, page.size)
    pic = picture.resize((w, h), Image.LANCZOS)
    rot = float(layer_get(layer, 'rot'))
    if abs(rot) > 1e-3:
        pic = pic.rotate(-rot, resample=Image.BICUBIC, expand=True)   # positive = clockwise on the page
    cx, cy = float(layer_get(layer, 'x')) * pw, float(layer_get(layer, 'y')) * ph
    x0, y0 = round(cx - pic.width / 2), round(cy - pic.height / 2)
    # alpha_composite needs the destination inside the page: crop the part that lands on it
    sx, sy = max(0, -x0), max(0, -y0)
    ex, ey = min(pic.width, pw - x0), min(pic.height, ph - y0)
    if ex > sx and ey > sy:
        page.alpha_composite(pic.crop((sx, sy, ex, ey)), (x0 + sx, y0 + sy))
    return page


def layer_corners(layer, src_size, page_size):
    """The four corners (page pixels) of the placed, rotated layer - for drawing its frame."""
    w, h = placed_size(layer, src_size, page_size)
    cx, cy = float(layer_get(layer, 'x')) * page_size[0], float(layer_get(layer, 'y')) * page_size[1]
    a = math.radians(float(layer_get(layer, 'rot')))
    c, s = math.cos(a), math.sin(a)
    out = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        out.append((cx + dx * c - dy * s, cy + dx * s + dy * c))
    return out


def compose(base, layers, size):
    """The page side as one transparent PIL image: the base page picture (stretched to the page,
    as the render shows it) with every layer on top, first layer at the bottom."""
    page = Image.new('RGBA', (int(size[0]), int(size[1])), (0, 0, 0, 0))
    if base and Path(base).exists():
        b = Image.open(base).convert('RGBA')
        if b.size != page.size:
            b = b.resize(page.size, Image.LANCZOS)
        page.alpha_composite(b)
    for layer in layers or []:
        if layer_get(layer, 'image') and Path(layer_get(layer, 'image')).exists():
            place(page, layer_picture(layer), layer)
    return page


def _stamp(p):
    try:
        st = Path(p).stat()
        return [str(p), st.st_mtime_ns, st.st_size]
    except OSError:
        return [str(p), 0, 0]


def compose_to_file(base, layers, size, out_dir):
    """compose() saved as a PNG in out_dir (reused while nothing changed); returns its path."""
    key = json.dumps([_stamp(base) if base else None, [int(size[0]), int(size[1])],
                      [dict(l, _src=_stamp(layer_get(l, 'image'))) for l in layers]], sort_keys=True)
    out = Path(out_dir) / f'layers_{hashlib.sha1(key.encode()).hexdigest()[:16]}.png'
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix('.tmp.png')
        compose(base, layers, size).save(tmp)
        tmp.replace(out)
    return str(out)
