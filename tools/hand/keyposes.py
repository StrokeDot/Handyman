"""The eight key poses of Arthur Morgan's page turn (from the RDR2 reference), rendered on the
book at the matching page angles, top-down, for approval.

Conventions: book space x right, y up the book, z up. A page's frame is (towards the spine, up the
page, its front). The hand works on the page's BACK (the side underneath before the turn, on top
after it): finger pads at point - n*gap, back of the hand facing -n.

    python3 keyposes.py job.json out_dir
"""
import json
import math
import os
import sys

sys.path.insert(0, '/home/claude/handyman')
import numpy as np  # noqa: E402

import hand_scene as H  # noqa: E402

job_path, OUT = sys.argv[1], sys.argv[2]
KEYS = ['rest', 'reach', 'lift', 'upright', 'push', 'press', 'exit', 'return']
TARGET_DEG = {'lift': 30.0, 'upright': 90.0, 'push': 140.0}
FRAMES = {}
REPORT = {}


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def key_pose(name, hand, page, cm):
    """page(along, up) -> (point, (e_in, e_edge, n)) on the page being turned (its front = n)."""
    from mathutils import Vector
    gap = H.PAD_GAP_CM * cm
    rest_fwd = hand.rest_frame.col[0]

    def clamp(target, thumb_to_index, fingers, amount=None, low=1.0, wrist_at=None):
        # thumb on one side of an edge, fingers on the other (part-closed grip), as Arthur holds
        # paper. The grip's axis may tilt: pick the one that keeps the wrist low and natural.
        from mathutils import Quaternion
        a0, fin = Vector(thumb_to_index).normalized(), Vector(fingers).normalized()
        perp = a0.orthogonal().normalized()
        P = Vector(target) / hand.s
        best = None
        for tilt in range(0, 71, 10):
            for az in range(0, 360, 30 if tilt else 360):
                a = Quaternion(a0, math.radians(az)) @ (Quaternion(perp, math.radians(tilt)) @ a0)
                for d in range(0, 360, 15):
                    f_ = Quaternion(a, math.radians(d)) @ fin
                    R = H._basis(a, f_) @ H._basis(hand.clamp_axis0, rest_fwd).transposed()
                    fw = R @ rest_fwd
                    W = P - R @ (hand.clamp0 - hand.wrist0)
                    wz = (W.z * hand.s - Vector(target).z) / cm          # wrist height over the grip, cm
                    wy = (W.y * hand.s - Vector(target).y) / cm          # wrist below (-) / above the grip, cm
                    c = hand._bend(P, R, hand.clamp0) + low * 4.0 * max(0.0, wz + 3.0) \
                        + (6.0 * max(0.0, abs(wy) - 1.5) if wrist_at is None else
                           3.0 * ((W * hand.s - Vector(target)) / cm - Vector(wrist_at)).length) \
                        + 80.0 * max(0.0, fw.dot(-fin) + 0.2)            # fingers must point in, not out
                    if best is None or c < best[0]:
                        best = (c, R, wz)
        _, R, wz = best
        print('CLAMP wrist above grip cm', round(wz, 1))
        point = Vector(target) + (R @ (hand.pinch0 - hand.clamp0)) * hand.s
        return hand.pose(point, R, hand.clamp_amount if amount is None else amount, 0.0)

    def flat(pads, fingers, back, amount=-0.9):
        f, u = _unit(fingers), _unit(back)
        f = _unit(f - u * float(f @ u))
        R = H._frame(Vector(f), Vector(u)) @ hand.rest_frame.transposed()
        return hand.pose(Vector(pads), R, amount, 1.0)

    if name in ('rest', 'reach', 'lift'):
        at = {'rest': 0.28, 'reach': 0.32, 'lift': 0.36}[name]
        p, (e_in, e_edge, n) = page(1.0, at)
        p, e_in, n = (np.array(v, float) for v in (p, e_in, n))
        target = p + e_in * 0.2 * cm - n * 0.03 * cm       # just in from the edge, at the paper
        if name == 'rest':                                 # the whole block: thumb on top, fingers under
            target = p + e_in * 0.25 * cm + np.array((0, 0, -0.5 * cm))
        fingers = e_in * 1.0 - n * 0.35 + np.array((0, 0.15, 0))
        # as in the game: the hand at the book's lower right corner, the thumb lying on the page,
        # the fingers under it, the wrist out beyond the corner (cm from the grip: right, down, below)
        return clamp(target, -n, fingers, None if name != 'reach' else hand.clamp_amount * 0.6,
                     wrist_at=(4.0, -7.0, -2.0))
    if name == 'upright':                                  # as in the game: the standing page held near its
        p, (e_in, e_edge, n) = page(0.86, 0.42)            # free edge between the thumb (on its front) and the
        p, e_edge, n = (np.array(v, float) for v in (p, e_edge, n))   # fingers (behind it), fingers up the book,
        return clamp(p, -n, e_edge, amount=0.75, wrist_at=(3.0, -9.0, -3.0))   # the back of the hand towards us
    if name in ('upright', 'push', 'press'):
        at = {'upright': (0.74, 0.68), 'push': (0.62, 0.6), 'press': (0.62, 0.36)}[name]
        p, (e_in, e_edge, n) = page(*at)
        p, e_in, e_edge, n = (np.array(v, float) for v in (p, e_in, e_edge, n))
        if name == 'press':
            fingers = np.array((-0.6, 0.8, 0.0))           # up and to the left, flat
        else:
            fingers = e_edge - e_in * 0.35                 # up the book, a little towards the free edge
        return flat(p - n * gap, fingers, -n, {'upright': -0.85, 'push': -0.9, 'press': -1.0}[name])
    if name == 'exit':                                     # sliding down off the bottom of the left page
        p, (e_in, e_edge, n) = page(0.6, 0.06)
        p, n = np.array(p, float), np.array(n, float)
        return flat(p - n * gap * 2, (-0.55, 0.8, -0.1), -n, -0.8)
    if name == 'return':                                   # back holding the book's right edge, as at rest
        return key_pose('rest', hand, page, cm)
        p = np.array((1.0 + 3.0 * cm, -hand.half_h + 0.25 * 2 * hand.half_h, -1.5 * cm))
        return flat(p, (-0.9, 0.3, -0.3), (0.3, 0, 1), -0.4)


