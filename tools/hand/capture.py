"""Finger poses from a filmed page turn (a development tool, not part of the app).

    python3 capture.py video.mp4 hand_landmarker.task out_dir [--fps 15] [--width 960]

Tracks the hands in the video with MediaPipe's hand landmarker (pip install mediapipe; the model
file hand_landmarker.task is Google's, Apache-2.0 - download it from the MediaPipe pages), then:

  out_dir/track.npz      the 21 tracked points of each hand, per frame (picture and metres)
  out_dir/overlay.png    the tracked points drawn on 12 frames - check the tracking is on the hand
  out_dir/curves.png     each finger's bend, thumb-to-index distance and the wrist's path over time
  out_dir/phases.json    the page turns found (the wrist sweeping right to left: the push across),
                         how long each part took, and each finger's median bend (degrees, per
                         joint, 0 = straight) while holding the edge, pushing, pressing, returning

Film from above, the book flat, the right hand turning pages (a phone over the table works).
Turn the bends into the rig's poses by adding them to its flat pose (hand_scene.CAPTURED_GRIP
came from this; a camera from above reads root-joint bends low, so do not straighten a finger
the rig already bends more).
Gloved, dark or cropped hands (game footage) are not found - film a bare hand instead.
"""
import json
import os
import subprocess
import sys

import numpy as np

BONES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12),
         (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]
FINGERS = dict(thumb=(1, 2, 3, 4), index=(5, 6, 7, 8), middle=(9, 10, 11, 12), ring=(13, 14, 15, 16), pinky=(17, 18, 19, 20))


def track(video, model, fps, width):
    import mediapipe as mp
    from mediapipe.tasks import python as mpp
    from mediapipe.tasks.python import vision
    st = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                    'stream=width,height', '-of', 'json', video],
                                   capture_output=True, text=True).stdout)['streams'][0]
    W = width
    H = int(round(st['height'] * W / st['width'] / 2) * 2)
    proc = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-i', video, '-vf', f'fps={fps},scale={W}:{H}',
                             '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    opts = vision.HandLandmarkerOptions(base_options=mpp.BaseOptions(model_asset_path=os.path.abspath(model)),
                                        running_mode=vision.RunningMode.VIDEO, num_hands=2,
                                        min_hand_detection_confidence=0.3, min_hand_presence_confidence=0.3,
                                        min_tracking_confidence=0.3)
    lm = vision.HandLandmarker.create_from_options(opts)
    img, world, label = [], [], []
    i = 0
    while True:
        raw = proc.stdout.read(W * H * 3)
        if len(raw) < W * H * 3:
            break
        frame = np.ascontiguousarray(np.frombuffer(raw, np.uint8).reshape(H, W, 3))
        r = lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=frame), int(i * 1000 / fps))
        ip = np.full((2, 21, 3), np.nan, np.float32)
        wp = np.full((2, 21, 3), np.nan, np.float32)
        lb = np.full(2, -1, np.int8)
        for h, (pts, wpts, hd) in enumerate(zip(r.hand_landmarks, r.hand_world_landmarks, r.handedness)):
            if h > 1:
                break
            ip[h] = [(p.x, p.y, p.z) for p in pts]
            wp[h] = [(p.x, p.y, p.z) for p in wpts]
            lb[h] = 1 if hd[0].category_name == 'Right' else 0
        img.append(ip)
        world.append(wp)
        label.append(lb)
        i += 1
    proc.stdout.close()
    proc.wait()
    lm.close()
    return np.array(img), np.array(world), np.array(label), (W, H)


