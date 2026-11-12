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
REST_CM = (46.0, -34.0, 6.0)        # where the hand waits before the first turn and after the last (low, front right)
GRAB_UP = 0.28                      # catch the edge this far up from the bottom (share of page height)
GRAB_IN = 0.012                     # ...and this far in from the fore-edge (share of page width)
STRAP_GRAB_IN = 0.03                # the strap's tongue is pinched this far in from its tip
STRAP_LET_GO = 0.65                 # ...and let go when it is this far undone (it falls open by itself)
COVER_GRAB_IN, COVER_GRAB_DOWN = 0.03, 0.12   # the cover is caught near its top fore-edge corner
GRIP_IN_DEG = 35.0                  # the fingers lie along the edge, turned this much in over the page
RELEASE = 0.97                      # (at the latest) let go at this turn progress
RELEASE_DEG = 118.0                 # let go once the page has turned this far (past upright)
LOOSE = 0.1                         # open fingers stay this much curled (0 = straight, 1 = pinch)
LEAD_S = 0.3                        # be at the edge this long before the page starts to move
PINCH_S = 0.15                      # time to close or open the fingers
PRESS_S = 0.25                      # time smoothing the turned page down
PRESS_ALONG, PRESS_UP = 0.6, 0.3    # where it smooths: share of the way from spine to edge, up the page
TRAVEL_LIFT = 0.16                  # moving between pages the hand rises this much (clears the book)
ENTER_S = 0.6                       # time to come in at the start, or go out at the end
ELBOW_ABOVE_CM = 6.0                # the elbow stays at least this high above the table
MAX_BEND = 85.0                     # degrees the wrist may bend away from the forearm's line
SKIN_TILE_M = 0.07                  # a skin/glove picture covers this many metres of hand
SLEEVE_TILE_M = 0.09                # a sleeve picture covers this many metres of sleeve
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
        # thumb -> index across the pinch: the page passes between them, thumb on its front
        self.pinch_axis0 = (pbs['index_03_r'].tail - pbs['thumb_03_r'].tail).normalized()
        self.pinch_gap = (pbs['index_03_r'].tail - pbs['thumb_03_r'].tail).length
        self._fingers(0.0)

    def set_look(self, skin=None, sleeve=None):
        """Swap the hand's and the sleeve's pictures (like a book's): skin = a picture wrapped
        over the hand (a glove's leather, a fabric, a skin), sleeve = a fabric repeated over it.
        None keeps the built-in look (bare hand from the photos, brown suede)."""
        for ob in self.objects:
            if ob.type != 'MESH' or not ob.data.materials:
                continue
            mat = ob.data.materials[0]
            if mat is None or not mat.node_tree:
                continue
            nt = mat.node_tree
            bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf is None:
                continue
            if ob.name.startswith('Sleeve') and sleeve and os.path.exists(sleeve):
                tex = self._picture(nt, sleeve, 'UV', SLEEVE_TILE_M)
                into = bsdf.inputs['Base Color'].links[0].from_node if bsdf.inputs['Base Color'].links else None
                if into is not None and into.type == 'MIX':
                    nt.links.new(tex.outputs['Color'], into.inputs[6])    # keeps the stitches' shading
                else:
                    nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
            elif not ob.name.startswith('Sleeve') and skin and os.path.exists(skin):
                tex = self._picture(nt, skin, 'BOX', SKIN_TILE_M)
                nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
                for link in list(bsdf.inputs['Roughness'].links):
                    nt.links.remove(link)
                bsdf.inputs['Roughness'].default_value = 0.5            # a glove: no nails, no skin glow
                bsdf.inputs['Subsurface Weight'].default_value = 0.0
                bsdf.inputs['Sheen Weight'].default_value = 0.2

    @staticmethod
    def _picture(nt, path, how, tile_m):
        """An image node repeating `path` every tile_m metres (UV in metres, or a box wrap)."""
        img = bpy.data.images.load(path, check_existing=True)
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = img
        mp = nt.nodes.new('ShaderNodeMapping')
        mp.inputs['Scale'].default_value = (1 / tile_m, 1 / tile_m, 1 / tile_m)
        if how == 'BOX':
            tc = nt.nodes.new('ShaderNodeTexCoord')
            nt.links.new(tc.outputs['Object'], mp.inputs['Vector'])
            tex.projection = 'BOX'
            tex.projection_blend = 0.3
        else:
            uv = nt.nodes.new('ShaderNodeUVMap')
            uv.uv_map = 'uv'
            nt.links.new(uv.outputs['UV'], mp.inputs['Vector'])
        nt.links.new(mp.outputs['Vector'], tex.inputs['Vector'])
        return tex

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
        if amount >= 0:
            self._fingers(LOOSE + (1 - LOOSE) * amount)
        else:
            self._fingers(amount)                  # an open, flat hand (smoothing a page)

    def _fingers(self, amount):
        """-1 = flat open hand, 0 = relaxed, 1 = pinching."""
        pbs = self.rig.pose.bones
        P = self.info['poses']
        rel, pin, flat = P['relaxed'], P['pinch'], P['flat']
        a, b, w = (rel, pin, amount) if amount >= 0 else (rel, flat, -amount)
        for f in FINGERS:
            for k in range(3):
                deg = a[f][k] * (1 - w) + b[f][k] * w
                pbs[f'{f}_0{k + 1}_r'].rotation_quaternion = Quaternion((1, 0, 0), math.radians(deg))

    # ---------------------------------------------------------------- planning
    def page_grip(self, k, t, curve):
        """(grab point, the page's frame there: in towards the spine, along the edge, front) now."""
        g = G.sheet_state(k, t, curve)
        ys = g[:, -1, 1]
        r = int(np.argmin(np.abs(ys - (ys.min() + GRAB_UP * (ys.max() - ys.min())))))
        r = min(max(r, 0), g.shape[0] - 2)
        edge = g[r, -1]
        e_in = g[r, -8] - edge
        e_in /= np.linalg.norm(e_in)
        e_edge = g[r + 1, -1] - edge
        e_edge /= np.linalg.norm(e_edge)
        n = np.cross(e_edge, e_in)
        n /= np.linalg.norm(n)
        e_in = np.cross(n, e_edge)              # square the frame (the page is curved)
        e_in /= np.linalg.norm(e_in)
        return edge + e_in * GRAB_IN, (e_in, e_edge, n)

    def cover_grip(self, theta):
        """(grab point, frame) on the front cover's top fore-edge corner, the cover open by theta."""
        pv = G.cover_pivot(theta)
        c, s_ = math.cos(-theta), math.sin(-theta)
        R = np.array(((c, 0, s_), (0, 1, 0), (-s_, 0, c)))
        local = np.array((G.WC - COVER_GRAB_IN * G.WC, G.HC / 2 - COVER_GRAB_DOWN * G.HC, G.TB * 0.5))
        point = np.array((pv[0], 0.0, pv[1])) + R @ local
        return point, (R @ np.array((-1.0, 0, 0)), R @ np.array((0, 1.0, 0)), R @ np.array((0, 0, 1.0)))

    def strap_grip(self, u):
        """(grab point, frame) at the tip of the journal strap's tongue, undone by u."""
        _, _, tip, along, outer = G.strap_points(u)
        return tip - along * STRAP_GRAB_IN, (-along, np.array((0.0, 1.0, 0.0)), outer)

    def cover_pose(self, theta, prev_turn=None):
        return self.grip_pose(*self.cover_grip(theta), prev_turn)

    def cover_press(self):
        """An open hand resting on the opened cover's lower part (on its pastedown)."""
        theta = math.pi
        pv = G.cover_pivot(theta)
        c, s_ = math.cos(-theta), math.sin(-theta)
        R = np.array(((c, 0, s_), (0, 1, 0), (-s_, 0, c)))
        local = np.array((G.WC * 0.6, -G.HC / 2 + PRESS_UP * G.HC, 0.0))
        p = np.array((pv[0], 0.0, pv[1])) + R @ local + np.array((0, 0, 0.012))
        return [tuple(p), HOLD_LEFT[1], HOLD_LEFT[2]]

    def carry_pose(self, k, t, curve, prev_turn=None):
        return self.grip_pose(*self.page_grip(k, t, curve), prev_turn)

    def grip_pose(self, point, frame, prev_turn=None):
        """Holding a page's (or the cover's) edge, at its own speed: the pinch point is fixed to
        it where it caught it, thumb on its front, index finger behind it. Around that pinch
        the hand may turn (as fingers do on paper) to keep the wrist comfortable.
        Returns (pose, turn angle used, how far it has turned 0..pi)."""
        e_in, e_edge, n = (Vector(v) for v in frame)
        a = -n                                                   # thumb (front) -> index (back)
        base = e_edge * math.cos(math.radians(GRIP_IN_DEG)) + e_in * math.sin(math.radians(GRIP_IN_DEG))
        rb = _basis(self.pinch_axis0, self.rest_frame.col[0]).transposed()
        best = None
        for deg in range(-150, 151, 10):
            f = Quaternion(a, math.radians(deg)) @ base
            R = _basis(a, f) @ rb
            bend = self._bend(Vector(point) / self.s, R)
            score = bend + 0.35 * abs(deg - (prev_turn if prev_turn is not None else 0))
            if best is None or score < best[0]:
                best = (score, deg, R)
        _, deg, R = best
        phi = float(np.clip(math.atan2(-n[0], n[2]), 0.0, math.pi))
        return [tuple(point), tuple(R @ self.rest_frame.col[0]), tuple(R @ self.rest_frame.col[1])], deg, phi

    def _bend(self, P, R):
        """Degrees the wrist would bend for the hand at rotation R with its pinch at P (metres)."""
        W, E = self._ik(P - R @ (self.pinch0 - self.wrist0))
        return math.degrees((R @ self.rest_frame.col[0]).angle((W - E).normalized()))

    def press_pose(self, k, curve):
        """Smoothing the turned page down: an open hand, palm down, on the lower part of the
        page where it has landed (worked out from the page lying on the left)."""
        g = G.sheet_state(k, 1.0, curve)
        ys = g[:, 0, 1]
        r = int(np.argmin(np.abs(ys - (ys.min() + PRESS_UP * (ys.max() - ys.min())))))
        c = int(g.shape[1] * PRESS_ALONG)
        p = g[r, c] + np.array((0.0, 0.0, 0.012))
        return [tuple(p), HOLD_LEFT[1], HOLD_LEFT[2]]

    def rest_pose(self):
        p = self.book_cm(REST_CM)
        return [tuple(p), (-0.7, 0.6, -0.2), (0.0, -0.1, 1.0)]


