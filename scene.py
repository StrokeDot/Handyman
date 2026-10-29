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
from clips import Clip, ClipTimeline, clip_from_dict


class Scene:
    def __init__(self, turns, page_aspect=1.4, open_at=0.04, fps=30, start_hold=0.8,
                 turn_seconds=1.4, pause=0.8, end_hold=1.5, open_seconds=0.0, slide=True,
                 page_count=None, smoothness=1.0, recorded_clips=None, clip_list=None):
        self.slide = bool(slide)
        self.smoothness = float(smoothness)
        # Physical model: every configured sheet exists. start_index sheets are already flipped
        # left (state 1.0), the next `turns` sheets animate, the rest stay right (state 0.0).
        self.start_index = 0
        self.page_count = int(page_count) if page_count else 0
        if clip_list is not None:
            clips = [clip_from_dict(d) for d in clip_list]
            self.turns = sum(1 for c in clips if c.kind == 'turn')
            if page_count:
                # Sheets already flipped on the left when the animation starts. Floor, not round:
                # a near-zero opening position must mean ZERO left sheets.
                self.start_index = int(float(open_at) * int(page_count))
                self.page_count = int(page_count)
                self.layout = bm.SheetLayout(page_aspect, page_count, self.start_index, self.turns)
            else:
                self.layout = bm.Layout(page_aspect, self.turns, open_at)
            self.turns = self.layout.turns   # follow any clamping the layout applied
            self.timeline = ClipTimeline.from_clips(clips, fps)
        else:
            extra = list(recorded_clips or [])
            self.turns = int(turns) + len(extra)
            if page_count:
                # Sheets already flipped on the left when the animation starts. Floor, not round:
                # a near-zero opening position must mean ZERO left sheets.
                self.start_index = int(float(open_at) * int(page_count))
                self.page_count = int(page_count)
                self.layout = bm.SheetLayout(page_aspect, page_count, self.start_index, self.turns)
            else:
                self.layout = bm.Layout(page_aspect, self.turns, open_at)
            self.turns = self.layout.turns   # follow any clamping the layout applied
            self.timeline = ClipTimeline(self.turns - len(extra), fps, start_hold, turn_seconds,
                                         pause, end_hold, open_seconds, smoothness=self.smoothness)
            for rc in extra:
                self.timeline.add_turn_clip(Clip(
                    'turn', 0, int(rc.get('duration', self.timeline.turn)),
                    smoothness=float(rc.get('smoothness', self.smoothness))))

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
        # One state entry per PHYSICAL sheet, so state and geometry arrays always match.
        # Sheets before the start are already left; scheduled sheets animate; the rest stay right.
        sheet_progress = []
        for k in range(self.page_count):
            if k < self.start_index:
                sheet_progress.append(1.0)
            elif k < self.start_index + self.turns:
                sheet_progress.append(self.progress(frame, k - self.start_index))
            else:
                sheet_progress.append(0.0)
        if not sheet_progress:
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
