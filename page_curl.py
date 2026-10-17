"""Page-turn geometry and timeline, shared by the Blender scene, the app and the tests.

Pure numpy, no Blender import, so it can be tested anywhere.

Book space:
  x  across the book; the spine is at x = 0, right-hand pages lie at x > 0
  y  up the page; the page spans -H/2 .. +H/2
  z  up out of the book

A sheet is a grid of nx (across) by ny (up) vertices. Vertex index = row * nx + col,
row 0 is the bottom edge, col 0 is the spine edge.
"""
import math
import numpy as np

PEEL_SHARE = 0.28   # part of each turn spent lifting the corner before the page goes over
GUTTER = 0.5        # how steeply a resting page rises out of the spine (radians at the spine)
GUTTER_POWER = 5.0  # higher = the curve stays closer to the spine


def gutter_angle(s, width, gutter=GUTTER):
    """Extra angle of a resting page near the spine: the curve of a real open book."""
    return gutter * (1.0 - np.asarray(s) / width) ** GUTTER_POWER


def gutter_rise(width, gutter=GUTTER, n=400):
    """How much higher the flat part of a resting page is than the spine."""
    s = np.linspace(0.0, width, n)
    return float(np.trapezoid(np.sin(gutter_angle(s, width, gutter)), s)) if hasattr(np, 'trapezoid') \
        else float(np.trapz(np.sin(gutter_angle(s, width, gutter)), s))


def rest_profile(width, nx, gutter=GUTTER):
    """(x, z) of a resting right-hand page from the spine outwards, z relative to the spine."""
    s = np.linspace(0.0, width, nx)
    a = gutter_angle(s, width, gutter)
    ds = width / (nx - 1)
    x = np.concatenate([[0.0], np.cumsum((np.cos(a[1:]) + np.cos(a[:-1])) * 0.5 * ds)])
    z = np.concatenate([[0.0], np.cumsum((np.sin(a[1:]) + np.sin(a[:-1])) * 0.5 * ds)])
    return x, z


def ease(t):
    """Smooth start and stop (smoothstep)."""
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def sheet_vertices(p, width, height, nx, ny, z_right, z_left,
                   curl=0.9, lag=0.10, corner=0.6, power=1.6, peel=1.1, peel_share=PEEL_SHARE, gutter=0.0):
    """Vertex positions of one sheet at turn progress p (0 = flat right, 1 = flat left).

    The first `peel_share` of the turn lifts the bottom outer corner (the hand grabbing it),
    then the page goes over.
    curl   how strongly the page bends while turning (radians at the outer edge)
    lag    how far the top edge trails the bottom edge
    corner extra curl near the bottom corner
    peel   how far the corner lifts before the turn (radians at the corner)
    gutter curve of a resting page out of the spine (0 = flat). z_right / z_left are the spine
           heights; the flat part of a resting page sits gutter_rise() higher.
    Returns float array of shape (ny * nx, 3).
    """
    p = float(np.clip(p, 0.0, 1.0))
    if peel_share > 0:
        lift = float(ease(p / peel_share))
        t = max(0.0, (p - peel_share) / (1.0 - peel_share))
    else:
        lift, t = 0.0, p
    s = np.linspace(0.0, width, nx)
    v = np.linspace(0.0, 1.0, ny)
    ds = width / (nx - 1)

    # Each row runs on a slightly delayed clock: the bottom corner leads.
    tr = np.clip(t * (1.0 + lag) - lag * v, 0.0, 1.0)
    theta = math.pi * ease(tr)
    bend = curl * np.sin(math.pi * tr) * (1.0 + corner * (1.0 - v))
    frac = (s / width) ** power
    angle = theta[:, None] + bend[:, None] * frac[None, :]
    if gutter:
        # Resting on the right the page rises out of the spine; resting on the left, mirrored.
        angle = angle + gutter_angle(s, width, gutter)[None, :] * (1.0 - 2.0 * ease(tr))[:, None]

    # Corner peel: only the outer part of the lower rows, fading out as the turn gets going.
    hold = lift * (1.0 - float(ease(t / 0.45)))
    if hold > 0:
        rows = (1.0 - v) ** 1.5
        cols = np.clip((s / width - 0.55) / 0.45, 0.0, 1.0) ** 2
        angle = angle + peel * hold * rows[:, None] * cols[None, :]
    angle = np.clip(angle, 0.0, math.pi)

    ca, sa = np.cos(angle), np.sin(angle)
    x = np.zeros_like(angle)
    z = np.zeros_like(angle)
    x[:, 1:] = np.cumsum((ca[:, 1:] + ca[:, :-1]) * 0.5 * ds, axis=1)
    z[:, 1:] = np.cumsum((sa[:, 1:] + sa[:, :-1]) * 0.5 * ds, axis=1)

    hinge = z_right + (z_left - z_right) * float(ease(t))
    y = (v - 0.5) * height
    out = np.empty((ny, nx, 3))
    out[..., 0] = x
    out[..., 1] = y[:, None]
    out[..., 2] = z + hinge
    return out.reshape(-1, 3)


