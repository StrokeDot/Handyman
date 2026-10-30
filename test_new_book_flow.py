"""End-to-end: New Leather Book -> first-spread preview -> image reaches the preview widget.

Runs headless. The Qt widget itself cannot be constructed here (no PySide6), so the test
verifies everything up to and including the file the widget loads: the job built from the
template, the frame index chosen for the still, the Blender render, and the exact path the
app hands to QPixmap.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(r'C:\Users\Alejandro\Documents\deepseek-harness\default-workspace')
REPO = WS / 'Handyman'
sys.path.insert(0, str(REPO))

import templates  # noqa: E402
import blender_bridge as bb  # noqa: E402
from page_curl import layout_pages  # noqa: E402
from scene import Scene  # noqa: E402


def test_new_leather_book_selects_calibrated_template():
    """The template the button targets must exist, be 20 sheets, and carry all panels."""
    folder = REPO / 'resources' / 'books' / 'leather-book'
    assert folder.is_dir(), 'leather-book template missing'
    book = templates.load(folder)
    assert 'Development Preview' in book['name'], book['name']
    assert int(book['page_count']) == 20, book['page_count']
    assert abs(float(book['page_aspect']) - 1.424) < 1e-9, book['page_aspect']
    for field in ('front_exterior_image', 'front_interior_image', 'back_exterior_image',
                  'back_interior_image', 'spine_exterior_image'):
        rel = book.get(field)
        assert rel, f'{field} not set'
        assert (REPO / rel).exists(), f'{field} missing on disk: {rel}'


def test_first_spread_frame_is_the_open_book_not_a_turn():
    """Preview still must target the open first spread, not a mid-turn frame."""
    book = templates.load(REPO / 'resources' / 'books' / 'leather-book')
    sc = Scene(0, float(book['page_aspect']), 0.04, 30, 0.8, 1.3, 0.6, 1.2, 1.6, True,
               page_count=20)
    frame = int(sc.timeline.first_turn)
    pose = sc.evaluate(frame)
    assert abs(float(pose['cover_angle'])) < 1e-6, 'cover not fully open at the preview frame'
    assert all(float(v) <= 1e-9 for v in pose['sheet_progress']), 'a sheet had started turning'


def test_preview_render_produces_the_image_the_widget_loads():
    """Render the still through Blender and confirm the exact path exists and decodes."""
    book = templates.load(REPO / 'resources' / 'books' / 'leather-book')
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        os.environ['APPDATA'] = str(out / 'appdata')
        sc = Scene(0, float(book['page_aspect']), 0.04, 30, 0.8, 1.3, 0.6, 1.2, 1.6, True,
                   page_count=20)
        settings = dict(width=320, height=240, fps=30, start_hold=0.8, turn_seconds=1.3,
                        pause=0.6, end_hold=1.2, start_closed=True, open_seconds=1.6,
                        open_at=0.04, curl=0.9, page_count=20, turns=0, smoothness=1.0,
                        quality='Draft (fastest)', blend='Photo (keeps bright colours)',
                        cam=dict(tilt=58, turn=0, roll=0, lens=50, zoom=1.0, move='none'))
        job = bb.make_job(settings, book, [], out / 'still')   # zero pages, like a new project
        job['out_dir'] = str(out / 'still')
        job['frames'] = [int(sc.timeline.first_turn)]
        Path(job['out_dir']).mkdir(parents=True, exist_ok=True)
        jp = out / 'job.json'
        jp.write_text(json.dumps(job), encoding='utf-8')
        subprocess.run(bb.command(bb.find_blender(), jp), capture_output=True, text=True,
                       timeout=1800)
        # this is exactly what _show_still builds
        path = Path(job['out_dir']) / 'frame_000000.png'
        assert path.exists(), f'preview frame not produced: {path}'
        assert path.stat().st_size > 5000, 'preview frame suspiciously small'
        with open(path, 'rb') as fh:
            assert fh.read(8) == b'\x89PNG\r\n\x1a\n', 'preview is not a PNG'


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
        print(f'ok {t.__name__}')
    print(f'ALL {len(tests)} INTEGRATION TESTS PASSED')


if __name__ == '__main__':
    main()