orig_plan = H.plan


def plan(hand, n_frames, fps, state_at, strap_u=None, held_up=False):
    out = orig_plan(hand, n_frames, fps, state_at, strap_u, held_up)
    cm = 1.0 / hand.pw

    def angle(f, along=1.0):
        ts, cw = state_at(f)[:2]
        _, fr = hand.page_at(0, ts[0], cw[0], along, 0.42)
        n = fr[2]
        return math.degrees(float(np.clip(math.atan2(-n[0], n[2]), 0.0, math.pi)))
    angs = [angle(f) for f in range(n_frames)]
    start = next(f for f, a in enumerate(angs) if a > 0.5)
    land = next(f for f, a in enumerate(angs) if a > 179.0)
    FRAMES.update(rest=2, reach=start - 1, press=land, exit=land + 5, **{'return': land + 12})
    for k, d in TARGET_DEG.items():
        FRAMES[k] = min(range(start, land + 1), key=lambda f: abs(angle(f, 0.6) - d))
    for k in KEYS:
        f = FRAMES[k]
        ts, cw = state_at(f)[:2]
        sh = 1 if k == 'return' else 0                     # back on the next page, the top one on the right
        pose = key_pose(k, hand, lambda along, up: hand.page_at(sh, ts[sh], cw[sh], along, up), cm)
        if pose is not None:
            out[f] = pose
        REPORT[k] = dict(frame=f, page_deg=round(angs[f], 1))
    return out


H.plan = plan
import journal_scene as JS  # noqa: E402

job = dict(json.load(open(job_path)), turn_style='pushed')
# first pass: only work out the frames (render nothing), then render just those
JS.hand_scene = H
sys.argv = ['x', '--', job_path]
orig_main = JS.main


class _Stop(Exception):
    pass


def _probe():
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    root, _, _, _, obs, strap = JS.build(job)
    sc = JS.job_scene(job)
    JS.make_hands(job, root, sc, len(obs), None, job.get('hand_left_style') == 'under')


_probe()
job2 = dict(job, turn_style='pushed', frames=[FRAMES[k] for k in KEYS], out_dir=OUT, width=960, height=540, samples=16,
            cam=dict(job['cam'], zoom=float(os.environ.get('ZOOM', '1.5')), tilt=float(os.environ.get('TILT', '89')), turn=float(os.environ.get('TURN', '0'))))
os.makedirs(OUT, exist_ok=True)
json.dump(job2, open(os.path.join(OUT, 'job.json'), 'w'))
json.dump(dict(frames=FRAMES, report=REPORT), open(os.path.join(OUT, 'keys.json'), 'w'), indent=1)
sys.argv = ['x', '--', os.path.join(OUT, 'job.json')]
JS.main()
print('KEYS', REPORT)
