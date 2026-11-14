"""The hand in 3D relative to the book, per frame.

    python3 hand3d.py book.npz track.npz focal_px spread_w_m spread_h_m out.npz
Book: its spread's 4 corners per frame (book_track.py) and its real size -> the camera's pose
relative to the book (solvePnP). Hand: MediaPipe's 21 points in metres (the hand's own shape) and
where they are in the picture -> the hand's pose relative to the camera (solvePnP). Together:
every hand point in book coordinates (metres; x across the spread from its middle, y up the page,
z out of the page towards the reader; the page surface is z = 0).
"""
import sys

import cv2
import numpy as np

book, track, f, sw, sh, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]), sys.argv[6]
PALM_M = float(sys.argv[7]) if len(sys.argv) > 7 else 0.0907   # wrist to knuckles (mean), metres
B = np.load(book)
T = np.load(track)
W, H = [int(x) for x in B['size']]
K = np.array([[f, 0, W / 2], [0, f, H / 2], [0, 0, 1]], np.float64)
dist = np.zeros(5)
plane = np.array([[-sw / 2, sh / 2, 0], [sw / 2, sh / 2, 0], [sw / 2, -sh / 2, 0], [-sw / 2, -sh / 2, 0]], np.float64)
n = min(len(B['quads']), len(T['img']))
P = np.full((n, 21, 3), np.nan)            # hand points in book coordinates
cam_pos = np.full((n, 3), np.nan)          # the camera, in book coordinates
err = np.full(n, np.nan)                   # the hand's reprojection error (px)
for i in range(n):
    if B['quality'][i] < 40:
        continue
    ok, rb, tb = cv2.solvePnP(plane, B['quads'][i].astype(np.float64), K, dist, flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        continue
    Rb = cv2.Rodrigues(rb)[0]
    cam_pos[i] = (-Rb.T @ tb).ravel()
    # the right hand (MediaPipe's label), else the only hand
    hs = [h for h in range(2) if np.isfinite(T['img'][i, h, 0, 0])]
    h = next((h for h in hs if T['label'][i, h] == 1), hs[0] if hs else None)
    if h is None:
        continue
    obj = T['world'][i, h].astype(np.float64)
    # a real hand keeps its size: the tracker's own guess of it wobbles from frame to frame
    # (+-14%), which at arm's length is several cm of false depth - every frame is set to one size
    palm = np.mean([np.linalg.norm(obj[k] - obj[0]) for k in (5, 9, 13, 17)])
    obj = obj * (PALM_M / palm)
    img = (T['img'][i, h, :, :2] * (W, H)).astype(np.float64)
    ok, rh, th = cv2.solvePnP(obj, img, K, dist, flags=cv2.SOLVEPNP_SQPNP)
    if not ok:
        continue
    ok, rh, th = cv2.solvePnP(obj, img, K, dist, rh, th, useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE)
    Rh = cv2.Rodrigues(rh)[0]
    proj, _ = cv2.projectPoints(obj, rh, th, K, dist)
    err[i] = float(np.linalg.norm(proj[:, 0] - img, axis=1).mean())
    Xc = obj @ Rh.T + th.ravel()                     # in the camera's coordinates
    P[i] = (Xc - tb.ravel()) @ Rb                    # in the book's (Rb^T (Xc - tb))
np.savez(out, P=P, cam=cam_pos, err=err, fps=float(T['fps']), spread=(sw, sh))
ok = np.isfinite(P[:, 0, 0])
print('frames with the hand placed', int(ok.sum()), 'of', n, '| reprojection error px median %.1f' % np.nanmedian(err))
print('camera height above the book (cm): median %.1f' % (np.nanmedian(cam_pos[:, 2]) * 100))
z = P[ok][:, [4, 8, 12], 2] * 100
print('fingertip height above the page (cm): 5%% %.1f  median %.1f  95%% %.1f' % tuple(np.percentile(z, [5, 50, 95])))
