"""Journal engine: book geometry and motion. Pure numpy (no Blender, no Qt), so the Blender
render and the live view can draw from the same shapes.

Call configure(page_count, page_aspect) before use (defaults: the 20-page journal).

Book space: x across (spine near x = 0, right-hand pages at x > 0), y up the page
(head at +y), z up from the table (table at z = 0).

Every sheet is inextensible: each row of a sheet is a planar curve in (x, z) defined by
its tangent angle a(s) along the arc length s from the binding, so paper never stretches.
"""
import math
import numpy as np

# ---- dimensions ------------------------------------------------------------------------
W = 1.0                    # page width (binding to fore-edge)
H = 1.4318                 # page height (parchment aspect 1406 / 982)
N_SHEETS = 10             # 20 pages: a slim journal
PITCH = 0.0030             # spacing of sheets in the stack (~0.45 mm on a 15 cm page)
SHEET_T = 0.0024           # physical sheet thickness (the gap between sheets reads as page lines)
T = N_SHEETS * PITCH       # text block thickness
TB = 0.028                 # board thickness
XB = -0.03                 # spine edge of the boards (the joint sits a little outside the text block)
WC = 1.08                  # board width
HC = 1.60                  # board height
ZJ = TB + T                # front-board hinge height (inner face of the closed front board)
GUTTER_DIP = 0.006         # how far the top page dips into the gutter
SPINE_BULGE = 0.03
RC = 0.035                 # fore-edge corner radius of every sheet (measured from the parchment art)

NX, NY = 64, 24            # grid of a turning sheet (NY = rows between the corner bands)
NX_REST, NY_REST = 40, 2   # grid of a sheet that never moves


def pchip(xk, yk):
    """Monotone cubic interpolation through keyframes (no overshoot), returns f(x)."""
    xk = np.asarray(xk, float)
    yk = np.asarray(yk, float)
    h = np.diff(xk)
    d = np.diff(yk) / h
    m = np.zeros_like(yk)
    for i in range(1, len(xk) - 1):
        if d[i - 1] * d[i] > 0:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    m[0], m[-1] = d[0], d[-1]
    if d[0] * m[0] <= 0:
        m[0] = 0.0
    if d[-1] * m[-1] <= 0:
        m[-1] = 0.0

    def f(x):
        x = np.clip(np.asarray(x, float), xk[0], xk[-1])
        i = np.clip(np.searchsorted(xk, x, side='right') - 1, 0, len(xk) - 2)
        t = (x - xk[i]) / h[i]
        h00 = (1 + 2 * t) * (1 - t) ** 2
        h10 = t * (1 - t) ** 2
        h01 = t * t * (3 - 2 * t)
        h11 = t * t * (t - 1)
        return h00 * yk[i] + h10 * h[i] * m[i] + h01 * yk[i + 1] + h11 * h[i] * m[i + 1]
    return f


# ---- curves from angle functions --------------------------------------------------------
S = np.linspace(0.0, W, NX)


def integrate(a, s=S, p0=(0.0, 0.0)):
    """Positions along a curve with tangent angle a(s) (trapezoid rule)."""
    ds = np.diff(s)
    c, n = np.cos(a), np.sin(a)
    x = np.concatenate([[0.0], np.cumsum((c[1:] + c[:-1]) * 0.5 * ds)])
    z = np.concatenate([[0.0], np.cumsum((n[1:] + n[:-1]) * 0.5 * ds)])
    return x + p0[0], z + p0[1]


def profile(s, L, p=2.0):
    return np.clip(1.0 - s / L, 0.0, 1.0) ** p


def bisect(f, lo, hi, it=60):
    flo = f(lo)
    for _ in range(it):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ---- the front board when open ----------------------------------------------------------
def rot(theta, v):
    c, s = math.cos(theta), math.sin(theta)
    return np.array([v[0] * c - v[1] * s, v[0] * s + v[1] * c])


def _open_angle():
    # the open board rests on the table: its far outer corner touches z = 0
    def f(beta):
        corner = np.array([XB, ZJ]) + rot(math.pi + beta, (WC, TB))
        return corner[1]
    beta = bisect(f, 0.0, 0.6)
    return math.pi + beta, beta


