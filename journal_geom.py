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
    # The open cover lies flat on the table, level with the back cover (the hinge flexes, as in
    # a real book), so the two halves of the open book are mirror images.
    return math.pi, 0.0


SPINE_GAP = T + 0.006      # open book: space between the covers' spine edges = width of the spine
THETA_OPEN, BETA = _open_angle()
J = np.array([XB, ZJ])                      # hinge of the closed cover: top of the text block
J_OPEN = np.array([XB - SPINE_GAP, TB])     # hinge of the open cover: flat on the table


def cover_pivot(theta):
    """Where the cover's hinge is at cover angle theta. It stays at the top of the text block
    while the cover rises, then drops to table level as the cover goes over, so the open cover
    lies flat beside the back cover instead of tilting down from the top of the pages."""
    f = min(1.0, max(0.0, (float(theta) / THETA_OPEN - 0.45) / 0.55))
    f = f * f * (3.0 - 2.0 * f)
    return J + (J_OPEN - J) * f


# ---- sheet stack: binding points and resting shapes --------------------------------------
LR = 0.26      # length of the gutter curve on the right
LL = 0.30      # length of the gutter curve on the left


OPEN_B = 1.0       # how far the spine has rolled open (0 = closed book, 1 = open)


def spine_hump_height():
    """Height of the spine's hump between the open covers (the bent hinge)."""
    return 0.35 * T + 0.004


def _hump_point(frac):
    """A point on the hump of the spine between the open covers (0 = front cover end, 1 = back)."""
    lp = np.array([J_OPEN[0], TB + 0.0006])
    rp = np.array([XB, TB + 0.0006])
    ch = 4.0 / 3.0 * spine_hump_height()
    c = bezier(lp, lp + np.array([0.0, ch]), rp + np.array([0.0, ch]), rp, 64)
    L = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(c, axis=0), axis=1))])
    target = float(frac) * L[-1]
    return np.array([np.interp(target, L, c[:, 0]), np.interp(target, L, c[:, 1])])


def open_seam(k, side='right'):
    """Where sheet k (0 = first sheet) is sewn on the hump of the open spine. The pages lying on
    the right are sewn down the right half of the hump, the top page nearest the crest; the pages
    lying on the left down the left half, the last one turned nearest the crest. So in each stack
    a page is sewn above the pages under it and never has to cut through them (when every seam had
    one fixed spot, the first pages were sewn below their neighbours and crossed them at the gutter).
    A turning page slides from its right-hand seam to its left-hand one (a few tenths of a mm)."""
    if side == 'right':
        return _hump_point(0.5 + 0.5 * (k + 0.5) / N_SHEETS)
    return _hump_point(0.5 * (k + 0.5) / N_SHEETS)


def binding(j):
    """Binding point (seam) of sheet j (0 = bottom, next to the back board). Closed book: a
    column at the back of the text block. As the book opens the spine rolls into the hump
    between the covers, carrying every seam to its fixed open spot."""
    closed = closed_binding(j)
    if OPEN_B <= 0.0:
        return closed
    return closed + (open_seam(N_SHEETS - 1 - j, 'right') - closed) * OPEN_B


def core_seam(j):
    """The top of the block's back between the covers, for the filler under the seams: spread
    over the whole hump (all the pages are sewn somewhere along it)."""
    closed = closed_binding(j)
    if OPEN_B <= 0.0:
        return closed
    return closed + (_hump_point((N_SHEETS - 1 - j + 0.5) / N_SHEETS) - closed) * OPEN_B


def closed_binding(j):
    zhi = TB + T - GUTTER_DIP
    # bound edges at least one sheet thickness apart (thin books: the gutter dip gives way)
    step = max((zhi - TB - 0.004) / N_SHEETS, 1.06 * SHEET_T)
    zlo = max(TB + 0.0003, zhi - N_SHEETS * step)
    step = (zhi - zlo) / N_SHEETS
    return np.array([0.0, zlo + (j + 0.5) * step])


BSTEP = (T - GUTTER_DIP - 0.004) / N_SHEETS
UP_LEFT = np.array([0.5, 0.866])     # each turned page binds just above the one turned before it


def binding_left(layer):
    """Seam of the sheet that landed on the left as `layer` (0 = first turned = sheet 0)."""
    j = N_SHEETS - 1 - layer
    closed = closed_binding(j)
    if OPEN_B <= 0.0:
        return closed
    return closed + (open_seam(layer, 'left') - closed) * OPEN_B


CURVE = 0.0        # page "pillow": 0 = flat pages; ~0.15 gentle, ~0.26 strong (radians at the spine)
OPEN_W = 1.0       # how far the pages have relaxed into their curve (0 = closed book, pages flat)
PAGE_SHAPES = {'flat': 0.0, 'curved': 0.15, 'very curved': 0.26}