def overlay(video, img, label, fps, size, out, n=12):
    from PIL import Image, ImageDraw
    W, H = size
    tiles = []
    for i in np.linspace(0, len(img) - 1, n).astype(int):
        raw = subprocess.run(['ffmpeg', '-loglevel', 'error', '-ss', f'{i / fps:.3f}', '-i', video, '-frames:v', '1',
                              '-vf', f'scale={W}:{H}', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                             capture_output=True).stdout
        im = Image.fromarray(np.frombuffer(raw, np.uint8)[:W * H * 3].reshape(H, W, 3).copy())
        dr = ImageDraw.Draw(im)
        for h in range(2):
            p = img[i, h]
            if not np.isfinite(p[0, 0]):
                continue
            col = (255, 60, 60) if label[i, h] == 1 else (60, 160, 255)
            xy = p[:, :2] * (W, H)
            for a, b in BONES:
                dr.line([tuple(xy[a]), tuple(xy[b])], fill=col, width=3)
        dr.text((8, 8), f'{i / fps:.1f}s', fill=(255, 255, 255))
        tiles.append(im.resize((W // 2, H // 2)))
    sheet = Image.new('RGB', (4 * W // 2, ((len(tiles) + 3) // 4) * H // 2))
    for k, t in enumerate(tiles):
        sheet.paste(t, ((k % 4) * W // 2, (k // 4) * H // 2))
    sheet.save(out)


def _angle(a, b, c):
    u, v = a - b, c - b
    cs = (u * v).sum(-1) / (np.linalg.norm(u, axis=-1) * np.linalg.norm(v, axis=-1) + 1e-9)
    return 180.0 - np.degrees(np.arccos(np.clip(cs, -1, 1)))      # 0 = straight


def analyse(img, world, label, fps, size, out_dir):
    from scipy.ndimage import median_filter
    T = len(img)
    R = np.full((T, 21, 3), np.nan)
    Ri = np.full((T, 21, 3), np.nan)
    for i in range(T):                                      # the right hand (or the only one)
        hs = [h for h in range(2) if np.isfinite(img[i, h, 0, 0])]
        h = next((h for h in hs if label[i, h] == 1), hs[0] if hs else None)
        if h is not None:
            R[i], Ri[i] = world[i, h], img[i, h]
    bend = {f: np.stack([_angle(R[:, 0], R[:, a], R[:, b]), _angle(R[:, a], R[:, b], R[:, c]),
                         _angle(R[:, b], R[:, c], R[:, e])], 1) for f, (a, b, c, e) in FINGERS.items()}
    pinch = np.linalg.norm(R[:, 4] - R[:, 8], axis=1) * 100
    t = np.arange(T) / fps
    wx = Ri[:, 0, 0] * size[0]
    ok = np.isfinite(wx)
    if ok.sum() < 2:
        raise SystemExit('no hand found in the video')
    wx = median_filter(np.interp(np.arange(T), np.where(ok)[0], wx[ok]), 5)
    v = np.gradient(wx) * fps
    # the pushes across: the wrist sweeping right to left (more than a fifth of the picture)
    turns, i = [], 0
    while i < T:
        if v[i] < -0.26 * size[0]:
            a = i
            while a > 0 and v[a - 1] < -0.08 * size[0]:
                a -= 1
            j = i
            while j < T and v[j] < -0.08 * size[0]:
                j += 1
            b = j - 1
            if wx[a] - wx[b] > 0.2 * size[0]:
                c = b
                while c < T - 1 and v[c + 1] < 0.12 * size[0]:
                    c += 1
                r = c
                while r < T - 1 and v[r + 1] > 0.04 * size[0]:
                    r += 1
                turns.append((a, b, c, r))
            i = j
        else:
            i += 1
    parts = {'hold': [], 'push': [], 'press': [], 'return': []}
    times = []
    for a, b, c, r in turns:
        parts['hold'] += list(range(max(0, a - int(fps)), a))
        parts['push'] += list(range(a, b + 1))
        parts['press'] += list(range(b + 1, c + 1))
        parts['return'] += list(range(c + 1, r + 1))
        times.append(dict(at_s=round(a / fps, 2), push_s=round((b - a) / fps, 2), press_s=round((c - b) / fps, 2),
                          return_s=round((r - c) / fps, 2)))
    med = {p: {f: (np.nanmedian(bend[f][ix], 0).round(1).tolist() if ix else None) for f in FINGERS}
           for p, ix in parts.items()}
    tips = {p: (round(float(np.nanmedian(pinch[ix])), 1) if ix else None) for p, ix in parts.items()}
    res = dict(frames=T, with_hand=int(ok.sum()), turns=times, bend_deg=med, thumb_index_cm=tips)
    with open(os.path.join(out_dir, 'phases.json'), 'w') as fh:
        json.dump(res, fh, indent=1)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(3, 1, figsize=(18, 10), sharex=True)
    for f in FINGERS:
        ax[0].plot(t, bend[f][:, 1:].sum(1), label=f)
    ax[0].legend()
    ax[0].set_ylabel('bend (deg, middle + end joints)')
    ax[1].plot(t, pinch, 'k')
    ax[1].set_ylabel('thumb-index tips (cm)')
    ax[2].plot(t, wx, label='wrist x (px)')
    for a, b, c, r in turns:
        ax[2].axvspan(a / fps, b / fps, color='orange', alpha=0.3)
    ax[2].legend()
    for a_ in ax:
        a_.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, 'curves.png'), dpi=70)
    return res


def main():
    args = [a for a in sys.argv[1:] if a != '--']
    video, model, out_dir = args[:3]
    fps = float(args[args.index('--fps') + 1]) if '--fps' in args else 15.0
    width = int(args[args.index('--width') + 1]) if '--width' in args else 960
    os.makedirs(out_dir, exist_ok=True)
    img, world, label, size = track(video, model, fps, width)
    np.savez_compressed(os.path.join(out_dir, 'track.npz'), img=img, world=world, label=label, fps=fps, size=size)
    overlay(video, img, label, fps, size, os.path.join(out_dir, 'overlay.png'))
    res = analyse(img, world, label, fps, size, out_dir)
    print(json.dumps(dict(frames=res['frames'], with_hand=res['with_hand'], turns=res['turns']), indent=1))


if __name__ == '__main__':
    main()
