"""The hand that turns the pages, for the final render (inside Blender, used by journal_scene.py).

The hand, forearm and sleeve come ready-made in resources/hand/hand.blend (shape from MakeHuman /
MPFB2, CC0; skin painted from photos). Here they are posed on every frame:

* a right arm with a shoulder fixed off to the front right of the book (real-world centimetres,
  so a small book gets a big hand, as in life); the elbow finds its own place (two-bone IK);
* before each page turn the hand reaches the page's bottom fore-edge corner and pinches it,
  carries it over while the page turns, lets go about halfway, and moves on to the next page;
* before the first turn it comes in from the right, after the last it goes back out.

Everything is worked out ahead (plan) from the timeline, so any frame can be rendered on its own
(the app renders parts of a video side by side) and still match its neighbours.
"""
import json
import math
import os

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

import journal_geom as G

HERE = os.path.dirname(os.path.abspath(__file__))
ASSET = os.path.join(HERE, 'resources', 'hand', 'hand.blend')

SHOULDER_CM = (33.0, -30.0, 30.0)   # right of the spine, in front of the bottom edge, above the table
REST_CM = (52.0, -22.0, 14.0)       # where the hand waits before the first turn and after the last (off to the side)
GRAB_UP = 0.07                      # pinch this far up from the bottom corner (share of page height)
GRAB_IN = 0.035                     # ...and this far in from the fore-edge (share of page width)
RELEASE = 0.42                      # let go at this turn progress (the page then falls by itself)
FOLLOW = 0.5                        # the hand turns this share of the page's turn (paper slides in the fingers)
LOOSE = 0.3                         # open fingers stay this much curled (0 = straight, 1 = pinch)
LEAD_S = 0.35                       # be at the corner this long before the page starts to move
PINCH_S = 0.2                       # time to close or open the fingers
ENTER_S = 1.0                       # time to come in at the start, or go out at the end
ELBOW_ABOVE_CM = 6.0                # the elbow stays at least this high above the table
MAX_BEND = 45.0                     # degrees the wrist may bend away from the forearm's line
FINGERS = ('thumb', 'index', 'middle', 'ring', 'pinky')


def _smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _frame(fwd, up):
    """Rotation matrix with columns (fwd, up, right), made orthonormal (fwd wins)."""
    f = Vector(fwd).normalized()
    u = Vector(up)
    u = (u - f * u.dot(f)).normalized()
    r = f.cross(u)                     # right-handed, so it is a true rotation (blends cleanly)
    return Matrix((f, u, r)).transposed()


