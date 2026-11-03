"""Journal engine: geometry rules that keep the book looking like one real object."""
import json
import math
import tempfile
from pathlib import Path

import numpy as np

import blender_bridge as bb
import journal_geom as G
import templates


def _height_above_cover(pts):
    d = G.rot(G.THETA_OPEN, (1.0, 0.0))
    nrm = G.rot(G.THETA_OPEN, (0.0, -1.0))
    rel = pts - G.J
    over = (rel @ d) > -0.002
    return (rel @ nrm)[over]


def test_landed_pages_never_dip_under_the_open_cover():
    for sheets in (10, 25, 50):
        G.configure(sheets, 1.4318)
        n = G.N_SHEETS
        for layer in range(3):
            g = G.sheet_grid(n - 1 - layer, 'left', layer, ny=2)
            h = _height_above_cover(g[:, :, [0, 2]].reshape(-1, 2))
            assert h.min() >= G.SHEET_T / 2 + layer * G.PITCH - 1e-4, (sheets, layer, h.min())


def test_turning_page_stays_above_the_cover_and_landed_pages():
    G.configure(10, 1.4318)
    n = G.N_SHEETS
    for layer in range(3):
        for u in np.linspace(0, 1, 21):
            g = G.sheet_grid(n - 1 - layer, 'turn', layer, float(u), ny=2)
            h = _height_above_cover(g[:, :, [0, 2]].reshape(-1, 2))
            if len(h):
                assert h.min() - layer * G.PITCH > 0, (layer, u)


def test_paper_never_stretches():
    G.configure(10, 1.4318)
    g = G.sheet_grid(G.N_SHEETS - 1, 'turn', 0, 0.45, ny=4)
    mid = g[len(g) // 2]
    length = np.sum(np.linalg.norm(np.diff(mid, axis=0), axis=1))
    assert math.isclose(length, G.W, rel_tol=2e-3), length


def test_fore_edge_corners_are_rounded_like_the_page_art():
    v = G.rows(4)
    assert G.smax(v[0]) < G.W and G.smax(v[len(v) // 2]) == G.W
    assert math.isclose(G.smax(v[0]), G.W - G.RC)


def test_journal_template_uses_the_journal_script():
    book = templates.load(Path(__file__).parent / 'resources' / 'books' / 'leather-journal')
    assert book['engine'] == 'journal'
    scene_book = templates.for_scene(book)
    for key in ('front_exterior_image', 'back_exterior_image', 'front_interior_image',
                'back_interior_image', 'spine_exterior_image', 'paper_odd_image', 'paper_even_image'):
        assert scene_book[key] and Path(scene_book[key]).exists(), key
    with tempfile.TemporaryDirectory() as tmp:
        job = Path(tmp) / 'job.json'
        job.write_text(json.dumps({'book': scene_book}), encoding='utf-8')
        assert bb.scene_script(job).name == 'journal_scene.py'
        job.write_text(json.dumps({'book': {'engine': 'classic'}}), encoding='utf-8')
        assert bb.scene_script(job).name == 'book_scene.py'


def test_app_camera_settings_frame_the_journal():
    import camera_fit as cf
    G.configure(10, 1.4318)
    for name, preset in cf.PRESETS.items():
        cam, r, u, f, lens = G.camera(dict(preset, zoom=1.0, move='none'), 0.0, 16 / 9)
        assert np.all(np.isfinite(cam)) and lens > 0, name
        # the book centre is in front of the camera
        assert np.dot(np.array([0.0, 0.0, G.ZJ]) - cam, f) > 0, name
