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
    rel = pts - G.J_OPEN
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


def _png_size(path):
    import struct
    with open(path, 'rb') as fh:
        head = fh.read(24)
    return struct.unpack('>II', head[16:24])


def test_bundled_journal_images_have_the_sizes_the_template_requires():
    folder = Path(__file__).parent / 'resources' / 'books' / 'leather-journal'
    book = templates.load(folder)
    sizes = book['image_sizes']
    for field, (w, h) in sizes.items():
        if field == 'page':
            continue
        assert _png_size(folder / book[field]) == (w, h), field


def test_covers_match_the_board_shape_so_nothing_is_stretched():
    folder = Path(__file__).parent / 'resources' / 'books' / 'leather-journal'
    book = templates.load(folder)
    G.configure(int(book['page_count']), float(book['page_aspect']))
    w, h = book['image_sizes']['front_exterior_image']
    assert abs(h / w - G.HC / G.WC) < 0.002
    pw, ph = book['image_sizes']['page']
    assert abs(ph / pw - G.H / G.W) < 0.002


def test_saving_a_journal_keeps_its_engine_page_count_and_sizes():
    import paths
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(__file__).parent / 'resources' / 'books' / 'leather-journal'
        book = templates.load(src)
        book['folder'] = str(Path(tmp) / 'copy')
        saved = templates.save(book)
        assert saved['engine'] == 'journal'
        assert int(saved['page_count']) == 10
        assert saved['image_sizes']['page'] == [982, 1406]


def test_standing_page_stays_inside_the_picture_on_every_preset():
    import camera_fit as cf
    G.configure(10, 1.4318)
    for name, preset in cf.PRESETS.items():
        cam, r, u, f, lens = G.camera(dict(preset, zoom=1.0, move='none'), 0.0, 16 / 9)
        pts = np.concatenate([G.sheet_grid(G.N_SHEETS - 1, 'turn', 0, float(t), ny=4).reshape(-1, 3)
                              for t in np.linspace(0, 1, 41)])
        x, y, _ = cf.project(pts, cam, r, u, f, lens, 16 / 9)
        assert np.abs(x).max() < 0.95 and np.abs(y).max() < 0.95, (name, np.abs(x).max(), np.abs(y).max())


