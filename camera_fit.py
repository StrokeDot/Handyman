"""Camera placement shared by the Blender scene and the app's live framing preview.

Pure numpy. The camera looks at the book from any tilt / turn / roll, and its distance is
found automatically so the whole book (including a page rising mid-turn) fits in frame.
"""
import math
import numpy as np

from page_curl import sheet_vertices

SENSOR = 36.0  # mm, Blender's default sensor width (horizontal for landscape frames)

PRESETS = {
    'Eye level (reading at a desk)': dict(tilt=50, turn=0, roll=-3, lens=35),
    'Top-down (like a game journal)': dict(tilt=89, turn=0, roll=0, lens=50),
    'Angled': dict(tilt=60, turn=0, roll=0, lens=50),
    'Low angle': dict(tilt=32, turn=0, roll=0, lens=35),
}
MOVES = {'Still': 'none', 'Slow push-in': 'push', 'Slow pull-out': 'pull', 'Slow drift sideways': 'drift'}


BOOK_CORNERS = 8  # the first 8 book_points are the book itself; the rest are a rising page


def book_points(page_w, page_h, margin, top):
    """Points the camera keeps in view: the open book's 8 corners, then a page rising mid-turn."""
    hx, hy = page_w + margin, page_h / 2 + margin
    pts = [(x, y, z) for x in (-hx, hx) for y in (-hy, hy) for z in (0.0, top)]
    for p in (0.45, 0.6, 0.75):
        pts.extend(sheet_vertices(p, page_w, page_h, 9, 5, top, top).tolist())
    return np.array(pts, dtype=float)


def pose(tilt, turn, roll, dist, target):
    """Camera position and axes (right, up, forward) for the given angles in degrees.

    Tilt is the elevation: negative looks up from below the book, positive looks down. It is
    clamped just short of the poles so the up-vector stays well defined; everything in between
    (including directly behind and underneath) is reachable.
    """
    el = math.radians(max(-89.5, min(tilt, 89.5)))
    az, rl = math.radians(turn), math.radians(roll)
    target = np.asarray(target, dtype=float)
    offset = np.array([math.cos(el) * math.sin(az), -math.cos(el) * math.cos(az), math.sin(el)])
    cam = target + dist * offset
    f = target - cam
    f /= np.linalg.norm(f)
    r = np.cross(f, [0.0, 0.0, 1.0])
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    r, u = r * math.cos(rl) + u * math.sin(rl), -r * math.sin(rl) + u * math.cos(rl)
    return cam, r, u, f


def project(points, cam, r, u, f, lens, aspect):
    """Normalised screen coordinates: -1..1 across the frame width and height."""
    d = points - cam
    depth = d @ f
    th = SENSOR / 2 / lens
    tv = th / aspect
    return (d @ r) / depth / th, (d @ u) / depth / tv, depth


def fit_distance(points, tilt, turn, roll, lens, aspect, target, fill=0.9):
    """Smallest distance at which every point sits inside `fill` of the frame."""
    lo, hi = 0.3, 200.0
    for _ in range(60):
        mid = (lo + hi) / 2
        cam, r, u, f = pose(tilt, turn, roll, mid, target)
        x, y, depth = project(points, cam, r, u, f, lens, aspect)
        ok = depth.min() > 0.05 and np.abs(x).max() <= fill and np.abs(y).max() <= fill
        if ok:
            hi = mid
        else:
            lo = mid
    return hi


def shot(cam_settings, frac, base_target, book_w, book_h, points, aspect):
    """Camera at a point of the video (frac 0..1), including the chosen slow move.

    Returns (position, right, up, forward, lens).
    """
    c = cam_settings
    tilt, turn, roll, lens, zoom = c['tilt'], c['turn'], c['roll'], c['lens'], c['zoom']
    a = frac * frac * (3 - 2 * frac)
    move = c.get('move', 'none')
    if move == 'push':
        zoom *= 1.0 + 0.15 * a
    elif move == 'pull':
        zoom *= 1.15 - 0.15 * a
    elif move == 'drift':
        turn += -5.0 + 10.0 * a
    # The book fills most of the frame; the tip of a rising page may briefly pass the top edge.
    dist = max(fit_distance(points[:BOOK_CORNERS], tilt, turn, roll, lens, aspect, base_target, fill=0.9),
               fit_distance(points, tilt, turn, roll, lens, aspect, base_target, fill=1.25)) / zoom
    target = np.asarray(base_target, dtype=float) + np.array([c.get('shift_x', 0.0) * book_w / 2,
                                                              c.get('shift_y', 0.0) * book_h / 2, 0.0])
    cam, r, u, f = pose(tilt, turn, roll, dist, target)
    return cam, r, u, f, lens


def matrix_rows(cam, r, u, f):
    """4×4 world matrix for a Blender camera (it looks down its -Z, up is +Y)."""
    return [[r[i], u[i], -f[i], cam[i]] for i in range(3)] + [[0.0, 0.0, 0.0, 1.0]]
