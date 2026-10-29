"""Book templates: a folder with book.json and its images (emblem, optional textures).

Templates live in the user folder (%APPDATA%\\Handyman\\books), so your own designs
never go into the app's public code. The app ships one plain starter book.
"""
import json
import re
import shutil
from pathlib import Path

import paths

DEFAULTS = {
    'name': 'Leather journal',
    'leather_color': '#6b3a1e',
    'back_cover_color': None,     # None = same as leather_color (swappable back cover)
    'inside_cover_color': None,   # None = paper-coloured endpaper (swappable inside cover)
    'leather_image': 'resources/templates/leather.png',   # bundled photo texture (relative to resources/)
    'paper_image': 'resources/templates/paper.png',       # bundled aged-paper texture
    # One replaceable image per cover surface (bundled, calibrated artwork by default).
    'front_exterior_image': 'resources/templates/panels/front_ext.png',
    'front_interior_image': 'resources/templates/panels/front_in.png',
    'back_exterior_image': 'resources/templates/panels/back_ext.png',
    'back_interior_image': 'resources/templates/panels/back_in.png',
    'spine_exterior_image': 'resources/templates/panels/spine_ext.png',
    'inside_leather_image': None,
    'paper_color': '#e0c99a',
    'paper_age': 0.55,          # blotches and yellowing, 0..1
    'burn': 0.6,                # darkened page edges, 0..1
    'page_aspect': 1.4,         # page height / width
    'stitching': True,
    'thread_color': '#b08a5a',
    'spine_bands': 4,
    'emblem': None,             # image file inside the template folder
    'emblem_style': 'medallion',  # 'medallion' (the image as-is) or 'deboss' (pressed into leather)
    'emblem_size': 0.42,        # fraction of the cover width
    'emblem_y': 0.18,           # up from the cover centre, fraction of cover height
    'title': '',
    'title_style': 'deboss',    # 'deboss' or 'gold'
    'title_size': 0.07,         # letter height, fraction of cover height
    'title_y': -0.08,
}
SLOTS = ('front_exterior', 'front_interior', 'back_exterior', 'back_interior', 'spine_exterior')
for _slot in SLOTS:
    DEFAULTS[f'{_slot}_fit'] = 'fit'
    DEFAULTS[f'{_slot}_scale'] = 1.0
    DEFAULTS[f'{_slot}_x'] = 0.0
    DEFAULTS[f'{_slot}_y'] = 0.0
EMBLEM_STYLES = {'Medallion (image as it is)': 'medallion', 'Pressed into leather': 'deboss'}
TITLE_STYLES = {'Pressed into leather': 'deboss', 'Gold foil': 'gold'}


def slug(name):
    s = re.sub(r'[^a-zA-Z0-9]+', '-', name.strip().lower()).strip('-')
    return s or 'book'


