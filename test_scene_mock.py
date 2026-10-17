"""Runs the whole Blender scene script against a stand-in for Blender.

It cannot show how the book looks, but it catches mistakes in the scene code
(wrong names, bad maths, missing settings) before anything reaches your PC.
"""
import json
import os
import sys
import tempfile
from unittest.mock import MagicMock

bpy = MagicMock()
bpy.types.NodeSocket = MagicMock
bpy.data.images.load.return_value.size = (800, 600)
bpy.data.objects.new.side_effect = lambda *a, **k: MagicMock()  # a separate object each time
sys.modules['bpy'] = bpy
sys.modules['bmesh'] = MagicMock()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import book_scene  # noqa: E402
import blender_bridge as bb  # noqa: E402
import templates  # noqa: E402

book_scene.sock = lambda sockets, name, kind=None: MagicMock()

SETTINGS = dict(width=1920, height=1080, fps=30, start_hold=0.5, turn_seconds=1.0, pause=0.3,
                end_hold=0.5, curl=0.9, quality='Draft (fastest)',
                cam=dict(tilt=50, turn=10, roll=-3, lens=35, zoom=1.0, move='push', shift_x=0.1, shift_y=0),
                blend='Ink on paper (blends in)', start_closed=True, open_seconds=1.5)


def run(settings, book, images):
    with tempfile.TemporaryDirectory() as tmp:
        job = bb.make_job(settings, book, images, os.path.join(tmp, 'out'))
        jp = os.path.join(tmp, 'job.json')
        with open(jp, 'w') as fh:
            json.dump(job, fh)
        sys.argv = ['blender', '--', jp]
        before = bpy.ops.render.render.call_count
        book_scene.main()
        with open(os.path.join(tmp, 'out', 'sequence.json')) as fh:
            seq = json.load(fh)
        return seq, bpy.ops.render.render.call_count - before


def test_full_book_with_cover_opening():
    with tempfile.TemporaryDirectory() as tmp:
        emblem = os.path.join(tmp, 'emblem.png')
        open(emblem, 'wb').close()
        book = dict(templates.DEFAULTS, folder=tmp, emblem='emblem.png', title='The Journal')
        seq, renders = run(SETTINGS, book, ['/x/a.png', None, '/x/b.png', '/x/c.png', '/x/d.png'])
    assert seq['turns'] == 2 and renders == seq['frames'] > 0


def test_open_start_cycles_and_deboss():
    s = dict(SETTINGS, start_closed=False, quality='Photoreal (Cycles, slow)',
             cam=dict(tilt=89.5, turn=0, roll=0, lens=50, zoom=1.2, move='none'))
    book = dict(templates.DEFAULTS, folder=None, title='', stitching=False, emblem_style='deboss')
    seq, renders = run(s, book, [])
    assert seq['turns'] == 1 and renders == seq['frames']


if __name__ == '__main__':
    test_full_book_with_cover_opening()
    test_open_start_cycles_and_deboss()
    print('ok scene mock')
