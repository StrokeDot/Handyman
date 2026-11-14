"""Shared (averaged over repeats) motion of the two RDR2 turns, from features.npz.
For each kind: per template frame (30 fps, relative to the aligned event): pinch point (u, v),
knuckle centre (u, v), hand direction on the page (unit 2D, metric), finger curls (5x3 deg)."""
import numpy as np
ASPECT = 1.25
F = np.load('features.npz'); valid, uv, curls = F['valid'], F['uv'], F['curls']
n = len(valid)
pinch = (uv[:, 4] + uv[:, 8]) / 2
knuck = uv[:, [5, 9, 13, 17]].mean(1)
side = (uv[:, 5] - uv[:, 17]) * (1, ASPECT)                       # index knuckle - pinky knuckle (metric)
dir2 = np.stack([side[:, 1], -side[:, 0]], 1)                     # fingers' way (palm down, right hand)
dir2 /= np.linalg.norm(dir2, axis=1, keepdims=True) + 1e-9
feat = np.concatenate([pinch, knuck, dir2, curls.reshape(n, 15)], 1)   # 2 + 2 + 2 + 15
fr = np.where(valid)[0]
d = np.load('handbook.npz'); wu = d['uv'][:, 0, 0]
def events_back():
    ev, last_right = [], -999
    for f in fr:
        if pinch[f, 0] > 0.6: last_right = f
        if pinch[f, 0] < -0.3 and f - last_right < 24 and (not ev or f - ev[-1] > 30): ev.append(f)
    return ev
def events_fwd():
    hi = [f for f in fr if 0.2 < pinch[f, 0] < 1.4 and pinch[f, 1] > 0.45]
    ev = []
    for f in hi:
        if not ev or f - ev[-1][-1] > 15: ev.append([f])
        else: ev[-1].append(f)
    return [max(e, key=lambda f: pinch[f, 1]) for e in ev]
def build(ev, PRE, POST, key):
    def samples(off):
        return [(f - e - o, f) for e, o in zip(ev, off) for f in fr[(fr >= e + o - PRE) & (fr <= e + o + POST)]]
    def template(S):
        T = np.full((PRE + POST + 1, feat.shape[1]), np.nan); cnt = np.zeros(PRE + POST + 1, int)
        for k in range(-PRE, POST + 1):
            sel = [f for kk, f in S if abs(kk - k) <= 1.5]
            if len(sel) >= 2: T[k + PRE] = np.nanmedian(feat[sel], 0); cnt[k + PRE] = len(sel)
        return T, cnt
    off = [0] * len(ev)
    for _ in range(4):
        T, _c = template(samples(off))
        new = []
        for e, o in zip(ev, off):
            best = None
            for dx in range(-8, 9):
                fs = fr[(fr >= e + o + dx - PRE) & (fr <= e + o + dx + POST)]
                k = fs - e - o - dx + PRE
                m = np.isfinite(T[k, 0])
                if m.sum() >= 4:
                    err = np.mean(np.sum((feat[fs[m]][:, key] - T[k[m]][:, key]) ** 2, 1))
                    if best is None or err < best[0]: best = (err, o + dx)
            new.append(best[1] if best else o)
        off = new
    T, cnt = template(samples(off))
    # gaps: interpolate; then smooth lightly (positions) - curls more
    idx = np.arange(len(T))
    for c in range(T.shape[1]):
        ok = np.isfinite(T[:, c])
        if ok.sum() >= 2: T[:, c] = np.interp(idx, idx[ok], T[ok, c])
    from scipy.ndimage import gaussian_filter1d
    T[:, :6] = gaussian_filter1d(T[:, :6], 1.2, axis=0, mode='nearest')
    T[:, 6:] = gaussian_filter1d(T[:, 6:], 2.5, axis=0, mode='nearest')
    T[:, 4:6] /= np.linalg.norm(T[:, 4:6], axis=1, keepdims=True)
    return T, cnt, off
ef = events_fwd()
eb = [e for e in events_back() if not any(0 <= e - x <= 24 for x in ef)]   # (not the end of a forward turn)
print('back events', len(eb), [round(e / 30, 2) for e in eb]); print('fwd events', len(ef), [round(e / 30, 2) for e in ef])
Tb, cb, ob = build(eb, 36, 54, [0, 1])
Tf, cf, of = build(ef, 45, 45, [0, 1])
# the resting pose: frames holding the right edge, not moving
rest_sel = [f for f in fr if pinch[f, 0] > 0.85 and pinch[f, 0] < 1.15 and 0.15 < pinch[f, 1] < 0.55]
rest = np.nanmedian(feat[rest_sel], 0)
np.savez('templates.npz', back=Tb, back_cnt=cb, fwd=Tf, fwd_cnt=cf, rest=rest, back_pre=36, fwd_pre=45, fps=30)
print('rest pinch', np.round(rest[:2], 3), 'knuckles', np.round(rest[2:4], 3), 'dir', np.round(rest[4:6], 2))
print('back coverage (samples per frame) min %d median %d' % (cb[cb > 0].min(), np.median(cb)), 'zero-frames', (cb == 0).sum())
print('fwd coverage min %d median %d' % (cf[cf > 0].min(), np.median(cf)), 'zero-frames', (cf == 0).sum())
