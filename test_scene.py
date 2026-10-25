"""The new Scene core must reproduce 0.5.0 exactly (same layout, same timing).

Compares scene.Scene against the page_curl.Timeline + book_model.Layout that 0.5.0 uses,
across several books and settings.
"""
import numpy as np

import book_model as bm
import scene
from page_curl import Timeline, layout_pages


def values(**over):
    v = dict(fps=30, start_hold=0.8, turn_seconds=1.4, pause=0.8, end_hold=1.5,
             start_closed=True, open_seconds=1.6, open_at=0.04)
    v.update(over)
    return v


def test_frames_match_timeline():
    for turns in (1, 2, 3, 5):
        for start_closed in (True, False):
            v = values(start_closed=start_closed)
            s = scene.Scene(turns, 1.4, v['open_at'], v['fps'], v['start_hold'], v['turn_seconds'],
                            v['pause'], v['end_hold'], v['open_seconds'] if start_closed else 0.0,
                            start_closed)
            tl = Timeline(turns, v['fps'], v['start_hold'], v['turn_seconds'], v['pause'],
                          v['end_hold'], v['open_seconds'] if start_closed else 0.0)
            assert s.frames == tl.frames, (turns, start_closed)


def test_evaluate_matches_0_5_0_pose():
    for n_images in (1, 2, 5, 8):
        for start_closed in (True, False):
            v = values(start_closed=start_closed)
            turns = layout_pages(n_images)[0]
            s = scene.Scene(turns, 1.4, v['open_at'], v['fps'], v['start_hold'], v['turn_seconds'],
                            v['pause'], v['end_hold'], v['open_seconds'] if start_closed else 0.0,
                            start_closed)
            tl = Timeline(turns, v['fps'], v['start_hold'], v['turn_seconds'], v['pause'],
                          v['end_hold'], v['open_seconds'] if start_closed else 0.0)
            L = bm.Layout(1.4, turns, v['open_at'])
            frames = list(range(0, tl.frames, 3)) + [tl.frames - 1]
            for f in frames:
                pose = s.evaluate(f)
                o = tl.opening(f)
                angle, slide = L.opening(o, slide=start_closed)
                assert abs(pose['cover_progress'] - o) < 1e-12
                assert abs(pose['cover_angle'] - angle) < 1e-12
                assert abs(pose['cover_slide'] - slide) < 1e-12
                assert pose['frames'] == tl.frames
                assert abs(pose['camera_frac'] - f / max(1, tl.frames - 1)) < 1e-12
                for k in range(turns):
                    assert abs(pose['sheet_progress'][k] - tl.progress(f, k)) < 1e-12, (f, k)
                assert pose['active_turn'] == tl.active_turn(f), f


def test_sheet_levels_match_layout():
    for open_at in bm.OPEN_AT.values():
        L = bm.Layout(1.4, 3, open_at)
        s = scene.Scene(3, 1.4, open_at)
        for k in range(3):
            assert s.sheet_levels(k) == L.sheet_levels(k)


def test_open_start_has_no_cover_motion():
    s = scene.Scene(2, 1.4, 0.04, open_seconds=0.0, slide=False)
    for f in (0, 10, s.frames - 1):
        pose = s.evaluate(f)
        assert pose['cover_progress'] == 1.0
        assert pose['cover_angle'] == 0.0
        assert pose['cover_slide'] == 0.0


def test_scene_with_page_count_uses_sheet_layout():
    s = scene.Scene(3, page_aspect=1.4, open_at=0.04, page_count=20)
    assert isinstance(s.layout, bm.SheetLayout)
    assert s.layout.page_count == 20
    assert s.turns == s.layout.turns
    pose = s.evaluate(0)
    assert len(pose['sheet_progress']) == s.turns


def test_scene_smoothness_changes_cover():
    a = scene.Scene(2, 1.4, 0.04, open_seconds=1.0, smoothness=0.0)
    b = scene.Scene(2, 1.4, 0.04, open_seconds=1.0, smoothness=1.0)
    f = a.timeline.start + max(1, a.timeline.open // 2)   # mid cover-opening
    pa, pb = a.evaluate(f), b.evaluate(f)
    assert pa['smoothness'] == 0.0 and pb['smoothness'] == 1.0
    assert pa['cover_angle'] != pb['cover_angle']


def test_scene_with_recorded_clips_extends_timeline():
    base = scene.Scene(2, 1.4, 0.04, page_count=20)
    rec = scene.Scene(2, 1.4, 0.04, page_count=20,
                      recorded_clips=[{'duration': 20, 'smoothness': 0.5}])
    assert rec.turns == base.turns + 1
    assert rec.timeline.frames > base.timeline.frames
    assert len(rec.evaluate(0)['sheet_progress']) == rec.turns


def test_scene_from_clip_list():
    from clips import Clip, clip_to_dict
    clips = [clip_to_dict(Clip('open', 0, 20)), clip_to_dict(Clip('turn', 20, 30)),
             clip_to_dict(Clip('turn', 60, 30))]
    s = scene.Scene(2, 1.4, 0.04, page_count=20, clip_list=clips)
    assert s.turns == 2
    assert s.frames == 90                       # last turn ends at 89
    assert len(s.evaluate(0)['sheet_progress']) == 2
    assert s.evaluate(10)['cover_progress'] > 0


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