# how the hand is held (fwd = wrist to fingers, up = back of the hand), in the book's space
HOLD_RIGHT = [(0, 0, 0), (-0.55, 0.7, -0.45), (-0.1, 0.05, 1.0)]    # on the right page, palm down
HOLD_UP = [(0, 0, 0), (-0.1, 0.35, 0.93), (0.95, -0.25, 0.0)]       # page upright: thumb up, palm to the left
HOLD_LEFT = [(0, 0, 0), (-0.35, 0.85, -0.3), (0.0, 0.05, 1.0)]      # laying it down on the left, palm down


def _basis(a, f):
    """Rotation with columns (a, f made square to a, a x f)."""
    a = Vector(a).normalized()
    f = Vector(f)
    f = (f - a * f.dot(a)).normalized()
    return Matrix((a, f, a.cross(f))).transposed()


def _blend(a, b, u, lift=0.0, smooth=True):
    """Between two (point, fwd, up) poses, with an arc over the page."""
    w = _smooth(u) if smooth else min(1.0, max(0.0, u))
    pa, pb = np.array(a[0]), np.array(b[0])
    p = pa + (pb - pa) * w
    p[2] += lift * math.sin(math.pi * w)
    qa = _frame(a[1], a[2]).to_quaternion()
    qb = _frame(b[1], b[2]).to_quaternion()
    m = qa.slerp(qb, w).to_matrix()
    return [tuple(p), tuple(m.col[0]), tuple(m.col[1])]


