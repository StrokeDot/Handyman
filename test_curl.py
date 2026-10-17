"""Checks for the page-turn geometry. Runs without Blender: python test_curl.py"""
import math
import numpy as np
from page_curl import sheet_vertices, Timeline, layout_pages, grid_faces, grid_uvs

W, H, NX, NY = 1.0, 1.4, 48, 24
ZR, ZL = 0.10, 0.10


def grid(t, **kw):
    return sheet_vertices(t, W, H, NX, NY, ZR, ZL, **kw).reshape(NY, NX, 3)


def test_rest_positions():
    a = grid(0.0)
    assert np.allclose(a[..., 0], np.linspace(0, W, NX)[None, :])
    assert np.allclose(a[..., 2], ZR)
    b = grid(1.0)
    assert np.allclose(b[..., 0], -np.linspace(0, W, NX)[None, :], atol=1e-9)
    assert np.allclose(b[..., 2], ZL, atol=1e-9)


def test_gutter_curve():
    from page_curl import gutter_rise
    rise = gutter_rise(W)
    assert 0.03 < rise < 0.1
    for t, sign in ((0.0, 1), (1.0, -1)):
        g = sheet_vertices(t, W, H, NX, NY, ZR, ZR, gutter=0.38).reshape(NY, NX, 3)
        assert np.allclose(g[:, 0, 2], ZR)                     # starts at the spine
        assert abs(g[0, -1, 2] - (ZR + rise)) < 2e-3           # outer part sits a rise higher
        assert np.all(np.diff(g[0, :, 2]) >= -1e-9)            # never dips
        assert sign * g[0, -1, 0] > 0.95 * W
        assert np.allclose(np.diff(g[:, -1, 2]), 0)            # same curve on every row


def test_paper_does_not_stretch_along_rows():
    for t in np.linspace(0, 1, 21):
        g = grid(t, gutter=0.38)
        seg = np.linalg.norm(np.diff(g, axis=1), axis=2).sum(axis=1)
        assert np.allclose(seg, W, rtol=2e-3), (t, seg.min(), seg.max())


def test_page_never_goes_through_the_book():
    for t in np.linspace(0, 1, 41):
        assert grid(t)[..., 2].min() >= min(ZR, ZL) - 1e-9


def test_corner_peels_first():
    g = grid(0.22)
    assert g[0, -1, 2] > ZR + 0.08          # bottom outer corner is up
    assert abs(g[-1, -1, 2] - ZR) < 1e-6    # top outer corner still on the page
    assert np.allclose(g[:, 0, 2], ZR)      # spine edge untouched


def test_page_lifts_and_bottom_corner_leads():
    g = grid(0.55)
    assert g[..., 2].max() > 0.5
    bottom_outer, top_outer = g[0, -1], g[-1, -1]
    assert bottom_outer[0] < top_outer[0]  # bottom corner has turned further


def test_hinge_moves_between_stacks():
    a = sheet_vertices(0.0, W, H, NX, NY, 0.12, 0.08).reshape(NY, NX, 3)
    b = sheet_vertices(1.0, W, H, NX, NY, 0.12, 0.08).reshape(NY, NX, 3)
    assert math.isclose(a[0, 0, 2], 0.12) and math.isclose(b[0, 0, 2], 0.08)


def test_timeline():
    tl = Timeline(3, 30, start_hold=1, turn_seconds=1.5, pause=0.5, end_hold=1)
    assert tl.frames == 30 + 3 * 45 + 2 * 15 + 30
    assert tl.progress(0, 0) == 0 and tl.progress(tl.frames - 1, 2) == 1
    assert tl.active_turn(tl.turn_start(1) + 10) == 1
    assert tl.active_turn(0) is None


def test_timeline_with_cover_opening():
    tl = Timeline(2, 30, start_hold=1, turn_seconds=1, pause=0.5, end_hold=1, open_seconds=2)
    assert tl.opening(0) == 0 and tl.opening(29) == 0
    assert tl.opening(30 + 59) == 1
    assert tl.turn_start(0) == 30 + 60 + 15
    assert tl.frames == 30 + 60 + 15 + 2 * 30 + 15 + 30
    assert Timeline(1, 30).opening(0) == 1


def test_layout():
    assert layout_pages(4) == (1, 0, [(1, 2)], 3)
    assert layout_pages(6) == (2, 0, [(1, 2), (3, 4)], 5)
    assert layout_pages(5) == (2, 0, [(1, 2), (3, 4)], None)
    assert layout_pages(1) == (1, 0, [(None, None)], None)


def test_mesh_tables():
    assert len(grid_faces(NX, NY)) == (NX - 1) * (NY - 1)
    assert grid_uvs(NX, NY).shape == (NX * NY, 2)


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
