"""Renders a few key frames with real Blender on the build machine and makes a contact sheet.

Used by .github/workflows/preview.yml so changes to the look can be checked without a PC:
    python tools/ci_preview.py <blender> <out_dir> <engine: eevee|cycles>
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('APPDATA', str(Path(sys.argv[2]) / 'appdata'))

import blender_bridge as bb  # noqa: E402
import templates  # noqa: E402
from page_curl import Timeline  # noqa: E402


def font(size):
    for name in ('DejaVuSans-Bold.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def sample_pages(folder):
    """Ink-style test pages: big heading, lines of 'handwriting', a sketch box."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, title in enumerate(['My life', 'Story', 'Tragedies', 'Reality', 'All Evil', 'Redemption']):
        im = Image.new('RGBA', (1000, 1400), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.text((80, 80), title, font=font(130), fill=(30, 25, 20, 255))
        for k in range(9):
            y = 330 + k * 80
            d.line([(90, y), (90 + 700 - (k * 37) % 200, y)], fill=(40, 30, 25, 230), width=9)
        d.rectangle([120, 1050, 520, 1300], outline=(150, 20, 20, 255), width=10)
        d.ellipse([600, 1000, 900, 1300], outline=(30, 25, 20, 255), width=10)
        p = folder / f'page{i + 1}.png'
        im.save(p)
        paths.append(str(p))
    return paths


def emblem(path):
    im = Image.new('RGBA', (600, 600), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([20, 20, 580, 580], fill=(150, 105, 45, 255))
    d.ellipse([60, 60, 540, 540], fill=(110, 20, 20, 255))
    d.polygon([(300, 70), (340, 260), (530, 300), (340, 340), (300, 530), (260, 340), (70, 300), (260, 260)],
              fill=(200, 150, 70, 255))
    im.save(path)


def render(blender, job, folder, label):
    folder.mkdir(parents=True, exist_ok=True)
    job['out_dir'] = str(folder)
    jp = folder.parent / f'{folder.name}.json'
    jp.write_text(json.dumps(job), encoding='utf-8')
    started = time.time()
    res = subprocess.run(bb.command(blender, jp), capture_output=True, text=True, timeout=3000)
    log = (res.stdout or '') + (res.stderr or '')
    (folder.parent / f'{folder.name}.log').write_text(log, encoding='utf-8')
    ok = res.returncode == 0 and 'DONE' in log
    print(f'{label}: {"ok" if ok else "FAILED"} in {time.time() - started:.0f}s')
    if not ok:
        print(log[-3000:])
    return ok, sorted(folder.glob('frame_*.png'))


def main():
    blender, out, engine = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    out.mkdir(parents=True, exist_ok=True)
    pages = sample_pages(out / 'pages')
    templates.ensure_starter_books()
    book = templates.list_books()[0]
    emblem(out / 'emblem.png')
    book = templates.save(dict(book, name='CI journal', folder=None, title='TheTruthProject'),
                          new_image=str(out / 'emblem.png'))
    quality = 'final' if engine == 'eevee' else 'cycles'
    base = dict(width=640, height=360, fps=24, start_hold=0.3, turn_seconds=1.4, pause=0.4, end_hold=0.3,
                start_closed=True, open_seconds=1.6, open_at=0.04, curl=0.9, quality='Final (recommended)',
                blend='Ink on paper (blends in)')
    shots = []
    for name, cam in (('eye', dict(tilt=50, turn=0, roll=-3, lens=35, zoom=1.0, move='none')),
                      ('top', dict(tilt=89, turn=0, roll=0, lens=50, zoom=1.0, move='none'))):
        s = dict(base, cam=cam)
        tl = Timeline(3, 24, 0.3, 1.4, 0.4, 0.3, 1.6)
        t0 = tl.turn_start(0)
        frames = [0, tl.start + tl.open // 2, t0, t0 + int(tl.turn * 0.2), t0 + int(tl.turn * 0.45),
                  t0 + int(tl.turn * 0.7), tl.turn_start(1) + tl.turn + 2]
        if name == 'top':
            frames = [frames[0], frames[4], frames[6]]
        job = bb.make_job(s, book, pages, out / name, frames=frames, quality=quality)
        job['samples'] = 24
        ok, files = render(blender, job, out / name, f'{engine} {name}')
        shots.append((name, frames, files))
    sheet_w = 640 * 4
    rows = sum((len(f) + 3) // 4 for _, _, f in shots) or 1
    sheet = Image.new('RGB', (sheet_w, rows * 360 + 40), (30, 30, 34))
    d = ImageDraw.Draw(sheet)
    d.text((10, 10), f'engine={engine}  {time.strftime("%Y-%m-%d %H:%M")}', fill=(255, 255, 0), font=font(20))
    row = 0
    for name, frames, files in shots:
        for i, f in enumerate(files):
            im = Image.open(f).convert('RGBA')
            bg = Image.new('RGBA', im.size, (95, 95, 105, 255))
            for y in range(0, im.size[1], 20):
                for x in range(0, im.size[0], 20):
                    if (x // 20 + y // 20) % 2:
                        ImageDraw.Draw(bg).rectangle([x, y, x + 19, y + 19], fill=(80, 80, 90, 255))
            bg.alpha_composite(im)
            ImageDraw.Draw(bg).text((6, 6), f'{name} frame {frames[i]}', fill=(255, 255, 0, 255), font=font(16))
            sheet.paste(bg.convert('RGB'), ((i % 4) * 640, 40 + (row + i // 4) * 360))
        row += (len(files) + 3) // 4
    sheet.save(out / f'sheet_{engine}.png')
    print('sheet written')


if __name__ == '__main__':
    main()
