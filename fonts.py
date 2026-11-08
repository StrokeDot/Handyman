"""Fonts for text on the pages - the same fonts as StrokeScribe.

The list is StrokeScribe's: open-licensed Google Fonts (OFL or Apache 2.0, free also for
commercial use), downloaded only when you choose one, each saved with its original licence.
Handyman uses StrokeScribe's own font folder, so a font you already have there is ready here
too, and the other way round. You can also bring a font file of your own.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

FONT_GROUPS = {
    'Handwriting': ('Caveat', 'Kalam', 'Patrick Hand', 'Indie Flower', 'Gochi Hand', 'Architects Daughter',
                    'Shadows Into Light', 'Reenie Beanie', 'Amatic SC', 'Permanent Marker', 'Rock Salt',
                    'Covered By Your Grace', 'Gloria Hallelujah', 'Handlee', 'Nothing You Could Do', 'Homemade Apple',
                    'Just Another Hand', 'Schoolbell', 'Coming Soon', 'Neucha', 'Over the Rainbow',
                    'Annie Use Your Telescope', 'La Belle Aurore', 'Zeyada', 'Delius', 'Mali', 'Sriracha',
                    'Caveat Brush', 'Pangolin', 'Delicious Handrawn', 'Sue Ellen Francisco', 'Short Stack'),
    'Script': ('Dancing Script', 'Sacramento', 'Satisfy', 'Great Vibes', 'Pacifico', 'Courgette', 'Kaushan Script',
               'Allura'),
    'Clean titles': ('Nunito', 'Poppins', 'Montserrat', 'Lato', 'Quicksand', 'Comfortaa', 'Fredoka', 'Bebas Neue',
                     'Oswald', 'Bangers', 'Luckiest Guy', 'Chewy'),
    'Serif': ('Merriweather', 'Playfair Display', 'Lora'),
}
ALL_FONTS = tuple(f for group in FONT_GROUPS.values() for f in group)
BUILT_IN = 'Book serif (built in)'
MAX_FONT_BYTES = 12_000_000
API_ROOT = 'https://api.github.com/repos/google/fonts/contents'
BINARY_HOST = 'https://raw.githubusercontent.com/google/fonts/'
FONT_SUFFIXES = {'.ttf', '.otf'}


def font_dir():
    """StrokeScribe's font folder (shared by both apps)."""
    appdata = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.strokescribe')))
    return appdata / 'StrokeScribe' / 'fonts'


def font_slug(family):
    slug = re.sub(r'[^a-z0-9]', '', family.lower())
    if not 2 <= len(slug) <= 60:
        raise ValueError('Choose a Google Fonts family name such as Caveat or Kalam.')
    return slug


def built_in_font():
    """A serif font that is always there (Windows' Georgia / Times, or DejaVu elsewhere)."""
    win = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for p in (win / 'georgia.ttf', win / 'times.ttf', win / 'cambria.ttc', win / 'segoeui.ttf',
              Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'),
              Path('/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf'),
              Path('/System/Library/Fonts/Supplemental/Georgia.ttf')):
        if p.exists():
            return p
    return None


def installed_font(family):
    """Path of an installed font (a Google family, an imported file or the built-in one), or None."""
    if family == BUILT_IN:
        return built_in_font()
    if family.startswith('Imported: '):
        p = font_dir() / 'imported' / family[len('Imported: '):]
        return p if p.exists() else None
    try:
        dest = font_dir() / font_slug(family)
    except ValueError:
        return None
    if not dest.is_dir():
        return None
    for path in sorted(dest.glob('*')):
        if path.suffix.lower() in FONT_SUFFIXES and path.stat().st_size > 1000:
            return path
    return None


def imported_fonts():
    d = font_dir() / 'imported'
    if not d.is_dir():
        return []
    return ['Imported: ' + p.name for p in sorted(d.iterdir()) if p.suffix.lower() in FONT_SUFFIXES]


def _read_url(url, binary=False):
    from urllib.request import Request, urlopen
    req = Request(url, headers={
        'User-Agent': 'Handyman-font-installer/1.0',
        'Accept': 'application/vnd.github+json' if not binary else 'application/octet-stream',
    })
    with urlopen(req, timeout=30) as response:
        data = response.read(MAX_FONT_BYTES + 1)
    if len(data) > MAX_FONT_BYTES:
        raise ValueError('This font is too large to download automatically.')
    return data


