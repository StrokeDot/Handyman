"""The shape of a cover image: how round its corners are (read from its transparent pixels), and a
copy of it with the transparent pixels filled with the colour next to them.

The 3D cover board is cut with the image's own corner radius, so a cover drawn with rounded
corners gets a rounded board (the live view and the render alike). Where the board still covers a
transparent pixel (the corners on the spine side, a worn edge) it shows the leather beside it,
never black.
"""
import hashlib
import math
from pathlib import Path

import numpy as np

DEFAULT_CORNER = 0.035 / 1.08    # fore-edge corner radius as a share of the board width (no transparency)
_CACHE = {}


def _alpha(path):
    from PIL import Image
    with Image.open(path) as im:
        if im.mode not in ('RGBA', 'LA', 'PA') and 'transparency' not in im.info:
            return None, im.size
        return np.asarray(im.convert('RGBA'))[..., 3], im.size


def corner_radius(path, side='right'):
    """Fore-edge corner radius of a cover image as a share of its width (side: which edge is the
    fore edge in the image - 'right' for a front cover's outside). DEFAULT_CORNER when it has no
    transparent corners."""
    if not path or not Path(path).exists():
        return DEFAULT_CORNER
    try:
        key = ('r', str(path), Path(path).stat().st_mtime_ns, side)
        if key in _CACHE:
            return _CACHE[key]
        a, (w, h) = _alpha(path)
        r = DEFAULT_CORNER
        if a is not None:
            cx = w - 1 if side == 'right' else 0
            dx = -1 if side == 'right' else 1
            ds = []
            for cy, dy in ((0, 1), (h - 1, -1)):
                t = 0
                while t < min(w, h) // 3 and a[cy + dy * t, cx + dx * t] <= 128:
                    t += 1
                ds.append(t)
            d = sum(ds) / 2.0
            if d >= 1.0:
                # a rounded corner of radius r leaves r * (sqrt 2 - 1) clear along the diagonal; each
                # diagonal step is sqrt 2 pixels long (+1.5 px: the cut stays inside the art)
                r = min(0.3, (d * math.sqrt(2) / (math.sqrt(2) - 1.0) + 1.5) / w)
        _CACHE[key] = r
        return r
    except Exception:
        return DEFAULT_CORNER


def filled(path, out_dir):
    """Path of a copy of the image whose transparent pixels take the colour of the nearest opaque
    pixel (the original when nothing is transparent)."""
    if not path or not Path(path).exists():
        return path
    try:
        st = Path(path).stat()
        tag = hashlib.sha1(f'{path}|{st.st_mtime_ns}|{st.st_size}'.encode()).hexdigest()[:16]
        out = Path(out_dir) / f'filled_{tag}.png'
        if out.exists():
            return str(out)
        from PIL import Image
        a, _ = _alpha(path)
        if a is None or a.min() > 250:
            return str(path)
        with Image.open(path) as im:
            rgba = np.asarray(im.convert('RGBA')).astype(np.float32)
        rgb, have = rgba[..., :3].copy(), rgba[..., 3] > 128
        for _ in range(96):                      # grow the colours into the transparent pixels
            if have.all():
                break
            acc = np.zeros_like(rgb)
            cnt = np.zeros(have.shape, np.float32)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    sh = np.roll(np.roll(have, dy, 0), dx, 1)
                    acc += np.roll(np.roll(rgb, dy, 0), dx, 1) * sh[..., None]
                    cnt += sh
            new = (~have) & (cnt > 0)
            rgb[new] = acc[new] / cnt[new][:, None]
            have = have | new
        if not have.all():
            rgb[~have] = rgb[have].mean(axis=0)
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        img = np.dstack([rgb, np.full(have.shape, 255.0)]).clip(0, 255).astype(np.uint8)
        Image.fromarray(img, 'RGBA').save(out)
        return str(out)
    except Exception:
        return str(path)


def edge_colour(path):
    """The cover's colour near its edge (0..1 RGB), for the board's edges: the leather band just
    inside the outer rim of the cover picture. None when the picture can't be read."""
    if not path or not Path(path).exists():
        return None
    try:
        key = ('e', str(path), Path(path).stat().st_mtime_ns)
        if key in _CACHE:
            return _CACHE[key]
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert('RGBA')
            im.thumbnail((400, 400))
            a = np.asarray(im).astype(np.float32)
        h, w = a.shape[:2]
        m = np.zeros((h, w), bool)
        o, i = max(1, int(0.008 * w)), max(2, int(0.03 * w))      # skip the very rim, take a thin band
        m[o:i, :] = m[h - i:h - o, :] = True
        m[:, w - i:w - o] = True                                  # top, bottom and fore edge (not the spine)
        m &= a[..., 3] > 200
        if not m.any():
            return None
        rgb = np.median(a[..., :3][m], axis=0) / 255.0
        _CACHE[key] = tuple(float(c) for c in rgb)
        return _CACHE[key]
    except Exception:
        return None


def tinted_leather(leather_path, rgb, out_dir, size=1024):
    """A leather texture recoloured to rgb (keeps the grain, takes the colour), as a PNG path."""
    try:
        from PIL import Image
        tag = hashlib.sha1(f'{leather_path}|{rgb}'.encode()).hexdigest()[:16]
        out = Path(out_dir) / f'edge_{tag}.png'
        if out.exists():
            return str(out)
        if leather_path and Path(leather_path).exists():
            with Image.open(leather_path) as im:
                g = np.asarray(im.convert('L').resize((size, size))).astype(np.float32)
            g = g / max(1.0, g.mean())
        else:
            g = np.ones((size, size), np.float32)
        col = np.asarray(rgb, np.float32)[None, None, :] * 255.0 * g[..., None]
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.clip(col, 0, 255).astype(np.uint8), 'RGB').save(out)
        return str(out)
    except Exception:
        return leather_path
