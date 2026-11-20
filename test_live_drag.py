"""Dragging in the live view: what a drag moves (cover or page, forward or back), and the pose it shows."""
import types

from live_view import LiveView as LV
from scene import Scene


def _view(manual=None, base=None, target=None, progress=0.0, opening_style='standard'):
    sc = Scene(2, slide=False, opening_style=opening_style)
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
    angle, _ = v.scene.layout.opening(0.4, slide=False)
    assert p['cover_progress'] == 0.4 and p['cover_angle'] == angle
    assert p['sheet_progress'] == [0, 0]


def test_what_a_finished_drag_left_stays_shown():
    v = _view(manual={'cover': 1.0, 'sheets': {0: 1.0}})
    p = LV._with_drag(v, _pose(0.0, [0, 0]))
    assert p['cover_progress'] == 1.0 and p['sheet_progress'] == [1.0, 0]


def test_dragging_the_cinematic_cover_recomputes_the_whole_book_pose():
    v = _view(base={}, target=('cover', None), progress=0.4, opening_style='cinematic')
    pose = LV._with_drag(v, v.scene.evaluate(0))
    assert pose['book_motion'] == v.scene.cover_pose(0.4)['book_motion']
    assert pose['book_motion'] != v.scene.evaluate(0)['book_motion']
    assert pose['sheet_progress'] == v.scene.evaluate(0)['sheet_progress']
