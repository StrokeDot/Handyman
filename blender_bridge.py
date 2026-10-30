"""Finds Blender and runs book_scene.py in the background. No Qt here, so it is testable."""
import glob
import os
import re
import shutil
import subprocess
from pathlib import Path

import paths
import templates

SCENE_SCRIPT = paths.resource_dir() / 'book_scene.py'
GLTF_SCRIPT = paths.resource_dir() / 'image_book_export.py'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

QUALITY = {'Draft (fastest)': 'draft', 'Final (recommended)': 'final', 'Photoreal (Cycles, slow)': 'cycles'}
BLEND = {'Ink on paper (blends in)': 'ink', 'Photo (keeps bright colours)': 'photo'}


def _version_key(path):
    nums = re.findall(r'\d+', str(path))
    return [int(n) for n in nums[-3:]] if nums else [0]


def find_blender(saved=None):
    """Most recent Blender install, or None."""
    # CI and portable installs can point at Blender explicitly.
    env = os.environ.get('HANDYMAN_BLENDER')
    if env and Path(env).is_file():
        return str(env)
    if saved and Path(saved).is_file():
        return str(saved)
    candidates = []
    for pattern in (r'C:\Program Files\Blender Foundation\Blender*\blender.exe',
                    r'C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe',
                    os.path.expandvars(r'%LOCALAPPDATA%\Programs\Blender Foundation\Blender*\blender.exe'),
                    os.path.expandvars(r'%ProgramFiles%\Blender Foundation\Blender*\blender.exe')):
        candidates += glob.glob(pattern)
    candidates.sort(key=_version_key, reverse=True)
    if candidates:
        return candidates[0]
    return shutil.which('blender')


def blender_version(path):
    try:
        out = subprocess.run([path, '-b', '--factory-startup', '--version'], capture_output=True,
                             text=True, timeout=60, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'Blender (\d+\.\d+(?:\.\d+)?)', out)
    return m.group(1) if m else None


def make_job(settings, book, images, out_dir, frames=None, width=None, height=None, quality=None,
             pages=None):
    """settings: plain dict of the UI choices (labels are translated here).
    book: a template from templates.py.
    pages: optional content sides (None | image path | {'kind':'text','text':...}); text is
           rasterised to a PNG and treated like an image, so the Blender scene is unchanged."""
    if pages is not None:
        import page_text
        images = page_text.sides_to_images(pages, str(Path(out_dir) / 'text'),
                                           float(book.get('page_aspect', 1.4)))
    scene_book = templates.for_scene(book)
    # Base paper is its own user-selectable texture. Page content is assigned per side only, so a
    # page carrying text or an illustration is never duplicated onto unassigned sides.
    scene_book['base_paper_image'] = scene_book.get('paper_image')
    return dict(
        images=[str(p) if p else None for p in images],
        out_dir=str(out_dir),
        width=int(width or settings['width']),
        height=int(height or settings['height']),
        fps=int(settings['fps']),
        start_hold=float(settings['start_hold']),
        turn_seconds=float(settings['turn_seconds']),
        pause=float(settings['pause']),
        end_hold=float(settings['end_hold']),
        curl=float(settings['curl']),
        cam=dict(settings['cam']),
        quality=quality or QUALITY[settings['quality']],
        blend=BLEND[settings['blend']],
        open_seconds=float(settings['open_seconds']) if settings['start_closed'] else 0.0,
        slide=bool(settings['start_closed']),
        open_at=float(settings.get('open_at', 0.04)),
        page_count=int(settings.get('page_count', 50)),
        turns=(int(settings['turns']) if settings.get('turns') is not None else None),
        smoothness=float(settings.get('smoothness', 1.0)),
        page_fits=list(settings.get('page_fits') or []),
        recorded_clips=list(settings.get('recorded_clips', [])),
        clip_list=list(settings['clip_list']) if settings.get('clip_list') else None,
        transform=dict(settings.get('transform') or {}),
        book=scene_book,
        # A full-bleed page image (parchment included) must REPLACE the procedural paper: no inset,
        # no partial blend. The margin/strength only make sense for ink artwork printed onto paper.
        image_strength=0.92 if settings.get('blend') == 'Ink on paper (blends in)' else 1.0,
        margin=0.08 if settings.get('blend') == 'Ink on paper (blends in)' else 0.0,
        png_compression=15,
        frames=frames,
    )


def command(blender, job_path):
    return [blender, '-b', '--factory-startup', '-noaudio', '-P', str(SCENE_SCRIPT), '--', str(job_path)]


def command_gltf(blender, job_path):
    return [blender, '-b', '--factory-startup', '-noaudio', '-P', str(GLTF_SCRIPT), '--', str(job_path)]


def parse_line(line):
    """('progress', done, total) | ('total', n) | ('error', msg) | ('done',) | ('log', line)."""
    line = line.rstrip()
    if line.startswith('PROGRESS '):
        a, b = line.split()[1:3]
        return ('progress', int(a), int(b))
    if line.startswith('TOTAL '):
        return ('total', int(line.split()[1]))
    if line.startswith('ERROR '):
        return ('error', line[6:])
    if line == 'DONE':
        return ('done',)
    return ('log', line)



