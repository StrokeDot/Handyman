"""Screenshots of the app's live 3D view under a virtual screen (software OpenGL).

    xvfb-run python tools/ci_liveview.py <out_dir>
Writes sheet_live.png and live.log; exits non-zero if the live view failed.
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
os.environ['APPDATA'] = str(OUT / 'appdata_live')

from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ci_preview import emblem, font, sample_pages  # noqa: E402


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def main():
    log = []
    qt = QApplication(sys.argv)
    import app as studio_app
    import templates
    w = studio_app.Studio()
    w.resize(1500, 900)
    w.show()
    pump(qt, 1.0)
    if w.live is None:
        print('LIVE VIEW NOT AVAILABLE', studio_app.GL_IMPORT_ERROR, w.status.text())
        return 1
    from OpenGL import GL
    w.live.makeCurrent()
    log.append(f'GL: {GL.glGetString(GL.GL_RENDERER)} / {GL.glGetString(GL.GL_VERSION)}')
    w.live.doneCurrent()

    pages = sample_pages(OUT / 'pages_live')
    emblem(OUT / 'emblem_live.png')
    book = templates.save(dict(templates.list_books()[0], name='CI live', folder=None, title='TheTruthProject'),
                          new_image=str(OUT / 'emblem_live.png'))
    w._reload_books(book['folder'])
    w._set_pages(pages)
    w._show_view(0)
    pump(qt, 0.5)
    w._refresh_live()
    pump(qt, 0.5)
    tl = w.live.timeline
    t0 = tl.turn_start(0)
    shots = [('closed', 0), ('cover opening', tl.start + tl.open // 2), ('open', t0),
             ('corner peel', t0 + int(tl.turn * 0.2)), ('mid turn', t0 + int(tl.turn * 0.5)),
             ('turn landing', t0 + int(tl.turn * 0.8)), ('second spread', tl.turn_start(1) + tl.turn + 2)]
    images = []
    for label, frame in shots:
        w.live.seek(frame)
        pump(qt, 0.25)
        img = w.live.grabFramebuffer()
        p = OUT / f'live_{frame:04d}.png'
        img.save(str(p))
        images.append((label, frame, p))
    if w.live is None or w.live.broken:
        print('LIVE VIEW BROKE:', getattr(w.live, 'broken', None), w.status.text())
        return 1

    # Mouse drag changes the camera; playback advances.
    turn0 = w.turn.value()
    w.live.orbit.emit(-60, 0)
    pump(qt, 0.3)
    log.append(f'drag: turn {turn0} -> {w.turn.value()}')
    w.live.seek(0)
    w._toggle_play()
    pump(qt, 1.0)
    log.append(f'play 1 s at 1x: frame {w.live.frame:.1f} (fps {tl.fps})')
    w.speed.setCurrentText('2×')
    f0 = w.live.frame
    pump(qt, 0.5)
    log.append(f'play 0.5 s at 2x: +{w.live.frame - f0:.1f} frames')
    w._toggle_play()
    img = w.grab()
    img.save(str(OUT / 'live_window.png'))

    sheet = Image.new('RGB', (480 * 4, 40 + 270 * 2), (30, 30, 34))
    d = ImageDraw.Draw(sheet)
    d.text((10, 10), 'live 3D view (software OpenGL)  ' + log[0][:90], fill=(255, 255, 0), font=font(18))
    for i, (label, frame, p) in enumerate(images):
        im = Image.open(p).convert('RGB').resize((480, 270))
        ImageDraw.Draw(im).text((6, 6), f'{label} · frame {frame}', fill=(255, 255, 0), font=font(16))
        sheet.paste(im, ((i % 4) * 480, 40 + (i // 4) * 270))
    sheet.save(OUT / 'sheet_live.png')
    win = Image.open(OUT / 'live_window.png').convert('RGB')
    win.thumbnail((1600, 1000))
    win.save(OUT / 'sheet_live_window.png')
    (OUT / 'live.log').write_text('\n'.join(log), encoding='utf-8')
    print('\n'.join(log))
    w.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
