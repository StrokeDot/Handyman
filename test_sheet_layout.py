"""Tests for the step-2 real-pages geometry (book_model.SheetLayout)."""
import numpy as np

import book_model as bm


def test_counts_and_heights():
    L = bm.SheetLayout(1.4, 50, left_count=1, turns=2)
    assert L.page_count == 50
    assert L.left_count == 1 and L.right_count == 49 and L.turns == 2
    assert abs(L.h_left - bm.SHEET_GAP) < 1e-12
    assert abs(L.h_right - 49 * bm.SHEET_GAP) < 1e-12


def test_middle_splits_evenly():
    L = bm.SheetLayout(1.4, 50, left_count=25, turns=0)
    assert L.left_count == 25 and L.right_count == 25


def test_clamps():
    L = bm.SheetLayout(1.4, 4, left_count=0, turns=99)
    assert L.left_count == 1 and L.right_count == 3 and L.turns == 3


def test_levels_stack_consistently():
    L = bm.SheetLayout(1.4, 10, left_count=2, turns=3)
    # 2 resting left + 3 turning + (10 - 2 - 3) resting right = 10 sheets total.
    assert len(L.left_levels()) == 2
    assert len(L.right_levels()) == 5
    left, right = L.left_levels(), L.right_levels()
    assert all(a < b for a, b in zip(left, left[1:]))
    assert all(a < b for a, b in zip(right, right[1:]))
    # The first turning sheet rests on top of the right stack.
    r0, _ = L.turn_levels(0)
    assert r0 > right[-1]
    # Every turning sheet lands above the left stack, at its expected level.
    for t in range(3):
        _, l = L.turn_levels(t)
        assert l > left[-1]
        assert abs(l - (L.base_left + (2 + t) * bm.SHEET_GAP)) < 1e-12


def test_turn_levels_rise_on_the_right_as_t_grows():
    # Later turning sheets start lower on the right stack (they are further down).
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


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