THETA_OPEN, BETA = _open_angle()
J = np.array([XB, ZJ])


# ---- sheet stack: binding points and resting shapes --------------------------------------
LR = 0.26      # length of the gutter curve on the right
LL = 0.30      # length of the gutter curve on the left


def binding(j):
    """Binding point of sheet j (0 = bottom, next to the back board)."""
    zhi = TB + T - GUTTER_DIP
    # bound edges at least one sheet thickness apart (thin books: the gutter dip gives way)
    step = max((zhi - TB - 0.004) / N_SHEETS, 1.06 * SHEET_T)
    zlo = max(TB + 0.0003, zhi - N_SHEETS * step)
    step = (zhi - zlo) / N_SHEETS
    return np.array([0.0, zlo + (j + 0.5) * step])


BSTEP = (T - GUTTER_DIP - 0.004) / N_SHEETS
UP_LEFT = np.array([0.5, 0.866])     # each turned page binds just above the one turned before it


def binding_left(layer):
    """Binding point of the sheet that landed on the left as `layer` (0 = first turned).
    The bound edge rolls as pages turn, so later pages bind above earlier ones and the left
    stack never crosses itself in the gutter."""
    # The first turned page binds just above the open cover's hinge, so its gutter curve never
    # dips under the cover; each later page binds one sheet higher along UP_LEFT.
    q, d, _ = left_line(0)
    base = q + d * ((0.0 - q[0]) / d[0]) + np.array([0.0, 0.0003])   # first page's support line, at the spine
    return base + layer * (1.05 * PITCH / UP_LEFT[1]) * UP_LEFT


CURVE = 0.0        # page "pillow": 0 = flat pages; ~0.15 gentle, ~0.26 strong (radians at the spine)
OPEN_W = 1.0       # how far the pages have relaxed into their curve (0 = closed book, pages flat)
PAGE_SHAPES = {'flat': 0.0, 'curved': 0.15, 'very curved': 0.26}


def pillow(s=S):
    """Extra angle that makes a resting page rise out of the spine and come back down at the
    fore-edge (cos: + near the spine, - near the edge; its height gain over the page is ~0)."""
    return CURVE * OPEN_W * np.cos(np.pi * np.asarray(s) / W)


def set_opening(theta):
    """Pages are pressed flat while the book is closed and relax into their curve as the cover
    lifts off them: flat at 0, fully curved once the cover is 45% open. (Checked: at every cover
    angle the curved pages stay below the cover.)"""
    global OPEN_W
    f = min(1.0, max(0.0, (float(theta) / THETA_OPEN) / 0.45))
    OPEN_W = f * f * (3.0 - 2.0 * f)
    return OPEN_W


def flat_right(j):
    return TB + (j + 0.5) * PITCH


def right_rest_angle(j, s=S):
    """Tangent angle along a resting right-hand sheet: rises out of the gutter, then flat."""
    p = binding(j)
    rise = flat_right(j) - p[1]
    arch = pillow(s)
    g = lambda d: integrate(d * profile(s, LR) + arch, s)[1][-1] - rise
    d = bisect(g, -0.5, 1.2)
    return d * profile(s, LR) + arch


def left_line(layer):
    """Support line for a sheet landed on the left: (point, direction, normal)."""
    d = rot(THETA_OPEN, (1.0, 0.0))            # along the open board, away from the spine
    nrm = rot(THETA_OPEN, (0.0, -1.0))          # inner-face normal (points up, away from board)
    off = (layer + 0.5) * PITCH + 0.0012
    return J + nrm * off, d, nrm


def left_rest_angle(j, layer, s=S):
    p = binding_left(layer)
    q, d, nrm = left_line(layer)
    final = math.atan2(d[1], d[0]) % (2 * math.pi)

    arch = pillow(s)
    k0 = int(np.searchsorted(s, LL))

    def g(gam):
        a = final - gam * profile(s, LL) - arch
        x, z = integrate(a, s, p)
        pts = np.stack([x[k0:], z[k0:]], axis=1)
        # lowest point of the page beyond the gutter curve sits exactly on its support (a flat
        # page: everywhere beyond LL; a curved page: its fore-edge, the arch floats above)
        return float(np.min((pts - q) @ nrm))
    gam = bisect(lambda gm: g(gm), -0.6, 2.5)
    return final - gam * profile(s, LL) - arch


