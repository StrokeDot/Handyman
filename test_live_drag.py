"""Dragging in the live view: what a drag moves (cover or page, forward or back), and the pose it shows."""
import types

from live_view import LiveView as LV


class _Layout:
    def opening(self, o, slide=False, smoothness=1.0):
        return o * 3.14159, 0.0


def _view(manual=None, base=None, target=None, progress=0.0):
    sc = types.SimpleNamespace(layout=_Layout(), slide=False, smoothness=1.0)
    return types.SimpleNamespace(manual=manual, _drag_base=base, drag_target=target, drag_progress=progress, scene=sc)


def _pose(cover, sheets):
    return dict(cover_progress=cover, cover_angle=cover * 3.14159, cover_slide=0.0, sheet_progress=list(sheets))


def test_pulling_left_on_a_closed_book_opens_the_cover_not_a_page():
    assert LV._drag_target_for(None, _pose(0.0, [0, 0, 0]), +1) == ('cover', None)


def test_pulling_left_on_an_open_book_turns_the_next_page():
    assert LV._drag_target_for(None, _pose(1.0, [1, 0, 0]), +1) == ('sheet', 1)


def test_pulling_right_turns_the_last_page_back_then_closes_the_cover():
    assert LV._drag_target_for(None, _pose(1.0, [1, 1, 0]), -1) == ('sheet', 1)
    assert LV._drag_target_for(None, _pose(1.0, [0, 0, 0]), -1) == ('cover', None)
    assert LV._drag_target_for(None, _pose(0.0, [0, 0, 0]), -1) is None


def test_a_cover_drag_moves_the_cover_and_leaves_the_pages():
    v = _view(base={}, target=('cover', None), progress=0.4)
    p = LV._with_drag(v, _pose(0.0, [0, 0]))
    assert abs(p['cover_progress'] - 0.4) < 1e-9 and abs(p['cover_angle'] - 0.4 * 3.14159) < 1e-9
    assert p['sheet_progress'] == [0, 0]


def test_what_a_finished_drag_left_stays_shown():
    v = _view(manual={'cover': 1.0, 'sheets': {0: 1.0}})
    p = LV._with_drag(v, _pose(0.0, [0, 0]))
    assert p['cover_progress'] == 1.0 and p['sheet_progress'] == [1.0, 0]
