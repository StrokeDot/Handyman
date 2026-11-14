"""The right hand in the book's own frame, per frame (from trk_*.npz + quads_smooth.npy).
u: -1 left edge .. 0 spine .. 1 right edge; v: 0 bottom .. 1 top (of the spread)."""
import numpy as np, cv2, math
W, H = 1280, 720
F = 1139.0
Q = np.load('quads_smooth.npy')
A = np.load('trk_plain.npz'); B = np.load('trk_bright.npz')
n = min(len(Q), len(A['img']))
dst = np.array([[-1, 1], [1, 1], [1, 0], [-1, 0]], np.float32)     # TL TR BR BL -> book (u, v)
K = np.array([[F, 0, W / 2], [0, F, H / 2], [0, 0, 1]])
ASPECT = 1.25                                                       # page height / page width
out = dict(uv=np.full((n, 21, 2), np.nan), size=np.full(n, np.nan), Rb=np.full((n, 3, 3), np.nan),
           world=np.full((n, 21, 3), np.nan), src=np.zeros(n, int))
prev = None
for f in range(n):
    cands = []
    for T, tag in ((A, 1), (B, 2)):
        for h in range(2):
            p = T['img'][f, h]
            if np.isfinite(p[0, 0]):
                cands.append((p[:, :2] * (W, H), T['world'][f, h], tag))
    if not cands:
        continue
    # the right hand: the one nearest where it was (else the one furthest right)
    if prev is not None:
        c = min(cands, key=lambda c: np.linalg.norm(c[0][0] - prev))
        if np.linalg.norm(c[0][0] - prev) > 260 and len(cands) > 1:
            c = max(cands, key=lambda c: c[0][9, 0])
    else:
        c = max(cands, key=lambda c: c[0][9, 0])
    px, wl, tag = c
    prev = px[0]
    Hm = cv2.getPerspectiveTransform(Q[f].astype(np.float32), dst)
    uv = cv2.perspectiveTransform(px[None].astype(np.float32), Hm)[0]
    out['uv'][f] = uv; out['src'][f] = tag
    out['size'][f] = np.linalg.norm(uv[9] - uv[0])                  # wrist -> middle knuckle, in book u units
    # the book's rotation in the camera (plane metric: x = u * half-width, y = v * height)
    Hp = cv2.getPerspectiveTransform(np.array([[-1, ASPECT], [1, ASPECT], [1, 0], [-1, 0]], np.float32), Q[f].astype(np.float32))
    M = np.linalg.inv(K) @ Hp
    r1, r2 = M[:, 0], M[:, 1]
    s = 2.0 / (np.linalg.norm(r1) + np.linalg.norm(r2))
    r1, r2 = r1 * s, r2 * s
    r3 = np.cross(r1, r2)
    U, _, Vt = np.linalg.svd(np.stack([r1, r2, r3], 1))
    out['Rb'][f] = U @ Vt                                            # book axes in camera coords
    out['world'][f] = wl
np.savez('handbook.npz', **out)
ok = np.isfinite(out['size'])
print('frames with the right hand', ok.sum(), 'palm size (u units) median %.3f' % np.nanmedian(out['size']))
