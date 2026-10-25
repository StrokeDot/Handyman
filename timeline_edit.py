"""Timeline editing (step 3): select, rearrange, trim and undo clips.

Pure model, no Qt. The timeline panel calls these operations and redraws; the Scene reads
`clips()` to play them. Undo/redo keeps a snapshot stack, so every edit is reversible.
"""
import copy

from clips import speed_duration


class TimelineEditor:
    """An editable list of clips with selection, trimming and undo/redo."""

    def __init__(self, clips=None):
        self._clips = [copy.copy(c) for c in (clips or [])]
        self._undo = []
        self._redo = []
        self.selected = None

    def clips(self):
        return list(self._clips)

    # ------------------------------------------------------------ history
    def _push(self):
        self._undo.append(copy.deepcopy(self._clips))
        self._redo.clear()

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if not self._undo:
            return False
        self._redo.append(copy.deepcopy(self._clips))
        self._clips = self._undo.pop()
        self.selected = None
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append(copy.deepcopy(self._clips))
        self._clips = self._redo.pop()
        self.selected = None
        return True

    # ---------------------------------------------------------- selection
    def select(self, index):
        self.selected = index if 0 <= index < len(self._clips) else None
        return self.selected

    # -------------------------------------------------------------- edits
    def move(self, index, to):
        """Rearrange a clip (its order in the list)."""
        n = len(self._clips)
        if not (0 <= index < n and 0 <= to < n):
            return False
        self._push()
        c = self._clips.pop(index)
        self._clips.insert(to, c)
        self.selected = to
        return True

    def reorder(self, order):
        """Reorder clips by a list of old indices (used by drag-reorder)."""
        if sorted(order) != list(range(len(self._clips))):
            return False
        self._push()
        self._clips = [self._clips[i] for i in order]
        self.selected = None
        return True

    def delete(self, index):
        if not (0 <= index < len(self._clips)):
            return False
        self._push()
        del self._clips[index]
        self.selected = None
        return True

    def duplicate(self, index):
        if not (0 <= index < len(self._clips)):
            return False
        self._push()
        c = copy.copy(self._clips[index])
        c.start = self._clips[index].start + self._clips[index].duration
        self._clips.insert(index + 1, c)
        self.selected = index + 1
        return True

    def trim(self, index, start=None, duration=None):
        if not (0 <= index < len(self._clips)):
            return False
        self._push()
        c = self._clips[index]
        if start is not None:
            c.start = max(0, int(start))
        if duration is not None:
            c.duration = max(1, int(duration))
        return True

    def set_smoothness(self, index, value):
        if not (0 <= index < len(self._clips)):
            return False
        self._push()
        self._clips[index].smoothness = max(0.0, min(1.0, float(value)))
        return True

    def set_speed(self, index, speed, base_frames):
        if not (0 <= index < len(self._clips)):
            return False
        self._push()
        self._clips[index].duration = speed_duration(base_frames, speed)
        return True