def download_google_font(family):
    """Fetch one Google Fonts family (font file and its original licence) into the shared folder."""
    from urllib.error import HTTPError, URLError
    slug = font_slug(family)
    existing = installed_font(family)
    if existing:
        return existing
    items = None
    for collection in ('ofl', 'apache', 'ufl'):
        url = f'{API_ROOT}/{collection}/{slug}?ref=main'
        try:
            items = json.loads(_read_url(url))
            if isinstance(items, list):
                break
        except HTTPError as exc:
            if exc.code == 404:
                continue
            raise RuntimeError(f'Google Fonts returned HTTP {exc.code}; please try again.') from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError('Cannot reach Google Fonts. Check the internet connection and try again.') from exc
    if not isinstance(items, list):
        raise ValueError(f'No Google Fonts family named {family!r} was found.')
    licenses = [a for a in items if isinstance(a, dict)
                and a.get('name', '').lower() in ('ofl.txt', 'license.txt', 'ufl.txt')]
    files = [a for a in items if isinstance(a, dict) and Path(a.get('name', '')).suffix.lower() in FONT_SUFFIXES]
    if not files or not licenses:
        raise ValueError('Google Fonts did not provide a font file and licence for this family.')
    files.sort(key=lambda a: (not ('-regular' in a['name'].lower() or 'variablefont' in a['name'].lower()),
                              len(a['name'])))
    selected = files[0]

    def trusted_url(item):
        link = item.get('download_url', '')
        if not isinstance(link, str) or not link.startswith(BINARY_HOST):
            raise ValueError('Unexpected font download address; stopped for safety.')
        return link
    license_data = _read_url(trusted_url(licenses[0]), binary=True)
    font_data = _read_url(trusted_url(selected), binary=True)
    if not font_data.startswith((b'\x00\x01\x00\x00', b'OTTO', b'true')):
        raise ValueError('The download is not a valid TrueType/OpenType font.')
    if len(font_data) < 1000 or not license_data:
        raise ValueError('The font file or its licence was incomplete.')
    dest = font_dir() / slug
    dest.mkdir(parents=True, exist_ok=True)
    fontfile = dest / Path(selected['name']).name
    (dest / Path(licenses[0]['name']).name).write_bytes(license_data)
    try:
        fontfile.write_bytes(font_data)
    except Exception:
        fontfile.unlink(missing_ok=True)
        raise
    return fontfile


def import_font(source):
    """Bring a TTF/OTF file of your own (it is copied into the shared folder)."""
    path = Path(source)
    if path.suffix.lower() not in FONT_SUFFIXES or not path.is_file():
        raise ValueError('Choose a TTF or OTF font file.')
    if path.stat().st_size > MAX_FONT_BYTES:
        raise ValueError('That font file is bigger than the 12 MB allowed.')
    if not path.read_bytes()[:4].startswith((b'\x00\x01\x00\x00', b'OTTO', b'true')):
        raise ValueError('That file is not a valid font.')
    name = re.sub(r'[^A-Za-z0-9._-]', '', path.stem)[:65] or 'font'
    dest = font_dir() / 'imported'
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / (name + path.suffix.lower())
    if path.resolve() != target.resolve():
        shutil.copy2(path, target)
    return 'Imported: ' + target.name


# ---------------------------------------------------------------- text as a picture
TEXT_DEFAULTS = dict(text='', font=BUILT_IN, size=14.0, colour='Dark grey (like printed text)', align='left',
                     spacing=1.25, width=0.84)
TEXT_COLOURS = {'Dark grey (like printed text)': (41, 41, 44), 'Black': (12, 12, 12), 'Sepia': (74, 52, 34),
                'Brown ink': (60, 38, 22), 'Blue ink': (28, 44, 92), 'Red ink': (120, 24, 20)}
PX_PER_PT = 0.0353 / 15.0      # one point as a share of a 15 cm page width


def render_text(t, page_px, page_cm=15.0, scale=2.0):
    """The text as a transparent PIL image, wrapped to its box. page_px: page width in pixels.
    Sizes are in points on the real page (12 pt reads like a printed book), drawn at `scale`
    times the page's pixels so it stays crisp."""
    from PIL import Image, ImageDraw, ImageFont
    d = dict(TEXT_DEFAULTS)
    d.update(t or {})
    px_per_cm = page_px / float(page_cm) * scale
    size = max(4, round(float(d['size']) * 0.03528 * px_per_cm))          # 1 pt = 0.3528 mm
    path = installed_font(d['font']) or built_in_font()
    try:
        font = ImageFont.truetype(str(path), size) if path else ImageFont.load_default()
    except OSError:
        font = ImageFont.load_default()
    box_w = max(20, round(float(d['width']) * page_px * scale))
    probe = ImageDraw.Draw(Image.new('L', (8, 8)))
    lines = []
    for para in str(d['text']).split('\n'):
        words, line = para.split(' '), ''
        if not para.strip():
            lines.append('')
            continue
        for wd in words:
            trial = (line + ' ' + wd).strip()
            if probe.textlength(trial, font=font) <= box_w or not line:
                line = trial
            else:
                lines.append(line)
                line = wd
        lines.append(line)
    asc, desc = font.getmetrics() if hasattr(font, 'getmetrics') else (size, size // 4)
    step = round((asc + desc) * float(d['spacing']))
    h = max(step, step * len(lines)) + desc
    img = Image.new('RGBA', (box_w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    rgb = TEXT_COLOURS.get(d['colour'], (41, 41, 44)) if isinstance(d['colour'], str) else tuple(d['colour'])
    for i, line in enumerate(lines):
        lw = dr.textlength(line, font=font)
        x = {'left': 0, 'centre': (box_w - lw) / 2, 'right': box_w - lw}.get(d['align'], 0)
        dr.text((x, i * step), line, font=font, fill=rgb + (255,))
    return img


def text_image_file(t, page_px, out_dir, page_cm=15.0):
    """render_text() saved as a PNG (reused while the text does not change); returns its path."""
    import hashlib
    d = dict(TEXT_DEFAULTS)
    d.update(t or {})
    fp = installed_font(d['font'])
    key = json.dumps([d, page_px, page_cm, str(fp), fp.stat().st_mtime_ns if fp else 0], sort_keys=True, default=str)
    out = Path(out_dir) / f'text_{hashlib.sha1(key.encode()).hexdigest()[:16]}.png'
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        render_text(d, page_px, page_cm).save(out)
    return str(out)