# ---- the turn -----------------------------------------------------------------------------
# root: how far the sheet has rotated from its right-hand shape to its left-hand shape
E = pchip([0.0, 0.14, 0.24, 0.50, 0.74, 0.88, 1.0],
          [0.0, 0.0, 0.05, 0.50, 0.93, 1.0, 1.0])
# bend: extra angle at the outer edge; + = outer edge leads (lift), - = trails (air drag, landing)
B = pchip([0.0, 0.07, 0.17, 0.30, 0.42, 0.52, 0.62, 0.72, 0.84, 0.94, 1.0],
          [0.0, 0.30, 0.95, 1.00, 0.90, 0.50, 0.0, -0.42, -0.36, -0.07, 0.0])
LEAD = 0.16        # how far the top outer corner trails the bottom outer corner
SIG = 1.4          # how much the bend is concentrated at the outer edge (higher = only the edge)

TURN_STYLES = {
    # the original: the page lifts and swings over in one smooth arc
    'natural': dict(E=E, B=B, LEAD=0.16, SIG=1.4),
    # like a hand-made After Effects turn: the bottom corner peels up slowly, the page whips over
    # quickly, then lands with its corner still curled and relaxes
    'corner peel': dict(
        E=pchip([0.0, 0.40, 0.52, 0.58, 0.64, 0.71, 0.80, 1.0],
                [0.0, 0.02, 0.10, 0.30, 0.62, 0.92, 1.0, 1.0]),
        B=pchip([0.0, 0.15, 0.32, 0.48, 0.56, 0.64, 0.72, 0.84, 0.94, 1.0],
                [0.0, 0.45, 1.05, 1.45, 1.10, 0.10, -0.50, -0.28, -0.06, 0.0]),
        LEAD=0.45, SIG=2.6),
    # quick and light: little lift, almost no bend - for fast flips through many pages
    'quick': dict(
        E=pchip([0.0, 0.08, 0.50, 0.90, 1.0], [0.0, 0.03, 0.50, 0.98, 1.0]),
        B=pchip([0.0, 0.15, 0.40, 0.65, 0.85, 1.0], [0.0, 0.35, 0.40, -0.25, -0.08, 0.0]),
        LEAD=0.10, SIG=1.6),
}


def turning_angles(aR, aL, u, v):
    """Angle function for each row v (0 = bottom edge .. 1 = top edge) at turn progress u.

    Every point runs on its own clock: the binding edge (s = 0) and the whole bottom edge run
    on the sheet's clock, while points further out towards the top edge run a little behind,
    so the bottom outer corner (where the hand grabs) leads and the top outer corner trails.
    The binding never twists, and every point reaches the rest shape at u = 1."""
    sig = (S / W) ** SIG
    rows = []
    for vv in v:
        lag = LEAD * vv * (S / W) ** 0.8
        ue = np.clip((u - lag) / (1.0 - lag), 0.0, 1.0)
        e = E(ue)
        rows.append((1 - e) * aR + e * aL + B(ue) * sig)
    return np.array(rows)


def rows(n_mid):
    """Row positions v (0 = bottom edge .. 1 = top edge): dense bands at the head and tail so
    the rounded fore-edge corners are cut cleanly, n_mid rows in between."""
    phi = np.linspace(0.0, math.pi / 2, 7)
    d = RC * (1.0 - np.cos(phi)) / H
    mid = np.linspace(RC / H, 1.0 - RC / H, n_mid + 2)[1:-1]
    return np.concatenate([d, mid, (1.0 - d)[::-1]])


def smax(v):
    """Width of the sheet along row v: the fore-edge corners are rounded with radius RC."""
    d = min(v, 1.0 - v) * H
    if d >= RC:
        return W
    return W - RC + math.sqrt(max(0.0, RC * RC - (RC - d) ** 2))


