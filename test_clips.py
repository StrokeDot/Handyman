"""Tests for the step-3 timeline clips and the Smoothness/Speed engine."""
from clips import Clip, Timeline, ease_smooth, speed_duration


def test_ease_endpoints():
    for s in (0.0, 0.3, 0.5, 1.0):
        assert abs(ease_smooth(0.0, s) - 0.0) < 1e-12
        assert abs(ease_smooth(1.0, s) - 1.0) < 1e-12


def test_ease_linear_at_zero_smoothness():
    for t in (0.1, 0.25, 0.5, 0.75, 0.9):
        assert abs(ease_smooth(t, 0.0) - t) < 1e-12


def test_ease_is_smoothstep_at_full_smoothness():
    for t in (0.1, 0.3, 0.5, 0.7, 0.9):
        assert abs(ease_smooth(t, 1.0) - (t * t * (3 - 2 * t))) < 1e-12


def test_ease_is_monotonic():
    for s in (0.0, 0.5, 1.0):
        prev = -1
        for i in range(0, 101):
            v = ease_smooth(i / 100, s)
            assert v >= prev - 1e-12
            prev = v


def test_speed_duration():
    assert speed_duration(60, 1) == 60
    assert speed_duration(60, 2) == 30
    assert speed_duration(60, 0.5) == 120
    assert speed_duration(1, 10) == 1


def test_clip_progress_and_end():
    c = Clip('turn', start=10, duration=30, smoothness=1.0)
    assert c.end == 39
    assert c.progress(0) == 0.0
    assert c.progress(10) == 0.0
    assert abs(c.progress(39) - 1.0) < 1e-12
    assert c.raw(10) == 0.0 and c.raw(39) == 1.0


def test_clip_smoothness_changes_midpoint():
    raw = 15 / 29                          # duration-1 denominator
    linear = Clip('turn', 0, 30, smoothness=0.0).progress(15)
    smooth = Clip('turn', 0, 30, smoothness=1.0).progress(15)
    assert abs(linear - raw) < 1e-12
    assert abs(smooth - (raw * raw * (3 - 2 * raw))) < 1e-12


def test_timeline_frames_and_at():
    tl = Timeline([Clip('open', 0, 40), Clip('turn', 40, 30)])
    assert tl.frames == 70
    assert tl.at(0).kind == 'open'
    assert tl.at(39).kind == 'open'
    assert tl.at(40).kind == 'turn'
    assert tl.at(69).kind == 'turn'
    assert tl.at(1000).kind == 'turn'


def test_timeline_is_sorted():
    tl = Timeline([Clip('turn', 40, 30), Clip('open', 0, 40)])
    assert [c.kind for c in tl.clips] == ['open', 'turn']


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
