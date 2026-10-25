"""Typed text on pages (step 2): rasterise text to a transparent RGBA image for a page side.

The Blender export receives page images, so typed text is drawn to a transparent PNG here
(using Pillow) and passed along exactly like an image. The live 3D view draws the same text
with Qt and never needs this file.
"""
from PIL import Image, ImageDraw, ImageFont

DEFAULT_COLOR = (30, 25, 20, 255)   # dark ink, matching the "ink on paper" look


def _font(size):
    for name in ('georgia.ttf', 'times.ttf', 'DejaVuSerif.ttf', 'DejaVuSans.ttf', 'arial.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap_lines(draw, text, font, max_width):
    words = text.split()
    lines, line = [], ''
    for w in words:
        trial = (line + ' ' + w).strip()
        if draw.textlength(trial, font=font) <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def text_image(text, width, height, color=DEFAULT_COLOR, font_size=None, margin=0.08):
    """Render `text` onto a transparent RGBA image `width`×`height` (page size), or None if blank."""
    text = (text or '').strip()
    if not text:
        return None
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fs = int(font_size or height * 0.055)
    m = int(width * margin)
    max_w = width - 2 * m
    # Shrink the font until the longest word fits on the page.
    while fs > 8:
        f = _font(fs)
        if max((d.textlength(w, font=f) for w in text.split()), default=0) <= max_w:
            break
        fs -= 2
    font = _font(fs)
    lines = wrap_lines(d, text, font, max_w)
    line_h = fs * 1.35
    y = (height - line_h * len(lines)) / 2
    for ln in lines:
        w = d.textlength(ln, font=font)
        d.text(((width - w) / 2, y), ln, font=font, fill=color)
        y += line_h
    return img


def text_png(text, path, width, height, **kw):
    """Render text to a PNG file at `path`; returns True if it wrote a page of text."""
    img = text_image(text, width, height, **kw)
    if img is None:
        return False
    img.save(path)
    return True


def side_kind(side):
    """Normalise a content side to ('image', path) | ('text', text) | ('blank', None)."""
    if side is None:
        return ('blank', None)
    if isinstance(side, str):
        return ('image', side)
    kind = side.get('kind') if hasattr(side, 'get') else getattr(side, 'kind', None)
    if kind == 'image':
        return ('image', side.get('image') if hasattr(side, 'get') else side.image)
    if kind == 'text':
        return ('text', side.get('text', '') if hasattr(side, 'get') else getattr(side, 'text', ''))
    return ('blank', None)


def sides_to_images(sides, out_dir, page_aspect=1.4):
    """Convert content sides to image paths; text is rasterised to a PNG in `out_dir`.

    Each side is None (blank), an image path, or a dict/Side with kind 'image' or 'text'.
    """
    from pathlib import Path
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    w = 700
    h = int(round(w * page_aspect))
    images = []
    for i, side in enumerate(sides):
        kind, value = side_kind(side)
        if kind == 'image':
            images.append(value)
        elif kind == 'text' and value.strip():
            p = out_dir / f'text_{i:03d}.png'
            text_png(value, str(p), w, h)
            images.append(str(p))
        else:
            images.append(None)
    return images