def sheet_grid(j, state, layer_left=0, u=0.0, ny=NY):
    """Mid-surface vertices (rows, NX, 3) of sheet j, cut to the page outline.
    state: 'right', 'left', or 'turn' (with progress u and landing layer)."""
    v = rows(ny)
    ny = len(v)
    p = binding(j)
    aR = right_rest_angle(j)
    if state == 'left':
        p = binding_left(layer_left)
    elif state == 'turn':
        w = float(E(u))
        q = binding_left(layer_left)
        p = (1 - w) * p + w * q + np.array([1.2 * BSTEP * math.sin(math.pi * w), 0.0])
    if state == 'right':
        A = np.repeat(aR[None, :], ny, 0)
    else:
        aL = left_rest_angle(j, layer_left)
        if state == 'left':
            A = np.repeat(aL[None, :], ny, 0)
        else:
            A = turning_angles(aR, aL, u, v)
    out = np.zeros((ny, NX, 3))
    for i in range(ny):
        x, z = integrate(A[i], S, p)
        s2 = S * smax(v[i]) / W                  # same paper, trimmed at the rounded corners
        out[i, :, 0] = np.interp(s2, S, x)
        out[i, :, 2] = np.interp(s2, S, z)
        out[i, :, 1] = -H / 2 + v[i] * H
    return out


# ---- spine leather ----------------------------------------------------------------------
def bezier(p0, p1, p2, p3, n=40):
    t = np.linspace(0, 1, n)[:, None]
    return ((1 - t) ** 3) * p0 + 3 * ((1 - t) ** 2) * t * p1 + 3 * (1 - t) * t * t * p2 + t ** 3 * p3


def _arclen(c):
    return float(np.sum(np.linalg.norm(np.diff(c, axis=0), axis=1)))


def spine_curve(theta, n=40):
    """Outer surface of the spine leather from the back board to the front board.
    The back stays rounded (hollow back); opening the cover creases the leather at the joint."""
    a = np.array([XB, 0.0])
    b = J + rot(theta, (0.0, TB))
    k = 4 / 3 * SPINE_BULGE * (1.0 - 0.6 * min(1.0, theta / math.pi))   # draws in as the cover opens
    return bezier(a, a + np.array([-k, 0.0]), b + np.array([-k, 0.0]), b, n)


SPINE_LEN = _arclen(bezier(np.array([XB, 0.0]), np.array([XB - 4 / 3 * SPINE_BULGE, 0.0]),
                           np.array([XB - 4 / 3 * SPINE_BULGE, 2 * TB + T]), np.array([XB, 2 * TB + T])))


# ---- reconfigure for a template ------------------------------------------------------------
def configure(page_count=None, page_aspect=None, pitch=None, sheet_t=None, page_shape=None, turn_style=None):
    """Set the book's sheet count and page shape, and recompute everything derived from them."""
    global N_SHEETS, H, PITCH, SHEET_T, T, ZJ, THETA_OPEN, BETA, J, BSTEP, HC, CURVE, E, B, LEAD, SIG
    if page_shape is not None:
        CURVE = PAGE_SHAPES.get(str(page_shape), 0.0) if isinstance(page_shape, str) else float(page_shape)
    if turn_style is not None:
        st = TURN_STYLES.get(str(turn_style), TURN_STYLES['natural'])
        E, B, LEAD, SIG = st['E'], st['B'], st['LEAD'], st['SIG']
    if page_count:
        N_SHEETS = int(page_count)
    if page_aspect:
        H = float(page_aspect) * W
        HC = H + 0.17
    if pitch:
        PITCH = float(pitch)
    if sheet_t:
        SHEET_T = float(sheet_t)
    T = N_SHEETS * PITCH
    ZJ = TB + T
    J = np.array([XB, ZJ])
    THETA_OPEN, BETA = _open_angle()
    BSTEP = (T - GUTTER_DIP - 0.004) / N_SHEETS


# ---- shared by the Blender render and the live preview -----------------------------------
COVER_MARGIN = 0.09        # cover overhang the camera keeps in frame (around the pages)


