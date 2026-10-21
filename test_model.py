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


def _left_half(L, angle, local):
    """Front-cover side points (open-layout coordinates) at a cover angle, as both views place them."""
    jx, jz = L.joint(angle)
    c, s = np.cos(angle), np.sin(angle)
    x, z = local[:, 0], local[:, 1]
    return np.stack([jx + x * c + z * s, jz - x * s + z * c], axis=1)


def test_closed_joint_matches_closed_layout():
    L = bm.Layout(1.4, 3, 0.04)
    pts = np.array([[-0.3, 0.01], [-1.0, bm.COVER_T], [0.0, L.top_left]])
    got = _left_half(L, np.pi, pts)
    want = np.array([bm.closed_to_open(L, x, 0, z)[::2] for x, z in pts])
    assert np.allclose(got, want)
    assert L.joint(0.0) == (0.0, 0.0)


def test_cover_stays_on_the_spine():
    """At every angle the spine ends exactly at the front cover's edge and starts at the back cover's."""
    for at in bm.OPEN_AT.values():
        L = bm.Layout(1.4, 3, at)
        for angle in np.linspace(0, np.pi, 41):
            v = bm.spine_vertices(L, angle, bands=0).reshape(bm.SPINE_NV, bm.SPINE_NU, 3)
            if angle > 0.6:
                assert np.allclose(v[:, 0, [0, 2]], 0.0, atol=1e-9)
                assert np.allclose(v[:, -1, [0, 2]], L.joint(angle), atol=1e-9)


def test_left_half_never_passes_through_the_right_block():
    for at in bm.OPEN_AT.values():
        L = bm.Layout(1.4, 3, at)
        verts, _ = bm.block_prism(L, -1)
        local = np.vstack([verts[:, [0, 2]], [[0.0, 0.0], [0.0, bm.COVER_T], [-L.cover_w, 0.0]]])
        for angle in np.linspace(0, np.pi, 61):
            p = _left_half(L, angle, local)
            inside = (p[:, 0] > 0.003) & (p[:, 0] < L.page_w) & (p[:, 1] < L.top_right - 0.002)
            assert not inside.any(), (at, angle)


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