def plan(hand, n_frames, fps, state_at, strap_u=None):
    """The hand's pose for every frame: [(point, fwd, up, pinch amount)].
    state_at(f) sets the book's shape for frame f and returns (progress list, curve weights).
    Per page (as in Red Dead Redemption 2's journal): slide in low to the page's edge, catch it,
    carry it all the way over turning with it, lay it down and smooth it, then go for the next."""
    lead, pinch, press, enter = (max(1, round(x * fps)) for x in (LEAD_S, PINCH_S, PRESS_S, ENTER_S))
    progs = [state_at(f) for f in range(n_frames)]
    thetas = [p[2] if len(p) > 2 else math.pi for p in progs]
    turns = []                      # (sheet, start frame, let-go frame)
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
    if strap_u and strap_u[0] < 1.0:                          # a journal's strap: undo it first
        s_start = next((f for f, u in enumerate(strap_u) if u > 1e-4), None)
        if s_start is not None:
            s_rel = next((f for f, u in enumerate(strap_u) if u >= STRAP_LET_GO), n_frames - 1)
            turns.append(('strap', s_start, s_rel))
    if thetas and thetas[0] < math.pi - 1e-3:                 # the book starts closed: open the cover first
        c_start = next((f for f, th in enumerate(thetas) if th > 1e-3), None)
        if c_start is not None:
            c_open = next((f for f, th in enumerate(thetas) if th >= math.radians(RELEASE_DEG)), n_frames - 1)
            turns.append(('cover', c_start, c_open))
    turns.sort(key=lambda x: x[1])
    # pages turning faster than a hand could take them (a fast flip) turn on their own
    kept = []
    for t in turns:
        if t[0] in ('strap', 'cover') or not kept or t[1] - lead - pinch >= kept[-1][2]:
            kept.append(t)
    turns = kept
    carry, lands = {}, {}
    for i, (k, start, rel) in enumerate(turns):
        prev = None
        for f in range(max(0, start - lead), min(n_frames, rel + 1)):
            ts, cw = state_at(f)[:2]
            if k == 'strap':
                pose, prev, phi = hand.grip_pose(*hand.strap_grip(strap_u[f]), prev)
                phi = 0.0                                        # let go by how far it is undone
            elif k == 'cover':
                pose, prev, phi = hand.cover_pose(thetas[f], prev)
            else:
                pose, prev, phi = hand.carry_pose(k, ts[k], cw[k], prev)
            carry[f] = pose
            if phi >= math.radians(RELEASE_DEG) and f >= start:
                rel = f                                          # past upright: let go
                break
        turns[i] = (k, start, rel)
        if k == 'strap':
            lands[k] = rel + 2
        elif k == 'cover':
            lands[k] = next((f for f, th in enumerate(thetas) if f > rel and th >= math.pi * 0.99), rel + press)
        else:
            series = [p[0][k] for p in progs]
            lands[k] = next((f for f, t in enumerate(series) if f > rel and t >= 0.985), rel + press)
    steps = []                      # per turn: arrive, let go, done smoothing, press pose
    for i, (k, start, rel) in enumerate(turns):
        arrive = max(0, start - lead)
        done = max(lands[k], rel + 2) + press
        if i + 1 < len(turns):
            nxt_arrive = max(0, turns[i + 1][1] - lead)
            done = max(rel + 1, min(done, nxt_arrive - max(2, pinch)))
        ts, cw = state_at(min(n_frames - 1, max(lands[k], rel + 2)))[:2]
        if k == 'strap':                                       # lift away from the strap as it falls
            pp = carry[rel]
            press_p = [(pp[0][0] + 0.05, pp[0][1], pp[0][2] + 0.12), pp[1], pp[2]]
        elif k == 'cover':
            press_p = hand.cover_press()
        else:
            press_p = hand.press_pose(k, cw[k])
        steps.append((arrive, start, rel, done, press_p, max(lands[k], rel + 2)))
    rest = hand.rest_pose()
    out = []
    for f in range(n_frames):
        if not steps:
            out.append(rest + [0.0])
            continue
        cur = next((s for s in steps if s[0] <= f <= s[3]), None)
        if cur:
            arrive, start, rel, done, press_p, land = cur
            if f <= rel:                                       # holding the page
                amount = _smooth((f - arrive + pinch * 0.5) / pinch)
                out.append(carry[f] + [amount])
            else:                                              # laying it down, open hand
                u = (f - rel) / max(1, land - rel)       # down with the page, then smooth it
                out.append(_blend(carry[rel], press_p, u) + [1 - 2 * _smooth(u * 1.5)])
            continue
        before = [s for s in steps if s[3] < f]
        after = [s for s in steps if s[0] > f]
        if not before:                                         # sliding in for the first page
            arrive = after[0][0]
            u = (f - (arrive - enter)) / enter
            out.append(_blend(rest, carry[arrive], u, TRAVEL_LIFT * 0.6) + [0.0])
        elif not after:                                        # going back out after the last
            done, press_p = before[-1][3], before[-1][4]
            u = (f - done) / enter
            out.append(_blend(press_p, rest, u, 0.03) + [-1 + _smooth(u * 2)])
        else:                                                  # back for the next page, low
            done, press_p = before[-1][3], before[-1][4]
            arrive = after[0][0]
            u = (f - done) / max(1, arrive - done)
            out.append(_blend(press_p, carry[arrive], u, TRAVEL_LIFT) + [-1 + _smooth(u * 2)])
    return out