def solid_from_grid(mid, thick=None):
    """Top/bottom vertices (2 * rows * cols, 3) of a solid sheet from its mid-surface grid."""
    thick = SHEET_T if thick is None else thick
    dx = np.gradient(mid, axis=1)
    dy = np.gradient(mid, axis=0)
    nrm = np.cross(dx, dy)
    nrm /= np.linalg.norm(nrm, axis=2, keepdims=True) + 1e-12
    top = mid + nrm * thick / 2
    bot = mid - nrm * thick / 2
    return np.concatenate([top.reshape(-1, 3), bot.reshape(-1, 3)])


def sheet_uvs(n_mid, nx=None):
    """UVs (rows * cols, 2) of the front face; the picture is trimmed where the paper is."""
    nx = NX if nx is None else nx
    vv = rows(n_mid)
    return np.array([(k / (nx - 1) * smax(v) / W, v) for v in vv for k in range(nx)], dtype=float)


def sheet_state(k, t):
    """(mid-surface grid) of sheet k (0 = first sheet inside the cover) at turn progress t."""
    j = N_SHEETS - 1 - k
    if t <= 0.0:
        return sheet_grid(j, 'right', ny=NY)
    if t >= 1.0:
        return sheet_grid(j, 'left', k, ny=NY)
    return sheet_grid(j, 'turn', k, float(t), ny=NY)


THETA_EASE = pchip([0.0, 0.25, 0.55, 0.80, 0.92, 1.0], [0.0, 0.10, 0.47, 0.88, 0.985, 1.0])


def cover_angle(opening):
    """Hinge angle of the front cover for opening progress 0..1."""
    return float(THETA_EASE(opening)) * THETA_OPEN


_TURN_PTS = {}


def turn_points():
    """Points of a page mid-turn (the real journal motion), for framing: the camera keeps the
    whole standing page in the picture, not just the flat book."""
    global OPEN_W
    key = (N_SHEETS, H, PITCH, CURVE, LEAD, SIG)
    if key not in _TURN_PTS:
        saved, OPEN_W = OPEN_W, 1.0
        pts = []
        for u in np.linspace(0.1, 0.9, 17):
            g = sheet_grid(N_SHEETS - 1, 'turn', 0, float(u), ny=2)
            cols = sorted(set(list(range(0, g.shape[1], 6)) + [g.shape[1] - 1]))   # include the outer edge
            pts.append(g[:, cols].reshape(-1, 3))
        _TURN_PTS[key] = np.concatenate(pts)
        OPEN_W = saved
    return _TURN_PTS[key]


def camera(cam_settings, frac, aspect):
    """The app's camera settings applied to this book: (position, right, up, forward, lens).
    Same controls as the classic book (presets, zoom, shift, slow moves). The framing keeps the
    open book AND the page standing up mid-turn inside the picture, aiming a little above the
    book so the rising page has room."""
    import camera_fit as cf
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
    top = ZJ
    corners = cf.book_points(W, H, COVER_MARGIN, top)[:cf.BOOK_CORNERS]
    pts = np.concatenate([corners, turn_points()])
    # Centre the open book and the standing page together in the picture, then fit them with a
    # margin all round: no cut-off page tip, no wasted empty band under the book.
    base = np.array([0.0, 0.0, top])
    th = cf.SENSOR / 2 / lens
    tv = th / aspect
    for _ in range(5):
        dist = cf.fit_distance(pts, tilt, turn, roll, lens, aspect, base, fill=0.86)
        cam, r, u, f = cf.pose(tilt, turn, roll, dist, base)
        x, y, _d = cf.project(pts, cam, r, u, f, lens, aspect)
        xs, ys = (x.max() + x.min()) / 2, (y.max() + y.min()) / 2
        base = base + (r * xs * th + u * ys * tv) * dist
    dist /= zoom
    target = base + np.array([c.get('shift_x', 0.0) * (W + COVER_MARGIN),
                              c.get('shift_y', 0.0) * (H / 2 + COVER_MARGIN), 0.0])
    cam, r, u, f = cf.pose(tilt, turn, roll, dist, target)
    return cam, r, u, f, lens