def hex_to_linear(value):
    """'#rrggbb' (what you see) to Blender's linear colour."""
    value = value.lstrip('#')
    out = []
    for i in (0, 2, 4):
        c = int(value[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def ensure_starter_books():
    """Copy bundled starter books into the user folder, and refresh them on upgrade.

    A bundled book is copied when it is missing - which is how the calibrated leather
    book reaches users who already have an older install. An existing user book is left
    completely alone unless the bundled copy is explicitly newer (``bundle_version``)
    AND the user has never saved it, so nobody's customised template is overwritten.
    """
    src = paths.resource_dir() / 'resources' / 'books'
    for folder in src.glob('*'):
        if not folder.is_dir():
            continue
        dest = paths.books_dir() / folder.name
        bundled = _read_json(folder / 'book.json')
        if not dest.exists():
            shutil.copytree(folder, dest)
            continue
        current = _read_json(dest / 'book.json')
        if not bundled or not current:
            continue
        same = str(current.get('bundle_version') or '') == str(bundled.get('bundle_version') or '')
        # a Legacy template is never refreshed: users may have customised it
        if same or current.get('user_modified') or current.get('legacy') or bundled.get('legacy'):
            continue
        # Upgrade only the fields the bundle owns; everything else is preserved.
        merged = dict(current)
        merged.update({k: v for k, v in bundled.items() if k in
                       ('page_aspect', 'page_count', 'front_exterior_image',
                        'front_interior_image', 'back_exterior_image',
                        'back_interior_image', 'spine_exterior_image', 'bundle_version')})
        (dest / 'book.json').write_text(json.dumps(merged, indent=2), encoding='utf-8')


def load(folder):
    folder = Path(folder)
    data = dict(DEFAULTS)
    try:
        data.update(json.loads((folder / 'book.json').read_text(encoding='utf-8')))
    except (OSError, ValueError):
        pass
    data['folder'] = str(folder)
    return data


def list_books():
    ensure_starter_books()
    books = [load(f) for f in sorted(paths.books_dir().glob('*')) if (f / 'book.json').exists()]
    return books or [dict(DEFAULTS, folder=None)]


def save(book, new_image=None, art_images=None):
    """Write a template. new_image: path of a freshly chosen emblem to copy in.

    art_images: {field: source path or None} for the replaceable cover surfaces; each chosen
    file is copied into the template folder so the book stays portable.
    """
    folder = Path(book.get('folder') or paths.books_dir() / slug(book['name']))
    folder.mkdir(parents=True, exist_ok=True)
    book['user_modified'] = True      # protects this template from bundled upgrades
    data = {k: book.get(k, v) for k, v in DEFAULTS.items()}
    if book.get('user_modified'):
        data['user_modified'] = True
    if new_image:
        target = folder / ('emblem' + Path(new_image).suffix.lower())
        if Path(new_image).resolve() != target.resolve():
            shutil.copyfile(new_image, target)
        data['emblem'] = target.name
    for field, path in (art_images or {}).items():
        if path:
            target = folder / (field + Path(path).suffix.lower())
            if Path(path).resolve() != target.resolve():
                shutil.copyfile(path, target)
            data[field] = target.name
        else:
            data[field] = None
    (folder / 'book.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    return load(folder)


def duplicate(book, new_name):
    folder = paths.books_dir() / slug(new_name)
    n = 2
    while folder.exists():
        folder = paths.books_dir() / f'{slug(new_name)}-{n}'
        n += 1
    if book.get('folder') and Path(book['folder']).exists():
        shutil.copytree(book['folder'], folder)
    copy = dict(book, name=new_name, folder=str(folder))
    return save(copy)


def _texture_path(book, name):
    """Resolve a texture: a file in the book folder first, else bundled in the resources dir."""
    if not name:
        return None
    name = str(name)
    candidates = []
    if book.get('folder'):
        candidates.append(Path(book['folder']) / name)
    candidates.append(paths.resource_dir() / name)
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def _fit(book, slot):
    return {'mode': book.get(f'{slot}_fit', 'fit'),
            'scale': float(book.get(f'{slot}_scale', 1.0)),
            'x': float(book.get(f'{slot}_x', 0.0)),
            'y': float(book.get(f'{slot}_y', 0.0))}


def for_scene(book):
    """The template in the form the Blender scene reads (absolute paths, linear colours)."""
    emblem = None
    if book.get('emblem') and book.get('folder'):
        p = Path(book['folder']) / book['emblem']
        emblem = str(p) if p.exists() else None
    return dict(
        leather_color=hex_to_linear(book['leather_color']),
        back_cover_color=hex_to_linear(book.get('back_cover_color') or book['leather_color']),
        inside_cover_color=hex_to_linear(book.get('inside_cover_color') or book['paper_color']),
        paper_color=hex_to_linear(book['paper_color']),
        leather_image=_texture_path(book, book.get('leather_image')),
        paper_image=_texture_path(book, book.get('paper_image')),
        front_exterior_image=_texture_path(book, book.get('front_exterior_image')),
        front_interior_image=_texture_path(book, book.get('front_interior_image')),
        back_exterior_image=_texture_path(book, book.get('back_exterior_image')),
        back_interior_image=_texture_path(book, book.get('back_interior_image')),
        spine_exterior_image=_texture_path(book, book.get('spine_exterior_image')),
        front_exterior_fit=_fit(book, 'front_exterior'),
        front_interior_fit=_fit(book, 'front_interior'),
        back_exterior_fit=_fit(book, 'back_exterior'),
        back_interior_fit=_fit(book, 'back_interior'),
        spine_exterior_fit=_fit(book, 'spine_exterior'),
        inside_leather_image=_texture_path(book, book.get('inside_leather_image')
                                           or book.get('leather_image')),
        thread_color=hex_to_linear(book['thread_color']),
        paper_age=float(book['paper_age']), burn=float(book['burn']),
        page_aspect=float(book['page_aspect']), stitching=bool(book['stitching']),
        spine_bands=int(book['spine_bands']),
        emblem=emblem, emblem_style=book['emblem_style'], emblem_size=float(book['emblem_size']),
        emblem_y=float(book['emblem_y']), title=book.get('title', ''), title_style=book['title_style'],
        title_size=float(book['title_size']), title_y=float(book['title_y']),
    )