def pillow(s=S):
    """Extra angle that makes a resting page rise out of the spine and come back down at the
    fore-edge (cos: + near the spine, - near the edge; its height gain over the page is ~0)."""
    return CURVE * OPEN_W * SHEET_W * np.cos(np.pi * np.asarray(s) / W)


SHEET_W = 1.0      # curve of the sheet being computed (0 = flat, 1 = full curve); see curve_weights


def curve_weights(progress):
    """How curved each sheet is, from every sheet's turn progress (0 = right, 1 = left).

    Only the two pages you can see are curved; every page under them is flat:
      * a page curves while the page before it turns away (it is being revealed) or while it
        turns itself - so the first spread, just opened, is still flat;
      * it goes flat again while the next page lands on top of it;
      * the last page goes flat as it lands, as the first page started flat (nothing is left on
        the right to make a spread with, so it lies like a page under the stack).
    w[k] = max(p[k-1], p[k]) * (1 - p[k+1]), with p[n] = p[n-1] for the last page."""
    p = [float(x) for x in progress]
    n = len(p)
    out = []
    for k in range(n):
        before = p[k - 1] if k > 0 else 0.0
        after = p[k + 1] if k + 1 < n else p[k]
        out.append(max(before, p[k]) * (1.0 - after))
    return out


def set_opening(theta):
    """Pages are pressed flat while the book is closed and relax into their curve as the cover
    lifts off them: flat at 0, fully curved once the cover is 45% open. (Checked: at every cover
    angle the curved pages stay below the cover.)"""
    global OPEN_W, OPEN_B
    f = min(1.0, max(0.0, (float(theta) / THETA_OPEN) / 0.45))
    OPEN_W = f * f * (3.0 - 2.0 * f)
    OPEN_B = _spine_roll(theta)
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
    return J_OPEN + nrm * off, d, nrm


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
    gam = bisect(lambda gm: g(gm), -2.0, 2.5)
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


def sheet_grid(j, state, layer_left=0, u=0.0, ny=NY, curve=1.0):
    """Mid-surface vertices (rows, NX, 3) of sheet j, cut to the page outline.
    state: 'right', 'left', or 'turn' (with progress u and landing layer).
    curve: how much of the page-shape curve this sheet has (see curve_weights)."""
    global SHEET_W
    saved, SHEET_W = SHEET_W, float(curve)
    try:
        return _sheet_grid(j, state, layer_left, u, ny)
    finally:
        SHEET_W = saved


def _sheet_grid(j, state, layer_left, u, ny):
    v = rows(ny)
    ny = len(v)
    p = binding(j)
    aR = right_rest_angle(j)
    if state == 'left':
        p = binding_left(layer_left)
    elif state == 'turn':
        w = float(E(u))
        q = binding_left(layer_left)
        p = (1 - w) * p + w * q
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
    b = cover_pivot(theta) + rot(theta, (0.0, TB))
    k = 4 / 3 * SPINE_BULGE * (1.0 - 0.6 * min(1.0, theta / math.pi))   # draws in as the cover opens
    closed_a, closed_b = a + np.array([-k, 0.0]), b + np.array([-k, 0.0])
    # open: the leather arches up between the two covers, under the seams (the bent hinge)
    ch = 4.0 / 3.0 * (spine_hump_height() + TB - 0.0015)
    open_a, open_b = a + np.array([0.0, ch]), b + np.array([0.0, ch])
    f = _spine_roll(theta)
    return bezier(a, closed_a + (open_a - closed_a) * f, closed_b + (open_b - closed_b) * f, b, n)


def _spine_roll(theta):
    f = min(1.0, max(0.0, (float(theta) / THETA_OPEN - 0.45) / 0.55))
    return f * f * (3.0 - 2.0 * f)


SPINE_LEN = _arclen(bezier(np.array([XB, 0.0]), np.array([XB - 4 / 3 * SPINE_BULGE, 0.0]),
                           np.array([XB - 4 / 3 * SPINE_BULGE, 2 * TB + T]), np.array([XB, 2 * TB + T])))


# ---- reconfigure for a template ------------------------------------------------------------
def cover_of(book):
    """(board width, board height) in page widths when the book has its own cover size, else None
    (then the cover follows the page: 1.08 wide, 0.17 taller)."""
    cm, page = (book or {}).get('cover_size_cm'), (book or {}).get('page_size_cm')
    try:
        return (float(cm[0]) / float(page[0]), float(cm[1]) / float(page[0])) if cm and page else None
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        return None


