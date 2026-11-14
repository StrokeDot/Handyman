"""Per-frame features of the right hand in the book's frame (from handbook.npz)."""
import numpy as np
d = np.load('handbook.npz'); uv, sz, Rb, wl = d['uv'], d['size'], d['Rb'], d['world']
n = len(sz)
valid = np.isfinite(sz) & (np.arange(n) > 8 * 30) & (np.arange(n) < 56 * 30)
valid &= (np.abs(uv[:, :, 0]) < 2.0).all(1) & (uv[:, :, 1] > -0.8).all(1) & (uv[:, :, 1] < 1.4).all(1)
FING = dict(thumb=(1, 2, 3, 4), index=(5, 6, 7, 8), middle=(9, 10, 11, 12), ring=(13, 14, 15, 16), pinky=(17, 18, 19, 20))
def ang(a, b, c):
    u, v = a - b, c - b
    cs = (u * v).sum(-1) / (np.linalg.norm(u, axis=-1) * np.linalg.norm(v, axis=-1) + 1e-9)
    return 180 - np.degrees(np.arccos(np.clip(cs, -1, 1)))
curls = np.full((n, 5, 3), np.nan)
for i, (f, (a, b, c, e)) in enumerate(FING.items()):
    base = wl[:, 0] if f != 'thumb' else wl[:, 0]
    curls[:, i] = np.stack([ang(base, wl[:, a], wl[:, b]), ang(wl[:, a], wl[:, b], wl[:, c]), ang(wl[:, b], wl[:, c], wl[:, e])], 1)
fwd = np.full((n, 3), np.nan); up = np.full((n, 3), np.nan)
for f in np.where(valid)[0]:
    R = Rb[f]
    fc = wl[f, 9] - wl[f, 0]; sc = wl[f, 5] - wl[f, 17]
    fb, sb = R.T @ fc, R.T @ sc
    fb /= np.linalg.norm(fb)
    ub = np.cross(fb, sb); ub /= np.linalg.norm(ub)
    fwd[f], up[f] = fb, ub
pinch = (uv[:, 4] + uv[:, 8]) / 2
np.savez('features.npz', valid=valid, uv=uv, pinch=pinch, size=sz, curls=curls, fwd=fwd, up=up)
v = valid
print('valid', v.sum())
print('rest-ish (pinch u>0.85): fwd median', np.round(np.nanmedian(fwd[v & (pinch[:, 0] > 0.85)], 0), 2), 'up', np.round(np.nanmedian(up[v & (pinch[:, 0] > 0.85)], 0), 2))
print('on the left (pinch u<-0.6): fwd', np.round(np.nanmedian(fwd[v & (pinch[:, 0] < -0.6)], 0), 2), 'up', np.round(np.nanmedian(up[v & (pinch[:, 0] < -0.6)], 0), 2))
print('curls rest median', np.round(np.nanmedian(curls[v & (pinch[:, 0] > 0.85)], 0)).tolist())