class Hand:
    def __init__(self, root, page_w_cm, half_h):
        with bpy.data.libraries.load(ASSET, link=False) as (src, dst):
            dst.collections = ['MotionCraftHand']
        col = dst.collections[0]
        bpy.context.scene.collection.children.link(col)
        self.objects = list(col.objects)
        self.rig = next(o for o in self.objects if o.type == 'ARMATURE')
        self.info = json.loads(self.rig['motioncraft_hand'])
        self.pw = float(page_w_cm)
        self.s = 100.0 / self.pw                     # metres -> book units (1 unit = one page width)
        self.rig.parent = root
        self.rig.matrix_parent_inverse = Matrix.Identity(4)
        self.rig.location, self.rig.rotation_euler = (0, 0, 0), (0, 0, 0)
        self.rig.scale = (self.s, self.s, self.s)
        bpy.context.view_layer.update()              # builds the pose of the appended rig
        self.half_h = half_h
        b = self.rig.data.bones
        self.m0 = {n: b[n].matrix_local.copy() for n in ('upperarm_r', 'lowerarm_r', 'hand_r')}
        self.l_up = (b['upperarm_r'].head_local - b['upperarm_r'].tail_local).length
        self.l_lo = (b['lowerarm_r'].head_local - b['hand_r'].head_local).length
        self.shoulder = self.book_cm(SHOULDER_CM) / self.s          # armature space (metres)
        for pb in self.rig.pose.bones:
            pb.rotation_mode = 'QUATERNION'
        # the hand's own frame and pinch point, read from the bones themselves
        self.wrist0 = b['hand_r'].head_local.copy()
        fwd = (b['middle_01_r'].head_local - self.wrist0).normalized()
        side = b['index_01_r'].head_local - b['pinky_01_r'].head_local
        up = fwd.cross(side).normalized()
        self.rest_frame = _frame(fwd, up)
        self._fingers(1.0)
        bpy.context.view_layer.update()
        pbs = self.rig.pose.bones
        self.pinch0 = (pbs['thumb_03_r'].tail + pbs['index_03_r'].tail) / 2
        self._fingers(0.0)

    def book_cm(self, cm):
        """A point given in centimetres from the spine / bottom edge / table, in book units."""
        return Vector((cm[0] / self.pw, -self.half_h + cm[1] / self.pw, cm[2] / self.pw))

    def hide(self, hidden=True):
        for o in self.objects:
            o.hide_render = hidden
            o.hide_viewport = hidden

    # ---------------------------------------------------------------- posing
    def _ik(self, W):
        """(wrist, elbow) for a wanted wrist position: two-bone IK from the shoulder."""
        S = self.shoulder
        d_vec = W - S
        self.last_reach = d_vec.length / (self.l_up + self.l_lo)
        d = min(max(d_vec.length, abs(self.l_up - self.l_lo) * 1.01), (self.l_up + self.l_lo) * 0.995)
        dirv = d_vec.normalized()
        W = S + dirv * d
        a = (d * d + self.l_up ** 2 - self.l_lo ** 2) / (2 * d)
        h = math.sqrt(max(self.l_up ** 2 - a * a, 0.0))
        pole = Vector((1.0, -0.15, -0.45))                            # the elbow points out, a little down
        pole = (pole - dirv * pole.dot(dirv)).normalized()
        E = S + dirv * a + pole * h
        floor = ELBOW_ABOVE_CM / 100.0                                # metres above the table
        if E.z < floor:
            for k in range(1, 19):                                    # swing it up round the arm's line
                for sgn in (1, -1):
                    pq = Quaternion(dirv, sgn * math.radians(10 * k)) @ pole
                    e2 = S + dirv * a + pq * h
                    if e2.z >= floor:
                        return W, e2
        return W, E

    def apply(self, p):
        """p = (pinch point, fwd, up, pinch amount) in the book's own space."""
        point, fwd, up, amount = Vector(p[0]), Vector(p[1]), Vector(p[2]), float(p[3])
        Q = _frame(fwd, up) @ self.rest_frame.transposed()          # rest hand -> wanted hand
        P = point / self.s
        S = self.shoulder
        rest_fwd = self.rest_frame.col[0]
        for _ in range(4):        # keep the wrist's bend natural: turn the hand towards the forearm
            W, E = self._ik(P - Q @ (self.pinch0 - self.wrist0))
            ydir = (W - E).normalized()
            hf = Q @ rest_fwd
            bend = hf.angle(ydir)
            if bend <= math.radians(MAX_BEND) + 1e-4:
                break
            axis = hf.cross(ydir)
            if axis.length < 1e-6:
                break
            Q = Quaternion(axis.normalized(), bend - math.radians(MAX_BEND)).to_matrix() @ Q
        W, E = self._ik(P - Q @ (self.pinch0 - self.wrist0))
        pbs = self.rig.pose.bones
        # upper arm: shoulder -> elbow
        Mu0 = self.m0['upperarm_r']
        Ru = Mu0.col[1].xyz.normalized().rotation_difference((E - S).normalized()).to_matrix() @ Mu0.to_3x3()
        pbs['upperarm_r'].matrix = Matrix.Translation(S) @ Ru.to_4x4()
        bpy.context.view_layer.update()
        # forearm: elbow -> wrist, turned with the hand (the forearm does the turning, not the wrist)
        Ml0, Mh0 = self.m0['lowerarm_r'], self.m0['hand_r']
        ydir = (W - E).normalized()
        R2 = Ml0.col[1].xyz.normalized().rotation_difference(ydir).to_matrix() @ Ml0.to_3x3()
        H = Q @ Mh0.to_3x3()
        ideal = H @ (Ml0.to_3x3().inverted() @ Mh0.to_3x3()).inverted()   # the forearm if the wrist were straight
        x_now = R2.col[0]
        x_want = ideal.col[0] - ydir * ideal.col[0].dot(ydir)
        if x_want.length > 1e-6:
            x_want.normalize()
            ang = math.atan2(x_now.cross(x_want).dot(ydir), x_now.dot(x_want))
            R2 = Quaternion(ydir, ang).to_matrix() @ R2
        pbs['lowerarm_r'].matrix = Matrix.Translation(E) @ R2.to_4x4()
        bpy.context.view_layer.update()
        pbs['hand_r'].matrix = Matrix.Translation(W) @ H.to_4x4()
        bpy.context.view_layer.update()
        self._fingers(LOOSE + (1 - LOOSE) * amount)

    def _fingers(self, amount):
        """0 = relaxed open hand, 1 = pinching."""
        pbs = self.rig.pose.bones
        rel, pin = self.info['poses']['relaxed'], self.info['poses']['pinch']
        for f in FINGERS:
            for k in range(3):
                deg = rel[f][k] * (1 - amount) + pin[f][k] * amount
                pbs[f'{f}_0{k + 1}_r'].rotation_quaternion = Quaternion((1, 0, 0), math.radians(deg))

    # ---------------------------------------------------------------- planning
    def corner_pose(self, k, t, curve):
        """Where to pinch sheet k now (current geometry state), and how the hand is held there."""
        g = G.sheet_state(k, t, curve)
        ys = g[:, -1, 1]
        r = int(np.argmin(np.abs(ys - (ys.min() + GRAB_UP * (ys.max() - ys.min())))))
        r = min(max(r, 0), g.shape[0] - 2)
        corner = g[r, -1]
        e_in = g[r, -8] - corner
        e_in /= np.linalg.norm(e_in)
        e_edge = g[r + 1, -1] - corner
        e_edge /= np.linalg.norm(e_edge)
        n = np.cross(e_edge, e_in)
        n /= np.linalg.norm(n)
        point = corner + e_in * GRAB_IN
        e_in = np.cross(n, e_edge)              # square the frame (the page is curved)
        e_in /= np.linalg.norm(e_in)
        # the page's turn so far (from lying flat), of which the hand follows a part
        Rp = Matrix((e_in, e_edge, n)).transposed() @ Matrix(((-1, 0, 0), (0, 1, 0), (0, 0, 1))).transposed().inverted()
        follow = Quaternion().slerp(Rp.to_quaternion(), FOLLOW).to_matrix()
        # on a flat page: fingers point in over the page and up it, the back of the hand up
        fwd = follow @ Vector((-0.62, 0.62, -0.48))
        up = follow @ Vector((-0.15, 0.0, 1.0))
        return [tuple(point), tuple(fwd), tuple(up)]

    def rest_pose(self):
        p = self.book_cm(REST_CM)
        return [tuple(p), (-0.55, 0.65, -0.45), (0.15, -0.1, 1.0)]