def grid_uvs(nx, ny):
    """Front-face UVs (u from spine to outer edge). The back face uses 1 - u in the shader."""
    u = np.linspace(0.0, 1.0, nx)
    v = np.linspace(0.0, 1.0, ny)
    uu, vv = np.meshgrid(u, v)
    return np.stack([uu.ravel(), vv.ravel()], axis=1)


def grid_faces(nx, ny):
    faces = []
    for r in range(ny - 1):
        for c in range(nx - 1):
            a = r * nx + c
            faces.append((a, a + 1, a + nx + 1, a + nx))  # counter-clockwise seen from +z
    return faces


class Timeline:
    """Frame timing.

    start hold → (cover opens → pause) → turn 1 → pause → turn 2 … → end hold
    """

    def __init__(self, turns, fps, start_hold=1.0, turn_seconds=1.6, pause=0.6, end_hold=1.0,
                 open_seconds=0.0):
        self.turns = int(turns)
        self.fps = float(fps)
        self.start = round(start_hold * fps)
        self.open = round(open_seconds * fps) if open_seconds > 0 else 0
        self.turn = max(2, round(turn_seconds * fps))
        self.pause = round(pause * fps)
        self.end = round(end_hold * fps)
        self.first_turn = self.start + (self.open + self.pause if self.open else 0)
        busy = self.turns * self.turn + max(0, self.turns - 1) * self.pause
        self.frames = max(2, self.first_turn + busy + self.end)

    def opening(self, frame):
        """Cover progress: 0 = closed, 1 = fully open. Always 1 when the book starts open."""
        if not self.open:
            return 1.0
        return float(np.clip((frame - self.start) / max(1, self.open - 1), 0.0, 1.0))

    def turn_start(self, k):
        return self.first_turn + k * (self.turn + self.pause)

    def progress(self, frame, k):
        """Turn progress (0..1) of sheet k at a frame."""
        return float(np.clip((frame - self.turn_start(k)) / (self.turn - 1), 0.0, 1.0))

    def active_turn(self, frame):
        """Index of the sheet currently moving, or None."""
        for k in range(self.turns):
            p = self.progress(frame, k)
            if 0.0 < p < 1.0:
                return k
        return None


def layout_pages(n_images):
    """Map images in reading order onto the open book.

    Image 0 is the left page of the first spread, image 1 the right page.
    Turning sheet k shows image 1 + 2k on its front (right side) and 2 + 2k on its back.
    Returns (turns, left_index, sheets[(front, back)], final_right_index); indexes may be
    None for blank paper.
    """
    def pick(i):
        return i if i < n_images else None

    turns = max(1, math.ceil(max(0, n_images - 2) / 2))
    sheets = [(pick(1 + 2 * k), pick(2 + 2 * k)) for k in range(turns)]
    return turns, pick(0), sheets, pick(1 + 2 * turns)
