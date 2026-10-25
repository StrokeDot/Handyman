"""Scene and timeline core: one place that answers "where is everything at time t?".

A Scene owns the book's layout and its timeline of page turns. ``evaluate(frame)``
returns the pose of everything at that frame — the front cover's angle and slide, and
each turning sheet's progress — plus the camera's progress through the shot.

The live 3D view and the Blender export both read this same answer, so what you see in
the app is exactly what gets exported. This is step 1 of the rebuild: it reproduces
0.5.0's behaviour, and later steps (real pages, turn-to-page clips, dragging, the hands)
build on the same Scene.
"""
import book_model as bm
from page_curl import Timeline


class Scene:
    def __init__(self, turns, page_aspect=1.4, open_at=0.04, fps=30, start_hold=0.8,
                 turn_seconds=1.4, pause=0.8, end_hold=1.5, open_seconds=0.0, slide=True,
                 page_count=None, smoothness=1.0):
        self.turns = int(turns)
        if page_count:
            left_count = int(round(open_at * page_count))
            self.layout = bm.SheetLayout(page_aspect, page_count, left_count, self.turns)
        else:
            self.layout = bm.Layout(page_aspect, self.turns, open_at)
        self.turns = self.layout.turns   # follow any clamping the layout applied
        self.slide = bool(slide)
        self.smoothness = float(smoothness)
        self.timeline = Timeline(self.turns, fps, start_hold, turn_seconds, pause, end_hold,
                                 open_seconds)

    # The timing and page stack, exposed to the renderers and the tests.
    @property
    def fps(self):
        return self.timeline.fps

    @property
    def frames(self):
        return self.timeline.frames

    def opening(self, frame):
        """Front-cover opening progress (0 = closed, 1 = open)."""
        return self.timeline.opening(frame)

    def turn_start(self, k):
        return self.timeline.turn_start(k)

    def progress(self, frame, k):
        """Turn progress (0..1) of the k-th turning sheet."""
        return self.timeline.progress(frame, k)

    def sheet_levels(self, k):
        """Spine heights (right, left) of the k-th turning sheet."""
        return self.layout.sheet_levels(k)

    def evaluate(self, frame):
        """Everything's pose at `frame`. Both renderers draw from this one answer."""
        o = self.opening(frame)
        angle, slide = self.layout.opening(o, slide=self.slide, smoothness=self.smoothness)
        sheet_progress = [self.progress(frame, k) for k in range(self.turns)]
        return dict(
            frame=int(frame),
            cover_progress=o,
            cover_angle=angle,
            cover_slide=slide,
            smoothness=self.smoothness,
            sheet_progress=sheet_progress,
            active_turn=self.timeline.active_turn(frame),
            camera_frac=frame / max(1, self.frames - 1),
            frames=self.frames,
        )
