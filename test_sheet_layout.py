"""Tests for the step-2 real-pages geometry (book_model.SheetLayout + sheet_slice)."""
import numpy as np

import book_model as bm


def test_counts_and_heights():
    L = bm.SheetLayout(1.4, 50, left_count=1, turns=2)
    assert L.page_count == 50
    assert L.left_count == 1 and L.right_count == 49 and L.turns == 2
    assert L.left_rest_count == 1 and L.right_rest_count == 47
    assert abs(L.h_left - bm.SHEET_GAP) < 1e-12
    assert abs(L.h_right - 47 * bm.SHEET_GAP) < 1e-12


def test_middle_splits_evenly():
    L = bm.SheetLayout(1.4, 50, left_count=25, turns=0)
    assert L.left_count == 25 and L.right_count == 25
    assert L.left_rest_count == 25 and L.right_rest_count == 25


def test_clamps():
    L = bm.SheetLayout(1.4, 4, left_count=0, turns=99)
    assert L.left_count == 1 and L.right_count == 3 and L.turns == 3
    assert L.right_rest_count == 0


def test_turn_levels_formula():
    T = 3
    L = bm.SheetLayout(1.4, 1 + T + 1, left_count=1, turns=T)
    for t in range(T):
        r, l = L.turn_levels(t)
        assert abs(r - (L.base_right + (T - t) * bm.SHEET_GAP)) < 1e-12
        assert abs(l - (L.base_left + (t + 1) * bm.SHEET_GAP)) < 1e-12


def test_turn_levels_rise_on_the_right_as_t_grows():
    L = bm.SheetLayout(1.4, 10, left_count=1, turns=4)
    rights = [L.turn_levels(t)[0] for t in range(4)]
    assert all(a > b for a, b in zip(rights, rights[1:]))  # decreasing with t


def test_hinge_is_half_the_closed_paper():
    L = bm.SheetLayout(1.4, 50, 1, 1)
    assert abs(L.hinge - (bm.COVER_T + 50 * bm.SHEET_GAP / 2 + 0.0008)) < 1e-12


def test_cover_still_lands_on_top_when_closed():
    for n in (4, 12, 50):
        L = bm.SheetLayout(1.4, n, left_count=max(1, n // 4), turns=1)
        flipped = 2 * L.hinge - L.top_left
        assert flipped > L.top_right, n


def test_page_count_too_small_raises():
    try:
        bm.SheetLayout(1.4, 1)
    except ValueError:
        pass
    else:
        raise AssertionError('SheetLayout(page_count=1) should raise')


def _normal(p):
    n = np.zeros(3)
    for i in range(len(p)):
        a, b = p[i], p[(i + 1) % len(p)]
        n += [(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]),
              (a[0] - b[0]) * (a[1] + b[1])]
    return n


def test_sheet_slice_winding_directions():
    L = bm.SheetLayout(1.4, 10, left_count=2, turns=3)
    for side in (1, -1):
        count = L.right_rest_count if side > 0 else L.left_rest_count
        for j in range(count):
            v, faces = bm.sheet_slice(L, side, j, count)
            n = len(v) // 4
            for i in range(n - 1):
                assert _normal(v[list(faces[i])])[2] > 0            # top surface: +z
            for i in range(n - 1):
                assert _normal(v[list(faces[n - 1 + i])])[2] < 0    # bottom surface: -z
            fore = _normal(v[list(faces[2 * (n - 1)])])
            assert fore[0] * side > 0                                # fore edge: outward x
            spine = _normal(v[list(faces[2 * (n - 1) + 1])])
            assert spine[0] * side < 0                               # spine edge: inward x
            e0 = _normal(v[list(faces[2 * (n - 1) + 2])])
            e1 = _normal(v[list(faces[2 * (n - 1) + 3])])
            assert e0[1] * e1[1] < 0                                 # the two ends point opposite y


def test_sheet_slice_nests_without_gaps():
    L = bm.SheetLayout(1.4, 10, left_count=1, turns=2)
    count = L.right_rest_count
    v0, _ = bm.sheet_slice(L, 1, 0, count)   # top sheet
    v1, _ = bm.sheet_slice(L, 1, 1, count)
    n = len(v0) // 4
    assert np.allclose(v0[n:2 * n, 2], v1[0:n, 2])        # y0: sheet0 bottom == sheet1 top
    assert np.allclose(v0[3 * n:4 * n, 2], v1[2 * n:3 * n, 2])  # y1: same


def test_sheet_slice_bottom_sheet_sits_on_the_cover():
    L = bm.SheetLayout(1.4, 10, left_count=1, turns=2)
    count = L.right_rest_count
    v, _ = bm.sheet_slice(L, 1, count - 1, count)
    n = len(v) // 4
    assert np.allclose(v[n:2 * n, 2], bm.COVER_T)
    assert np.allclose(v[3 * n:4 * n, 2], bm.COVER_T)


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
