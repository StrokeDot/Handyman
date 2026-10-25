"""Tests for the timeline editor (select, rearrange, trim, undo/redo)."""
from clips import Clip
from timeline_edit import TimelineEditor


def make():
    return TimelineEditor([Clip('open', 0, 20), Clip('turn', 20, 30), Clip('turn', 60, 30)])


def test_select():
    e = make()
    assert e.select(1) == 1
    assert e.select(9) is None


def test_move_and_undo():
    e = make()
    assert e.move(0, 2)
    assert [c.kind for c in e.clips()] == ['turn', 'turn', 'open']
    assert e.undo()
    assert [c.kind for c in e.clips()] == ['open', 'turn', 'turn']


def test_delete_and_undo():
    e = make()
    assert e.delete(1)
    assert len(e.clips()) == 2
    assert e.undo() and len(e.clips()) == 3


def test_duplicate():
    e = make()
    e.select(1)
    assert e.duplicate(1)
    clips = e.clips()
    assert len(clips) == 4
    assert clips[2].kind == 'turn'
    assert e.undo() and len(e.clips()) == 3


def test_trim():
    e = make()
    assert e.trim(1, start=25, duration=10)
    c = e.clips()[1]
    assert c.start == 25 and c.duration == 10
    assert e.undo()
    assert e.clips()[1].start == 20


def test_speed_and_smoothness():
    e = make()
    assert e.set_speed(1, 2.0, base_frames=30)
    assert e.clips()[1].duration == 15
    assert e.set_smoothness(1, 0.25)
    assert e.clips()[1].smoothness == 0.25
    assert e.undo()
    assert e.clips()[1].smoothness == 1.0


def test_redo_and_clear():
    e = make()
    e.delete(0)
    e.undo()
    assert e.can_redo()
    assert e.redo()
    assert len(e.clips()) == 2
    # a new edit clears the redo stack
    e.delete(0)
    assert not e.can_redo()


def test_history_bounds():
    e = make()
    assert not e.undo() and not e.redo()
    e.delete(0)
    assert e.can_undo()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
