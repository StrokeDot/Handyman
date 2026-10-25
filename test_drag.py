"""Tests for drag-to-turn and record mode (pure logic)."""
from drag import DragState, new_turn_clip


def test_begin_sets_active_and_zero():
    d = DragState()
    d.begin(100, 50)
    assert d.active and d.progress == 0.0


def test_drag_left_turns_forward():
    d = DragState()
    d.begin(100, 50)
    p = d.move(50, 50, span=100)
    assert abs(p - 0.5) < 1e-12
    p = d.move(0, 50, span=100)
    assert p == 1.0


def test_drag_right_is_clamped_at_zero():
    d = DragState()
    d.begin(100, 50)
    assert d.move(200, 50, span=100) == 0.0


def test_finish_snaps_based_on_threshold():
    d = DragState()
    d.begin(100, 50)
    d.move(70, 50, span=100)      # 0.3
    assert d.finish() == 0.0
    d.begin(100, 50)
    d.move(20, 50, span=100)      # 0.8
    assert d.finish() == 1.0


def test_move_without_begin_does_nothing():
    d = DragState()
    assert d.move(10, 10, span=100) == 0.0
    assert d.finish() == 0.0


def test_recorded_clip():
    c = new_turn_clip(start_frame=10, base_frames=30, speed=2.0, smoothness=0.5)
    assert c.kind == 'turn' and c.start == 10
    assert c.duration == 15          # 30 / 2x
    assert c.smoothness == 0.5


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
