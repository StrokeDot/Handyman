"""Book proportions and layout, shared by the Blender scene and the app's live 3D view.

Pure numpy, so both draw exactly the same book.
"""
import math

import numpy as np

from page_curl import GUTTER, gutter_rise, ease

PAGE_W = 1.0
COVER_MARGIN = 0.05
COVER_T = 0.03
BLOCK_H = 0.11            # all the paper together
SHEET_GAP = 0.0012
MIN_STACK = 0.004

# Where the book is opened. A real journal opened from its cover has almost all pages on the right.
OPEN_AT = {'Beginning (only the cover opens)': 0.04, 'A quarter in': 0.25, 'Middle': 0.5}


class Layout:
    def __init__(self, page_aspect=1.4, turns=1, open_at=0.04):
        self.page_w = PAGE_W
        self.page_h = PAGE_W * float(page_aspect)
        self.turns = int(turns)
        open_at = float(min(0.96, max(0.0, open_at)))
        self.h_left = max(MIN_STACK, BLOCK_H * open_at)
        self.h_right = max(MIN_STACK, BLOCK_H - self.h_left)
        self._finish()

    def _finish(self):
        """Derived stack geometry, from page_w/page_h/turns and h_left/h_right."""
        full_rise = gutter_rise(PAGE_W, GUTTER)
        # A thin stack can only curve as far as it is thick.
        self.gutter_left = GUTTER * min(1.0, 0.7 * self.h_left / full_rise)
        self.gutter_right = GUTTER * min(1.0, 0.7 * self.h_right / full_rise)
        self.rise_left = gutter_rise(PAGE_W, self.gutter_left)
        self.rise_right = gutter_rise(PAGE_W, self.gutter_right)
        # Flat page level of each stack, and the spine heights pages hinge from.
        self.top_left = COVER_T + self.h_left
        self.top_right = COVER_T + self.h_right
        self.base_left = self.top_left - self.rise_left
        self.base_right = self.top_right - self.rise_right
        self.hinge = self._hinge()
        self.cover_w = PAGE_W + COVER_MARGIN
        self.cover_h = self.page_h + 2 * COVER_MARGIN
        self.book_w = 2 * self.cover_w

    def _hinge(self):
        # The front cover swings around this height so that, closed, it lands on top of everything.
        return (self.top_left + self.top_right + (self.turns + 1) * SHEET_GAP) / 2 + 0.0008

    @property
    def gutter(self):
        return (self.gutter_right, self.gutter_left)

    def sheet_levels(self, k):
        """Spine heights (right, left) of the k-th turning sheet."""
        return (self.base_right + (self.turns - k) * SHEET_GAP,
                self.base_left + (k + 1) * SHEET_GAP)

    def opening(self, o, slide=True):
        """Front-cover angle (radians around +y at the hinge) and sideways slide for cover progress o."""
        e = float(ease(o))
        return math.pi * (1.0 - e), (-(self.cover_w / 2) * (1.0 - e) if slide else 0.0)

    def camera_top(self):
        return max(self.top_left, self.top_right)


class SheetLayout(Layout):
    """Real pages (step 2): a book of `page_count` real sheets, open with `left_count` on the left.

    Every sheet has a front and a back. `turns` sheets turn during the animation, moving
    from the right stack to the left stack. `Layout` above is the older fixed-block book and
    is kept unchanged for comparison while the renderers migrate to this model.
    """

    def __init__(self, page_aspect=1.4, page_count=50, left_count=1, turns=1):
        self.page_w = PAGE_W
        self.page_h = PAGE_W * float(page_aspect)
        self.page_count = int(page_count)
        if self.page_count < 2:
            raise ValueError('page_count must be at least 2 (a left and a right page)')
        self.left_count = int(min(max(left_count, 1), self.page_count - 1))
        self.right_count = self.page_count - self.left_count
        self.turns = int(min(max(turns, 0), self.right_count))
        # Height of the resting stacks (sheets that never turn); the turning sheets ride on top.
        self.h_left = self.left_count * SHEET_GAP
        self.h_right = (self.right_count - self.turns) * SHEET_GAP
        self._finish()

    def _hinge(self):
        # Closed, all page_count sheets and both covers stack up; the hinge is at half the paper.
        return COVER_T + self.page_count * SHEET_GAP / 2 + 0.0008

    @property
    def left_rest_count(self):
        return self.left_count

    @property
    def right_rest_count(self):
        return self.right_count - self.turns

    def turn_levels(self, t):
        """Spine heights (right, left) of the t-th turning sheet (0-based), above the resting stacks."""
        return (self.base_right + (self.turns - t) * SHEET_GAP,
                self.base_left + (t + 1) * SHEET_GAP)


