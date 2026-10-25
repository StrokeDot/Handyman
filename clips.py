"""Timeline clips (step 3): the actions that make up a video.

Each clip is one action — open the cover, turn to a page, turn back, close — with a
**Smoothness** (0 = linear, 1 = gentle ease-in/out) and a **Speed** (how long it takes).
The app builds the curve from those two numbers, so the owner never sets keyframes by hand.

Pure data (no Qt, no Blender), so the live preview and the Blender export can share it.
"""


def clamp(t, lo=0.0, hi=1.0):
    return lo if t < lo else hi if t > hi else t


def ease_linear(t):
    return clamp(t)


def ease_smooth(t, smoothness=1.0):
    """Blend linear (smoothness 0) and a smooth ease-in/out (smoothness 1).

    At 0.5 it is a gentle in-between curve; this is what makes every action feel natural
    without the owner touching keyframes.
    """
    t = clamp(t)
    smooth = t * t * (3.0 - 2.0 * t)          # smoothstep
    return t + (smooth - t) * clamp(smoothness)


def speed_duration(base_frames, speed):
    """Frames a clip takes at `speed` (2x = half the frames, 0.5x = double)."""
    s = float(speed) if speed else 1.0
    return max(1, int(round(float(base_frames) / s)))


class Clip:
    """One action on the timeline with its own duration and easing."""

    def __init__(self, kind, start, duration, smoothness=1.0, **params):
        self.kind = kind                     # 'open' | 'turn' | 'turn_back' | 'close'
        self.start = int(start)              # first frame
        self.duration = int(max(1, duration))
        self.smoothness = clamp(float(smoothness))
        self.params = dict(params)           # e.g. {'to_page': 3}

    @property
    def end(self):
        return self.start + self.duration - 1

    def raw(self, frame):
        """Un-eased 0..1 position of the clip at a frame."""
        return clamp((frame - self.start) / max(1, self.duration - 1))

    def progress(self, frame):
        """Eased 0..1 position of the clip at a frame (what the renderers draw)."""
        return ease_smooth(self.raw(frame), self.smoothness)

    def __repr__(self):
        return (f'Clip({self.kind!r}, start={self.start}, duration={self.duration}, '
                f'smoothness={self.smoothness})')


class Timeline:
    """A list of clips answering \"what is happening at frame t\".

    Clips are expected not to overlap; the one with the latest start wins.
    """

    def __init__(self, clips=()):
        self.clips = sorted(clips, key=lambda c: (c.start, str(c.kind)))

    @property
    def frames(self):
        return max((c.end for c in self.clips), default=0) + 1

    def at(self, frame):
        """The clip covering `frame` (the last one that has started), or None."""
        active = None
        for c in self.clips:
            if c.start <= frame:
                active = c
        return active

    def progress(self, frame):
        c = self.at(frame)
        return c.progress(frame) if c else 0.0
