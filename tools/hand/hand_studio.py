"""The hands alone, in still poses that test the model (no page turning): resting, the forearm
turned palm down -> thumb up -> palm up, the wrist bent up and down, fingers flat / relaxed /
gripping. Writes a live-view hand file (as hand_bake.py does), one pose per frame:

    python3 hand_studio.py base_job.json out/hands.npz
then look at it with the live view's own drawing (frame = pose number).
POSES lists them in order.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))

import bpy  # noqa: E402,F401
import numpy as np  # noqa: E402
from mathutils import Matrix, Quaternion, Vector  # noqa: E402

import hand_bake  # noqa: E402

# (name, roll about the forearm: 0 palm down, 90 thumb up, 180 palm up; wrist bend: + back of the
#  hand up, - palm down; fingers: -1 flat, 0 relaxed, 1 grip)
POSES = [('rest', 0, 0, 0.0), ('roll 45', 45, 0, 0.0), ('thumb up', 90, 0, 0.0), ('roll 135', 135, 0, 0.0),
         ('palm up', 180, 0, 0.0), ('roll -30', -30, 0, 0.0), ('wrist up 30', 0, 30, 0.0),
         ('wrist up 60', 0, 60, 0.0), ('wrist down 30', 0, -30, 0.0), ('wrist down 60', 0, -60, 0.0),
         ('flat', 0, 0, -1.0), ('grip', 0, 0, 1.0), ('thumb up + grip', 90, 20, 1.0),
         ('thumb up wrist up 45', 90, 45, 0.6)]


def studio_poses(hand, where):
    """Each pose about one wrist place: the hand's frame turned about the forearm's line."""
    fwd0 = Vector((-0.25 * hand.mx, 1.0, -0.05)).normalized()   # (fingers forward, a little inwards)
    up0 = Vector((0.0, 0.0, 1.0))
    up0 = (up0 - fwd0 * up0.dot(fwd0)).normalized()
    side = fwd0.cross(up0)
    out = []
    for _name, roll, bend, fingers in POSES:
        Rb = Quaternion(side, math.radians(bend)).to_matrix()
        f1, u1 = Rb @ fwd0, Rb @ up0
        Rr = Quaternion(fwd0, math.radians(-roll * hand.mx)).to_matrix()
        f2, u2 = Rr @ f1, Rr @ u1
        p = Vector(where) + f2 * 0.12                         # (the pinch ahead of the wrist place)
        out.append([tuple(p), tuple(f2), tuple(u2), fingers, 0.0])
    return out


def main():
    args = [a for a in sys.argv[1:] if a != '--']
    job = json.load(open(args[0]))
    job = dict(job, hand=True, hand_left=True, hand_left_style='on', hand_bake_out=os.path.abspath(args[1]))
    job['clip_list'] = [dict(kind='open', start=0, duration=2, smoothness=1.0)]
    job['end_hold'] = len(POSES) / float(job.get('fps') or 30) + 0.5
    os.makedirs(os.path.dirname(job['hand_bake_out']), exist_ok=True)
    real = hand_bake.JS.make_hands

    def make(job_, root, sc, n, strap_u, held_up):
        hand, _p, left, _lp = real(job_, root, sc, n, strap_u, held_up)
        frames = sc.frames
        rp = studio_poses(hand, (1.25, 0.35, 0.25))
        lp = studio_poses(left, (-1.25, 0.35, 0.25)) if left is not None else None
        pad = lambda ps: ps + [ps[-1]] * max(0, frames - len(ps))
        return hand, pad(rp), left, (pad(lp) if lp else None)
    hand_bake.JS.make_hands = make
    path = os.path.join(os.path.dirname(job['hand_bake_out']), 'studio_job.json')
    with open(path, 'w') as fh:
        json.dump(job, fh)
    sys.argv = ['hand_bake.py', '--', path]
    hand_bake.main()
    _ = (np, Matrix)


if __name__ == '__main__':
    main()