def min_cover(page_aspect):
    """The smallest board (width, height) in page widths: it must still cover the pages."""
    return (W - XB + 0.005, float(page_aspect) * W + 0.02)


def configure(page_count=None, page_aspect=None, pitch=None, sheet_t=None, page_shape=None, turn_style=None,
              cover=None):
    """Set the book's sheet count and page shape, and recompute everything derived from them.
    cover: (board width, board height) in page widths; None = the default cover for the page."""
    global N_SHEETS, H, PITCH, SHEET_T, T, ZJ, THETA_OPEN, BETA, J, J_OPEN, SPINE_GAP, BSTEP, HC, WC, CURVE, E, B
    global LEAD, SIG, COVER_MARGIN
    if page_shape is not None:
        CURVE = PAGE_SHAPES.get(str(page_shape), 0.0) if isinstance(page_shape, str) else float(page_shape)
    if turn_style is not None:
        st = TURN_STYLES.get(str(turn_style), TURN_STYLES['natural'])
        E, B, LEAD, SIG = st['E'], st['B'], st['LEAD'], st['SIG']
    if page_count:
        N_SHEETS = int(page_count)
    if page_aspect:
        H = float(page_aspect) * W
        WC, HC = 1.08, H + 0.17
    if cover:
        lo_w, lo_h = min_cover(H / W)
        WC, HC = max(float(cover[0]), lo_w), max(float(cover[1]), lo_h)
    # the camera keeps the cover's overhang (whichever side sticks out more) in the picture
    COVER_MARGIN = max(XB + WC - W, (HC - H) / 2) + 0.005
    if pitch:
        PITCH = float(pitch)
    if sheet_t:
        SHEET_T = float(sheet_t)
    T = N_SHEETS * PITCH
    ZJ = TB + T
    J = np.array([XB, ZJ])
    SPINE_GAP = T + 0.006
    J_OPEN = np.array([XB - SPINE_GAP, TB])
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


def sheet_state(k, t, curve=1.0):
    """(mid-surface grid) of sheet k (0 = first sheet inside the cover) at turn progress t,
    with `curve` of the page-shape curve (see curve_weights)."""
    j = N_SHEETS - 1 - k
    if t <= 0.0:
        return sheet_grid(j, 'right', ny=NY, curve=curve)
    if t >= 1.0:
        return sheet_grid(j, 'left', k, ny=NY, curve=curve)
    return sheet_grid(j, 'turn', k, float(t), ny=NY, curve=curve)


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
        global OPEN_B
        saved, OPEN_W = OPEN_W, 1.0
        saved_b, OPEN_B = OPEN_B, 1.0
        pts = []
        for u in np.linspace(0.1, 0.9, 17):
            g = sheet_grid(N_SHEETS - 1, 'turn', 0, float(u), ny=2)
            cols = sorted(set(list(range(0, g.shape[1], 6)) + [g.shape[1] - 1]))   # include the outer edge
            pts.append(g[:, cols].reshape(-1, 3))
        _TURN_PTS[key] = np.concatenate(pts)
        OPEN_W, OPEN_B = saved, saved_b
    return _TURN_PTS[key]


REF_PAGE_CM = (15.0, 21.48)     # the shipped Leather Journal's page: the camera frames this size


def real_size(book):
    """How big this book's page is compared with the Leather Journal's (by width), or None when
    the book has no real size set. A smaller book then looks smaller in the picture."""
    cm = (book or {}).get('page_size_cm')
    try:
        return float(cm[0]) / REF_PAGE_CM[0] if cm else None
    except (TypeError, ValueError, IndexError):
        return None


def camera(cam_settings, frac, aspect, real=None):
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
    if real:
        # Real size: frame the Leather Journal's size (and shape) instead of this book, so a smaller
        # book looks smaller. A bigger book is still kept whole in the picture.
        ref_h = REF_PAGE_CM[1] / REF_PAGE_CM[0]
        k = np.array([1.0, ref_h / H, 1.0]) / float(real)
        dist = max(dist, cf.fit_distance(base + (pts - base) * k, tilt, turn, roll, lens, aspect, base, fill=0.86))
    # Zoom like a real camera lens: the camera stays where it is and the lens gets longer, so zooming
    # in does not bend the book (moving the camera closer made a near book look stretched).
    lens = lens * zoom
    target = base + np.array([c.get('shift_x', 0.0) * (W + COVER_MARGIN),
                              c.get('shift_y', 0.0) * (H / 2 + COVER_MARGIN), 0.0])
    cam, r, u, f = cf.pose(tilt, turn, roll, dist, target)
    return cam, r, u, f, lens