def _blend(a, b, u, lift=0.0):
    """Between two (point, fwd, up) poses: smooth, with an arc over the page."""
    w = _smooth(u)
    pa, pb = np.array(a[0]), np.array(b[0])
    p = pa + (pb - pa) * w
    p[2] += lift * math.sin(math.pi * w)
    qa = _frame(a[1], a[2]).to_quaternion()
    qb = _frame(b[1], b[2]).to_quaternion()
    m = qa.slerp(qb, w).to_matrix()
    return [tuple(p), tuple(m.col[0]), tuple(m.col[1])]


def plan(hand, n_frames, fps, state_at):
    """The hand's pose for every frame: [(point, fwd, up, pinch amount)].
    state_at(f) sets the book's shape for frame f and returns (progress list, curve weights)."""
    lead, pinch, enter = (max(1, round(x * fps)) for x in (LEAD_S, PINCH_S, ENTER_S))
    progs = []
    for f in range(n_frames):
        ts, cw = state_at(f)
        progs.append((ts, cw))
    turns = []                      # (sheet, start frame, release frame)
    n_sheets = len(progs[0][0]) if progs else 0
    for k in range(n_sheets):
        series = [p[0][k] for p in progs]
        if series[0] >= 1.0 - 1e-6:
            continue                # already turned when the video starts
        start = next((f for f, t in enumerate(series) if t > 1e-4), None)
        if start is None:
            continue
        rel = next((f for f, t in enumerate(series) if t >= RELEASE), n_frames - 1)
        turns.append((k, start, rel))
    turns.sort(key=lambda x: x[1])
    # pages turning faster than a hand could take them (a fast flip) turn on their own
    kept = []
    for t in turns:
        if not kept or t[1] - lead - pinch >= kept[-1][2]:
            kept.append(t)
    turns = kept
    grip = {}                        # frame -> pose while holding a page
    for k, start, rel in turns:
        for f in range(max(0, start - lead), min(n_frames, rel + 1)):
            ts, cw = state_at(f)
            grip[f] = (k, hand.corner_pose(k, ts[k], cw[k]))
    rest = hand.rest_pose()
    out = []
    for f in range(n_frames):
        if f in grip:
            k, pose = grip[f]
            start = next(s for kk, s, _ in turns if kk == k)
            amount = _smooth((f - (start - lead) + pinch * 0.5) / pinch)
            out.append(pose + [amount])
            continue
        prev = [t for t in turns if t[2] < f]
        nxt = [t for t in turns if t[1] - lead > f]
        if not turns:
            out.append(rest + [0.0])
        elif not prev:                                   # coming in for the first page
            k, start, _ = nxt[0]
            arrive = max(0, start - lead)
            u = (f - (arrive - enter)) / enter
            out.append(_blend(rest, grip[arrive][1] if arrive in grip else rest, u, 0.25) +
                       [_smooth((u - 0.7) / 0.3)])
        elif not nxt:                                    # going back out after the last page
            k, _, rel = prev[-1]
            u = (f - rel) / enter
            out.append(_blend(grip[rel][1], rest, u, 0.25) + [1 - _smooth(u / 0.3)])
        else:                                            # from one page to the next
            _, _, rel = prev[-1]
            _, start, _ = nxt[0]
            arrive = start - lead
            span = max(1, arrive - rel)
            u = (f - rel) / span
            amount = max(1 - _smooth((f - rel) / pinch), _smooth((f - (arrive - pinch)) / pinch))
            out.append(_blend(grip[rel][1], grip[arrive][1], u, 0.18) + [amount])
    return out
