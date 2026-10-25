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


def ensure_starter_books():
    """Copy the bundled starter book(s) into the user folder the first time."""
    src = paths.resource_dir() / 'resources' / 'books'
    for folder in src.glob('*'):
        dest = paths.books_dir() / folder.name
        if folder.is_dir() and not dest.exists():
            shutil.copytree(folder, dest)


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


def save(book, new_image=None):
    """Write a template. new_image: path of a freshly chosen emblem to copy in."""
    folder = Path(book.get('folder') or paths.books_dir() / slug(book['name']))
    folder.mkdir(parents=True, exist_ok=True)
    data = {k: book.get(k, v) for k, v in DEFAULTS.items()}
    if new_image:
        target = folder / ('emblem' + Path(new_image).suffix.lower())
        if Path(new_image).resolve() != target.resolve():
            shutil.copyfile(new_image, target)
        data['emblem'] = target.name
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
        thread_color=hex_to_linear(book['thread_color']),
        paper_age=float(book['paper_age']), burn=float(book['burn']),
        page_aspect=float(book['page_aspect']), stitching=bool(book['stitching']),
        spine_bands=int(book['spine_bands']),
        emblem=emblem, emblem_style=book['emblem_style'], emblem_size=float(book['emblem_size']),
        emblem_y=float(book['emblem_y']), title=book.get('title', ''), title_style=book['title_style'],
        title_size=float(book['title_size']), title_y=float(book['title_y']),
    )