def spine_shapes(layout, bands=4, nu=9, nv=60):
    """(open, closed) vertex grids of the leather spine, plus quad faces."""
    hy = layout.cover_h / 2
    u = np.linspace(0, 1, nu)
    yv = np.linspace(-hy, hy, nv)
    bump = np.zeros(nv)
    for i in range(bands):
        c = -hy * 0.7 + (1.4 * hy) * (i + 0.5) / max(1, bands)
        bump += 0.007 * np.exp(-((yv - c) / 0.025) ** 2)
    height = 2 * layout.hinge
    open_pts, closed_pts = [], []
    for j in range(nv):
        for i in range(nu):
            bulge = math.sin(math.pi * u[i])
            open_pts.append(((u[i] - 0.5) * 0.12, yv[j], -0.004 - 0.01 * bulge - bump[j]))
            closed_pts.append((-0.03 * bulge - bump[j], yv[j], u[i] * height))
    faces = [(j * nu + i, j * nu + i + 1, (j + 1) * nu + i + 1, (j + 1) * nu + i)
             for j in range(nv - 1) for i in range(nu - 1)]
    return np.array(open_pts), np.array(closed_pts), faces


def block_prism(layout, side, nx=24):
    """Paper block of one half: vertices and faces (outward). side = +1 right, -1 left."""
    from page_curl import rest_profile
    gutter = layout.gutter_right if side > 0 else layout.gutter_left
    base = layout.base_right if side > 0 else layout.base_left
    px, pz = rest_profile(layout.page_w - 0.004, nx, gutter)
    px = side * (px + 0.002)
    thick = layout.h_right if side > 0 else layout.h_left
    z_spine = base - min(0.002, 0.2 * thick)     # just under the resting page, never under the cover
    y0, y1 = -layout.page_h / 2 + 0.004, layout.page_h / 2 - 0.004
    n = len(px)
    verts = []
    for y in (y0, y1):
        verts += [(px[i], y, z_spine + pz[i]) for i in range(n)]
        verts += [(px[-1], y, COVER_T), (px[0], y, COVER_T)]
    m = n + 2
    faces = [(i, i + 1, m + i + 1, m + i) for i in range(n - 1)]
    faces += [(n - 1, n, m + n, m + n - 1), (n, n + 1, m + n + 1, m + n), (n + 1, 0, m, m + n + 1),
              tuple(range(m - 1, -1, -1)), tuple(range(m, 2 * m))]
    if side < 0:
        faces = [tuple(reversed(f)) for f in faces]
    return np.array(verts), faces


def sheet_slice(layout, side, j, count, nx=24):
    """One real resting sheet: the j-th (0 = top) of `count` sheets on one half.

    A wedge slice of the stack: its top and bottom are scaled versions of the resting-page
    curve, nested between the cover and the visible top page. side = +1 right, -1 left.
    Returns (vertices, faces) with outward faces, like block_prism.
    """
    from page_curl import rest_profile
    gutter = layout.gutter_right if side > 0 else layout.gutter_left
    base = layout.base_right if side > 0 else layout.base_left
    px, pz = rest_profile(layout.page_w - 0.004, nx, gutter)
    px = side * (px + 0.002)
    pz = np.asarray(pz, dtype=float)
    f_top = (count - j) / count
    f_bot = (count - j - 1) / count
    z_top = COVER_T + f_top * (base + pz - COVER_T)
    z_bot = COVER_T + f_bot * (base + pz - COVER_T)
    y0, y1 = -layout.page_h / 2 + 0.004, layout.page_h / 2 - 0.004
    n = len(px)
    verts = []
    for y in (y0, y1):
        verts += [(px[i], y, z_top[i]) for i in range(n)]
        verts += [(px[i], y, z_bot[i]) for i in range(n)]
    # Index layout: y0 top 0..n-1, y0 bottom n..2n-1, y1 top 2n..3n-1, y1 bottom 3n..4n-1.
    faces = []
    faces += [(i, i + 1, 2 * n + i + 1, 2 * n + i) for i in range(n - 1)]          # top surface
    faces += [(n + i, 3 * n + i, 3 * n + i + 1, n + i + 1) for i in range(n - 1)]  # bottom surface
    faces += [(n - 1, 2 * n - 1, 4 * n - 1, 3 * n - 1)]                            # fore edge
    faces += [(n, 0, 2 * n, 3 * n)]                                                # spine edge
    faces += [tuple(range(2 * n - 1, -1, -1)), tuple(range(2 * n, 4 * n))]         # y0 and y1 ends
    if side < 0:
        faces = [tuple(reversed(f)) for f in faces]
    return np.array(verts), faces


def closed_to_open(layout, x, y, z):
    """A point placed on the closed book's front cover, in the front cover's open-layout coordinates."""
    return (-x, y, 2 * layout.hinge - z)
