"""Follow the open book through a video: the open spread's 4 outer corners in every frame.

    python3 book_track.py video ref_time_s "x,y x,y x,y x,y" fps out.npz
Corners (TL TR BR BL of the open spread) are given on the reference frame; every other frame is
matched to the reference by SIFT features on the book (RANSAC homography), falling back to the
previous frame's match when the reference is too different. The hand is masked out.
"""
import json
import subprocess
import sys

import cv2
import numpy as np

video, t_ref, corners_s, fps, out = sys.argv[1], float(sys.argv[2]), sys.argv[3], float(sys.argv[4]), sys.argv[5]
REF = np.array([[float(v) for v in p.split(',')] for p in corners_s.split()], np.float32)
st = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
                                '-of', 'json', video], capture_output=True, text=True).stdout)['streams'][0]
W, H = st['width'], st['height']


def frames(start=None, n=None):
    args = ['ffmpeg', '-loglevel', 'error']
    if start is not None:
        args += ['-ss', f'{start:.3f}']
    args += ['-i', video]
    if n is not None:
        args += ['-frames:v', str(n)]
    args += ['-vf', f'fps={fps}', '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    p = subprocess.Popen(args, stdout=subprocess.PIPE)
    while True:
        raw = p.stdout.read(W * H)
        if len(raw) < W * H:
            break
        yield np.frombuffer(raw, np.uint8).reshape(H, W)


sift = cv2.SIFT_create(nfeatures=4000)
ref_img = next(frames(t_ref, 1))


def book_mask(quad, grow=1.25):
    """The book (the spread's quad grown to take in the cover), as a mask."""
    c = quad.mean(0)
    q = (quad - c) * grow + c
    m = np.zeros((H, W), np.uint8)
    cv2.fillPoly(m, [q.astype(np.int32)], 255)
    return m


ref_kp, ref_des = sift.detectAndCompute(ref_img, book_mask(REF))
matcher = cv2.BFMatcher(cv2.NORM_L2)
hands = np.load(sys.argv[6]) if len(sys.argv) > 6 else None   # (MediaPipe track: mask the hand out)


def match(kp, des, kp2, des2):
    if des is None or des2 is None or len(kp) < 8:
        return None, 0
    m = matcher.knnMatch(des, des2, k=2)
    good = [a for a, b in (x for x in m if len(x) == 2) if a.distance < 0.75 * b.distance]
    if len(good) < 12:
        return None, len(good)
    src = np.float32([kp[g.queryIdx].pt for g in good])
    dst = np.float32([kp2[g.trainIdx].pt for g in good])
    Hm, inl = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    return Hm, int(inl.sum()) if inl is not None else 0


quads, quality = [], []
prev = None                                                 # (homography ref -> previous frame, its keypoints)
for i, img in enumerate(frames()):
    guess = quads[-1] if quads else REF
    m = book_mask(np.array(guess, np.float32))
    if hands is not None and i < len(hands['img']):
        for h in range(2):
            p = hands['img'][i, h]
            if np.isfinite(p[0, 0]):
                xy = (p[:, :2] * (W, H)).astype(np.int32)
                hull = cv2.convexHull(xy)
                cv2.fillConvexPoly(m, hull, 0)
                cv2.dilate(m, np.ones((1, 1), np.uint8))
                x0, y0 = xy.min(0) - 40
                x1, y1 = xy.max(0) + 40
                m[max(0, y0):y1, max(0, x0):x1] = 0          # (the hand and around it)
    kp, des = sift.detectAndCompute(img, m)
    Hm, n_in = match(ref_kp, ref_des, kp, des)                # straight to the reference
    if (Hm is None or n_in < 40) and prev is not None:        # else: through the previous frame
        H2, n2 = match(prev[1], prev[2], kp, des)
        if H2 is not None and n2 > n_in:
            Hm, n_in = H2 @ prev[0], n2
    if Hm is None:
        quads.append(np.array(guess, np.float32))
        quality.append(0)
        continue
    q = cv2.perspectiveTransform(REF[None], Hm)[0]
    quads.append(q)
    quality.append(n_in)
    prev = (Hm, kp, des)
    if i % 50 == 0:
        print('frame', i, 'inliers', n_in, flush=True)
np.savez(out, quads=np.array(quads), quality=np.array(quality), fps=fps, size=(W, H), ref=REF)
print('frames', len(quads), 'weak (<40 inliers)', int((np.array(quality) < 40).sum()))
