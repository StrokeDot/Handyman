"""The open spread's 4 corners per frame: pale pages against the grass, each edge a robust line fit.
    bookquad.py clip.mp4 out.npz"""
import sys, subprocess, numpy as np, cv2
video, out = sys.argv[1], sys.argv[2]
W, H, FPS = 1280, 720, 30
rng = np.random.default_rng(1)
LAST = None
def ransac(u, v, iters=200, tol=2.5):
    """v = a*u + b, robust."""
    best = None
    n = len(u)
    if n < 10: return None
    for _ in range(iters):
        i, j = rng.choice(n, 2, replace=False)
        if u[i] == u[j]: continue
        a = (v[j] - v[i]) / (u[j] - u[i]); b = v[i] - a * u[i]
        inl = np.abs(v - (a * u + b)) < tol
        if best is None or inl.sum() > best[0]: best = (inl.sum(), inl)
    inl = best[1]
    a, b = np.polyfit(u[inl], v[inl], 1)
    return a, b, inl.mean()
def mask(im):
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 1] < 34) & (hsv[..., 2] > 80)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
GRAY = None
def quad(m):
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    if n < 2: return None
    big = st[1:, cv2.CC_STAT_AREA].max()
    keep = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] > 0.25 * big]   # (both pages: the gutter splits them)
    both = np.isin(lab, keep).astype(np.uint8)
    both = cv2.morphologyEx(both, cv2.MORPH_CLOSE, np.ones((1, 31), np.uint8))   # (bridge the gutter)
    cs, _ = cv2.findContours(both, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cs = [max(cs, key=cv2.contourArea)]
    filled = np.zeros((H, W), np.uint8)
    cv2.drawContours(filled, cs, -1, 1, -1)                   # (writing and smudges on the pages: filled)
    m = filled.astype(bool)
    x0, y0, w, h = cv2.boundingRect(cs[0])
    rows = np.arange(y0 + int(0.2 * h), y0 + int(0.8 * h))
    cols = np.arange(x0 + int(0.15 * w), x0 + int(0.85 * w))
    has_r = m[rows].any(1); has_c = m[:, cols].any(0)
    rows, cols = rows[has_r], cols[has_c]
    # each edge: from the middle of the book outwards, the first pixel that is not page
    cx, cy = x0 + w // 2, y0 + h // 2
    left = cx - (~m[rows, :cx][:, ::-1]).argmax(1)
    right = cx + (~m[rows, cx:]).argmax(1) - 1
    top = cy - (~m[:cy, cols][::-1]).argmax(0)
    bot = cy + (~m[cy:, cols]).argmax(0) - 1
    def edge(u, v, ok):
        return ransac(u[ok].astype(float), v[ok].astype(float))
    hasL = ~m[rows, :cx].all(1); hasR = ~m[rows, cx:].all(1)       # (a transition found at all)
    hasT = ~m[:cy, cols].all(0); hasB = ~m[cy:, cols].all(0)
    L, R = edge(rows, left, hasL), edge(rows, right, hasR)          # x = a*y + b
    T, B = edge(cols, top, hasT), edge(cols, bot, hasB)             # y = a*x + b
    # the spine: the darkest column of the middle of the book, row by row (pages are equal width,
    # so the left edge is the right edge mirrored about it - the left edge is often off the picture
    # or under the hand)
    g = cv2.GaussianBlur(GRAY, (1, 31), 0).astype(np.float32)
    sp_rows, sp_x = [], []
    for y in rows[::4]:
        if R is None: break
        xr = R[0] * y + R[1]
        lo, hi = int(max(0, xr - 1.55 * (xr - cx))), int(xr - 0.25 * (xr - cx))
        lo = int(max(0, cx - 0.35 * w)); hi = int(min(W - 1, cx + 0.35 * w))
        seg = g[y, lo:hi]
        if seg.size < 10: continue
        sp_rows.append(y); sp_x.append(lo + int(np.argmin(seg)))
    S_ = ransac(np.array(sp_rows, float), np.array(sp_x, float), tol=4.0) if len(sp_rows) > 10 else None
    if S_ is not None and R is not None:
        L = (2 * S_[0] - R[0], 2 * S_[1] - R[1], S_[2])
    global LAST
    got = [L, R, T, B]
    if sum(x is None for x in got) > 1 or (None in got and LAST is None):
        return None
    if None in got:                                     # one edge out of the picture: from its opposite,
        i = got.index(None)                             # the book's size as in the last whole view
        o = {0: 1, 1: 0, 2: 3, 3: 2}[i]
        g = LAST
        got[i] = (got[o][0] - (g[o][0] - g[i][0]), got[o][1] - (g[o][1] - g[i][1]), 0.0)
    else:
        LAST = [tuple(x) for x in got]
    L, R, T, B = got
    def cross(xl, yl):   # x = xa*y + xb ; y = ya*x + yb
        xa, xb = xl[:2]; ya, yb = yl[:2]
        y = (ya * xb + yb) / (1 - ya * xa); return (xa * y + xb, y)
    q = np.array([cross(L, T), cross(R, T), cross(R, B), cross(L, B)], np.float32)
    return q, (L[2], R[2], T[2], B[2])
if __name__ == '__main__':
    p = subprocess.Popen(['ffmpeg','-loglevel','error','-i',video,'-vf',f'fps={FPS},scale={W}:{H}','-f','rawvideo','-pix_fmt','bgr24','-'],stdout=subprocess.PIPE)
    Q, S = [], []
    while True:
        raw = p.stdout.read(W * H * 3)
        if len(raw) < W * H * 3: break
        im = np.frombuffer(raw, np.uint8).reshape(H, W, 3)
        GRAY = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        r = quad(mask(im))
        Q.append(r[0] if r else np.full((4, 2), np.nan, np.float32)); S.append(r[1] if r else (0, 0, 0, 0))
    np.savez(out, quads=np.array(Q), support=np.array(S), size=(W, H), fps=FPS)
    print('frames', len(Q))