def test_every_page_shape_and_turn_style_stays_clear():
    """Curved pages and all turn styles: landed pages above the cover and each other, turning
    pages above the stack, paper never stretched."""
    for shape in ('flat', 'curved', 'very curved'):
        for style in ('natural', 'corner peel', 'quick'):
            G.configure(10, 1.4318, page_shape=shape, turn_style=style)
            n = G.N_SHEETS
            for layer in range(2):
                g = G.sheet_grid(n - 1 - layer, 'left', layer, ny=2)
                h = _height_above_cover(g[:, :, [0, 2]].reshape(-1, 2))
                assert h.min() >= G.SHEET_T / 2 + layer * G.PITCH - 1e-4, (shape, style, layer)
            for u in np.linspace(0, 1, 11):
                g = G.sheet_grid(n - 1, 'turn', 0, float(u), ny=4)
                mid = g[len(g) // 2]
                length = np.sum(np.linalg.norm(np.diff(mid, axis=0), axis=1))
                assert math.isclose(length, G.W, rel_tol=3e-3), (shape, style, u, length)
    G.configure(10, 1.4318, page_shape='flat', turn_style='natural')


def test_curved_pages_rise_out_of_the_spine():
    G.configure(10, 1.4318, page_shape='very curved')
    r = G.sheet_grid(G.N_SHEETS - 1, 'right', ny=2)[8]
    assert r[:, 2].max() - r[-1, 2] > 0.05          # an arch well above the fore-edge
    G.configure(10, 1.4318, page_shape='flat')
    r = G.sheet_grid(G.N_SHEETS - 1, 'right', ny=2)[8]
    assert r[:, 2].max() - r[-1, 2] < 1e-3


def test_curved_pages_never_push_through_the_cover_while_it_opens():
    """Closed book: pages flat under the cover. Opening: the curve grows only as the cover lifts."""
    for shape in ('flat', 'curved', 'very curved'):
        for sheets in (10, 25, 50):
            G.configure(sheets, 1.4318, page_shape=shape)
            for frac in np.linspace(0, 1, 26):
                th = frac * G.THETA_OPEN
                G.set_opening(th)
                d = np.array([np.cos(th), np.sin(th)])
                n = np.array([-np.sin(th), np.cos(th)])
                g = G.sheet_grid(G.N_SHEETS - 1, 'right', ny=2)[:, :, [0, 2]].reshape(-1, 2)
                rel = g - G.cover_pivot(th)
                under = (rel @ d > -0.01) & (rel @ d < G.WC)
                if under.any():
                    assert (-(rel @ n))[under].min() >= G.SHEET_T / 2, (shape, sheets, frac)
    G.set_opening(G.THETA_OPEN)
    G.configure(10, 1.4318, page_shape='flat')



def test_open_book_is_level_left_and_right():
    """The open cover lies flat at the same height as the back cover: the two halves match."""
    G.configure(10, 1.4318)
    th = G.THETA_OPEN
    p = G.cover_pivot(th)
    inner_left = p[1]                              # open cover's inner face height
    assert abs(inner_left - G.TB) < 1e-9           # back cover's inner face is at TB too
    assert abs(G.rot(th, (1.0, 0.0))[1]) < 1e-9    # and it is flat (no tilt)
    # the closed cover still sits on top of the text block
    assert np.allclose(G.cover_pivot(0.0), G.J)


def test_pages_are_sewn_at_a_fixed_spot_on_the_spine():
    """A page turns about its own seam; the seam does not move while it turns."""
    G.configure(10, 1.4318)
    G.set_opening(G.THETA_OPEN)
    n = G.N_SHEETS
    for k in (0, 4, 9):
        seam = G.binding(n - 1 - k)
        assert np.allclose(G.binding_left(k), seam)
        for u in (0.0, 0.3, 0.7, 1.0):
            g = G.sheet_grid(n - 1 - k, 'turn', k, u, ny=2)
            row = g[len(g) // 2]
            assert np.allclose(row[0, [0, 2]], seam, atol=1e-6), (k, u)


def test_open_spine_is_a_hump_between_the_covers_with_pages_sewn_along_it():
    G.configure(10, 1.4318)
    G.set_opening(G.THETA_OPEN)
    seams = np.array([G.open_seam(k) for k in range(G.N_SHEETS)])
    assert seams[:, 0].min() >= G.J_OPEN[0] - 1e-9 and seams[:, 0].max() <= G.XB + 1e-9   # between the covers
    assert seams[:, 1].max() > G.TB + 0.5 * G.spine_hump_height()                          # a real hump
    mid = seams[:, 1].argmax()
    assert 2 <= mid <= G.N_SHEETS - 3                                                       # highest in the middle
    G.set_opening(0.0)
    closed = np.array([G.binding(j) for j in range(G.N_SHEETS)])
    assert np.allclose(closed[:, 0], 0.0)                                                   # closed: a column
    G.set_opening(G.THETA_OPEN)


def test_only_the_visible_spread_is_curved():
    """Just opened: flat. While a page turns, it and the page it reveals curve; the page it lands
    on goes flat; every page underneath stays flat."""
    w = G.curve_weights
    assert w([0, 0, 0, 0]) == [0, 0, 0, 0]                       # just opened: flat
    assert w([0.5, 0, 0, 0])[:2] == [0.5, 0.5]                   # curving as page 1 turns
    assert w([1, 0, 0, 0]) == [1, 1, 0, 0]                       # page 1 landed: the spread is curved
    mid = w([1, 0.4, 0, 0])
    assert abs(mid[0] - 0.6) < 1e-9 and mid[1] == 1 and abs(mid[2] - 0.4) < 1e-9
    assert w([1, 1, 0, 0]) == [0, 1, 1, 0]                       # page 1 now covered: flat
    assert w([1, 1, 1, 0]) == [0, 0, 1, 1]                       # last spread: curved
    assert w([1, 1, 1, 0.5])[2:] == [0.5, 0.5]                   # last page turning: both relax
    assert w([1, 1, 1, 1]) == [0, 0, 0, 0]                       # last page landed: flat, like the first


def test_travelling_curve_never_makes_pages_touch():
    def mind(a, b):
        return min(np.min(np.linalg.norm(a[i][:, None] - b[i][None], axis=2)) for i in range(0, a.shape[0], 4))
    G.configure(10, 1.4318, page_shape='very curved')
    G.set_opening(G.THETA_OPEN)
    n = G.N_SHEETS
    for landed in (0, 1, 4, n - 2, n - 1):
        for u in np.linspace(0, 1, 9):
            prog = [1.0] * landed + [float(u)] + [0.0] * (n - landed - 1)
            cw = G.curve_weights(prog)
            sh = [G.sheet_grid(n - 1 - k, 'right' if p <= 0 else ('left' if p >= 1 else 'turn'), k, float(p),
                               ny=2, curve=cw[k])[:, :, [0, 2]] for k, p in enumerate(prog)]
            for a in range(max(0, landed - 2), min(n - 1, landed + 2)):
                assert mind(sh[a], sh[a + 1]) >= G.SHEET_T - 1e-4, (landed, u, a)
    G.configure(10, 1.4318, page_shape='flat')
