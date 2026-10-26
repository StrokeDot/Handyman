"""Book layout checks: the cover opens alone, nothing passes through anything."""
import numpy as np

import book_model as bm
from page_curl import sheet_vertices


def test_open_at_beginning_keeps_pages_on_the_right():
    L = bm.Layout(1.4, 3, bm.OPEN_AT['Beginning (only the cover opens)'])
    assert L.h_left < 0.01 and L.h_right > 0.1
    assert L.base_left >= bm.COVER_T - 1e-9        # thin left curve stays above the cover
    assert L.rise_left <= L.h_left


def test_closed_cover_lands_on_top():
    for at in bm.OPEN_AT.values():
        L = bm.Layout(1.4, 4, at)
        # Left page flat level, flipped over the hinge, must sit above the right stack + its sheets.
        flipped = 2 * L.hinge - L.top_left
        assert flipped > L.top_right + L.turns * bm.SHEET_GAP


def test_blocks_face_outwards():
    for at in bm.OPEN_AT.values():
        L = bm.Layout(1.4, 2, at)
        for side in (1, -1):
            v, faces = bm.block_prism(L, side)
            c = v.mean(0)
            for f in faces:
                p = v[list(f)]
                n = np.zeros(3)
                for i in range(len(p)):
                    a, b = p[i], p[(i + 1) % len(p)]
                    n += [(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])]
                assert n @ (p.mean(0) - c) > 0


def test_turning_sheet_moves_between_the_two_stacks():
    L = bm.Layout(1.4, 2, 0.04)
    zr, zl = L.sheet_levels(0)
    a = sheet_vertices(0.0, 1.0, L.page_h, 30, 10, zr, zl, gutter=L.gutter).reshape(10, 30, 3)
    b = sheet_vertices(1.0, 1.0, L.page_h, 30, 10, zr, zl, gutter=L.gutter).reshape(10, 30, 3)
    assert abs(a[0, -1, 2] - (zr + L.rise_right)) < 3e-3     # rests flat on the right stack
    assert abs(b[0, -1, 2] - (zl + L.rise_left)) < 3e-3      # and flat on the thin left stack
    assert b[0, -1, 0] < -0.95


def test_opening_motion():
    L = bm.Layout(1.4, 1, 0.04)
    assert L.opening(0.0) == (np.pi, -L.cover_w / 2)
    assert L.opening(1.0) == (0.0, 0.0)


def test_spine_shapes():
    o, c, f = bm.spine_shapes(bm.Layout())
    assert o.shape == c.shape and len(f) > 0
    assert np.isclose(c[:, 2].max(), 2 * bm.Layout().hinge)


def test_hinge_ribbon_stays_glued_to_the_boards():
    L = bm.Layout(1.4, 4, 0.04)
    for angle in (0.0, np.pi / 4, np.pi / 2, np.pi):
        verts, faces = bm.hinge_ribbon(L, angle, nu=7)
        assert len(faces) > 0
        back, front = verts[0], verts[6]               # first row: t=0 .. t=1
        assert np.isclose(back[2], bm.COVER_T, atol=1e-9)   # glued to the back board
        expected = L.hinge + (bm.COVER_T - L.hinge) * np.cos(angle)
        assert np.isclose(front[2], expected, atol=1e-9)    # glued to the front board
        assert abs(back[0]) < 1e-9 and abs(front[0]) < 1e-9  # both edges lie on the hinge line


def test_fit_uv_frames_without_touching_geometry():
    # A tall image on a wide surface: 'fit' shrinks it in x, 'fill' overflows, 'stretch' is 1:1.
    sx, sy, ox, oy = bm.fit_uv(2.0, 1.4, 'fit')
    assert sx < 1.0 and sy == 1.0
    assert np.isclose(ox, (1 - sx) / 2) and oy == 0.0
    fx, fy, _, _ = bm.fit_uv(2.0, 1.4, 'fill')
    assert fx >= 1.0 and fy >= 1.0
    assert bm.fit_uv(2.0, 1.4, 'stretch')[:2] == (1.0, 1.0)
    zx, _, zox, _ = bm.fit_uv(2.0, 1.4, 'fit', scale=2.0, x=0.1)
    assert np.isclose(zx, sx * 2.0) and np.isclose(zox, (1 - zx) / 2 + 0.1)


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
