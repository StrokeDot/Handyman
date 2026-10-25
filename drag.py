"""Drag-to-turn (step 3): grab a page in the live preview and pull it over.

This is the pure part of the interaction. The Qt widget feeds mouse positions; this module
maps them to a turn progress (0..1) and, in record mode, to a timeline clip. Keeping it
pure means the drag behaviour is testable without a screen.
"""
from clips import Clip, speed_duration


class DragState:
    """One mouse drag on a page: grabbing it, moving, and letting go."""

    def __init__(self):
        self.active = False
        self.start_x = 0.0
        self.start_y = 0.0
        self.x = 0.0
        self.y = 0.0
        self.progress = 0.0

    def begin(self, x, y):
        """Grab the page at a point (pixels)."""
        self.active = True
        self.start_x, self.start_y = float(x), float(y)
        self.x, self.y = float(x), float(y)
        self.progress = 0.0

    def move(self, x, y, span):
        """Drag to a point. `span` is the pixel distance for a full turn (left = forward)."""
        if not self.active:
            return self.progress
        self.x, self.y = float(x), float(y)
        self.progress = min(1.0, max(0.0, (self.start_x - self.x) / max(1.0, float(span))))
        return self.progress

    def finish(self, complete_at=0.5):
        """Let go: snap to a full turn if dragged past `complete_at`, else back to the start."""
        if not self.active:
            return self.progress
        self.active = False
        self.progress = 1.0 if self.progress >= complete_at else 0.0
        return self.progress


def new_turn_clip(start_frame, base_frames, speed=1.0, smoothness=1.0):
    """Turn a finished drag into a timeline clip (record mode)."""
    return Clip('turn', int(start_frame), speed_duration(base_frames, speed), smoothness=smoothness)
