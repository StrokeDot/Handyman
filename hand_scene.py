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
LEFT_SHOULDER_CM = (-3.0, -30.0, 30.0)   # the left shoulder (the reader sits a little to the right)
REST_CM = (50.0, -5.0, 5.0)         # where the hand waits before the first turn and after the last (resting, front right)
GRAB_UP = 0.42                      # catch the edge this far up from the bottom (share of page height)
GRAB_IN = 0.012                     # ...and this far in from the fore-edge (share of page width)
STRAP_GRAB_IN = 0.03                # the strap's tongue is pinched this far in from its tip
STRAP_LET_GO = 0.65                 # ...and let go when it is this far undone (it falls open by itself)
COVER_GRAB_IN, COVER_GRAB_DOWN = 0.03, 0.12   # the cover is caught near its top fore-edge corner
GRIP_IN_DEG = 35.0                  # the fingers lie along the edge, turned this much in over the page
RELEASE = 0.97                      # (at the latest) let go at this turn progress
RELEASE_DEG = 108.0                 # let go once the page has turned this far (past upright)
LOOSE = 0.1                         # open fingers stay this much curled (0 = straight, 1 = pinch)
LEAD_S = 0.3                        # be at the edge this long before the page starts to move
PINCH_S = 0.15                      # time to close or open the fingers
PRESS_S = 0.25                      # time smoothing the turned page down
PRESS_ALONG, PRESS_UP = 0.6, 0.3    # where it smooths: share of the way from spine to edge, up the page
RIGHT_HOLD = (0.985, 0.3)           # between turns the right hand holds the book here (share of the page: from the spine, up)
RIGHT_FINGERS = -0.35               # ...its fingers nearly flat on the edge
RETURN_S = 0.45                     # after laying a page down it is back holding the book in this long
SLIDE_S = 0.3                       # ...and slides up the edge to the next page in this long
SLIDE_LIFT_CM = 0.6                 # ...barely lifting
FAST_BACK_S = 0.45                   # with less time than this between turns it goes straight across
BACK_LIFT_CM = 1.2                  # ...rising this much on the way (clear of the book's edges)
SKIM_CM = 0.8                       # coming back along the bottom it skims this far over the pages
BOTTOM_PATH = (0.45, 0.1, 0.55)     # ...over the left page this far from the spine, this far up, then the right page
BACK_FINGERS = -0.3                 # ...fingers relaxed and open
WITHDRAW_MIN_S = 0.9                # a pause at least this long: the hand goes back below the book and waits
WITHDRAW_TRAVEL_S = 0.45            # ...taking about this long each way
WAIT_CM = (0.62, -8.0, 2.5)         # where it waits: this share of the page's width from the spine, cm below the bottom edge, cm up
TRAVEL_LIFT_CM = 3.9                # moving between pages the hand rises this much and comes down onto the next
ENTER_S = 0.6                       # time to come in at the start, or go out at the end
ELBOW_ABOVE_CM = 6.0                # the elbow stays at least this high above the table
MAX_BEND = 85.0                     # degrees the wrist may bend away from the forearm's line
SKIN_TILE_M = 0.07                  # a skin/glove picture covers this many metres of hand
SLEEVE_TILE_M = 0.09                # a sleeve picture covers this many metres of sleeve
LAST_PHASES = []                    # what the hand is doing on each frame (for checks)
SIDES = {}                          # which side the thumb took for each thing held (for checks)
SIDE_INFO = {}                      # (side, mean bend, turn onto the page after) per thing (for checks)
PAD_DEPTH_M = 0.008                 # from the middle of a fingertip to its pad (the skin that touches)
PAD_GAP_CM = 0.3                    # finger pads rest this far above the paper
LAY_PAGE = (0.55, 0.58)              # laying a page down: the hand slides to here on it (along, up)
LAY_COVER = (0.55, 0.7)             # ...and on the cover
LEFT_HOLD = (0.88, 0.0)              # the left hand holds the open book here on the cover (along, up)
LEFT_SHOULDER_UNDER_CM = (-12.0, -26.0, -28.0)   # holding the book up from beneath: the left shoulder is below it
UNDER_X = (0.62, -0.38)             # ...its finger pads under this share of the page's width (closed book, open book)
UNDER_UP = 0.4                      # ...this share of the way up the book
UNDER_GAP_CM = 0.35                 # ...this far below the book's underside
UNDER_FINGERS = -0.6                # ...fingers nearly flat against it
LEFT_FINGERS = -0.5                 # the holding hand's fingers lie nearly flat on the book
LEFT_HOLD_CLOSED = (0.22, 0.035)    # ...and the closed book here, near the spine
HAND_LEN_CM = 28.0                  # fingertips to wrist and the bare forearm below the sleeve
HANDS_APART_CM = 9.0                # the left hand keeps about this far from the right one
GIVE_WAY_MAX_CM = 7.0               # if it would have to move further aside, it rests beside the book
BESIDE_CM = (6.0, 5.0)              # ...this far left of the open book, this far up from its bottom edge
HOVER_CM = (-4.0, -7.0, 4.0)        # while the cover opens it waits this far from where it will hold
LEFT_EASE_CM = 1.8                  # ...and eases up this much as a page lands on the left
JOIN_SMOOTH_S = 0.05                # seconds of smoothing over the joins between movements
LAY_FLIP_COST = 0.1                 # choosing the grip: a degree of turning over onto the page after ~ this much wrist bend
LAY_TILT = 0.4                      # laying a page down the fingers point this much into it (palm raised)
LET_GO_OUT_CM = 4.0                 # letting go, the thumb slips out this far past the page's edge
LET_GO_BACK_CM = 0.9                # ...while the hand drops this far behind the page
# (all distances in real centimetres: the hand is a real hand's size whatever the book's size)
SMOOTH_STROKE = (-0.1, -0.04)       # smoothing it: the hand then strokes this far (along, up)
PINCH_LIFT_CM = (1.2, 3.7)          # ...and only once its edge has risen this far (from .. to fully)
COVER_PINCH_LIFT_CM = (2.6, 5.2)    # ...the cover: higher, so the fingers going under it clear the pages
CATCH_DEG = 32.0                    # flat things are touched with the fingertips; pinched once lifted this far
MIN_TRAVEL_S = 0.35                  # the hand always has at least this long to go from one page to the next
MIN_LEAD_S = 0.12                   # ...and at least this long at the next edge before it moves
ANGLE_SMOOTH_FRAMES = 2.5           # the grip's turn is smoothed over this many frames (no jitter)
FINGER_DELAY = {'index': 0.0, 'thumb': 0.06, 'middle': 0.08, 'ring': 0.15, 'pinky': 0.22}
IDLE_CM = 0.18                      # a free hand drifts this much (alive, never perfectly still)
FINGERS = ('thumb', 'index', 'middle', 'ring', 'pinky')


def _smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _smoother(x):
    """Quintic ease: starts and stops with no jolt (zero speed and acceleration at both ends)."""
    x = min(1.0, max(0.0, x))
    return x * x * x * (x * (6 * x - 15) + 10)


def _frame(fwd, up):
    """Rotation matrix with columns (fwd, up, right), made orthonormal (fwd wins)."""
    f = Vector(fwd).normalized()
    u = Vector(up)
    u = (u - f * u.dot(f)).normalized()
    r = f.cross(u)                     # right-handed, so it is a true rotation (blends cleanly)
    return Matrix((f, u, r)).transposed()


class Hand:
    def __init__(self, root, page_w_cm, half_h, mirror=False, shoulder_cm=None, elbow_floor=True):
        """mirror=True makes it a left hand (the right hand mirrored, with its own shoulder).
        shoulder_cm: where the shoulder is instead (cm from the spine / bottom edge / table);
        elbow_floor=False lets the elbow go below the table (an arm holding the book up from beneath)."""
        self.mx = -1.0 if mirror else 1.0
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
        self.rig.scale = (self.mx * self.s, self.s, self.s)
        bpy.context.view_layer.update()              # builds the pose of the appended rig
        self.half_h = half_h
        b = self.rig.data.bones
        self.m0 = {n: b[n].matrix_local.copy() for n in ('upperarm_r', 'lowerarm_r', 'hand_r')}
        self.l_up = (b['upperarm_r'].head_local - b['upperarm_r'].tail_local).length
        self.l_lo = (b['lowerarm_r'].head_local - b['hand_r'].head_local).length
        self.shoulder = self.arm(self.book_cm(shoulder_cm or (LEFT_SHOULDER_CM if mirror else SHOULDER_CM)))   # metres
        self.elbow_floor = elbow_floor
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
        # a hand touches with its finger pads (index and middle fingertips, palm side): where they
        # are with the fingers flat and with them relaxed
        pads = {}
        for amt in (-1.0, 0.0):
            self._fingers(amt)
            bpy.context.view_layer.update()
            pads[amt] = (pbs['index_03_r'].tail + pbs['middle_03_r'].tail) / 2 - self.rest_frame.col[1] * PAD_DEPTH_M
        self.pad_flat, self.pad_rel = pads[-1.0], pads[0.0]
        self.pad0 = self.pad_flat
        self._fingers(0.0)
        if bpy.context.scene.render.engine != 'CYCLES':
            self._tone_for_fast_engine()

    def _tone_for_fast_engine(self):
        """EEVEE draws fabric sheen and a skin's oily layer much stronger than Cycles (the suede
        would look like satin): tone them down there."""
        for ob in self.objects:
            if ob.type != 'MESH' or not ob.data.materials or ob.data.materials[0] is None:
                continue
            nt = ob.data.materials[0].node_tree
            bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None) if nt else None
            if bsdf is None:
                continue
            if ob.name.startswith('Sleeve'):
                bsdf.inputs['Sheen Weight'].default_value = min(bsdf.inputs['Sheen Weight'].default_value, 0.12)
            else:
                bsdf.inputs['Coat Weight'].default_value = min(bsdf.inputs['Coat Weight'].default_value, 0.04)

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
                fabric = nt.nodes.get('FabricColour')          # keeps the stitches, nap, folds and wear
                into = bsdf.inputs['Base Color'].links[0].from_node if bsdf.inputs['Base Color'].links else None
                if fabric is not None:
                    nt.links.new(tex.outputs['Color'], fabric.inputs[6])
                elif into is not None and into.type == 'MIX':
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

    def arm(self, v):
        """A book-space point into the rig's own space (metres; mirrored for a left hand)."""
        return Vector((self.mx * v[0], v[1], v[2])) / self.s

    def arm_dir(self, v):
        return Vector((self.mx * v[0], v[1], v[2]))

    def natural_pose(self, point, up=(0.0, 0.0, 1.0), amount=0.0, anchor=1.0, pitches=(-35, -20, -5),
                     yaws=range(0, 360, 8)):
        """A resting pose at `point` (book space) with the back of the hand towards `up`: the
        direction that keeps the wrist straightest, searched (works for either hand); yaws limits
        which ways the fingers may point (degrees, 0 = +x, 90 = up the book)."""
        P = self.arm(point)
        pad = self.pad_rel.lerp(self.pad_flat, min(1.0, max(0.0, -amount)))
        ref = self.pinch0.lerp(pad, anchor)
        upv = Vector(up).normalized()
        best = None
        for yaw in yaws:
            for pitch in pitches:
                y, pt = math.radians(yaw), math.radians(pitch)
                fwd = Vector((math.cos(y), math.sin(y), 0.0)) * math.cos(pt) + upv * math.sin(pt)
                R = _frame(self.arm_dir(fwd), self.arm_dir(upv)) @ self.rest_frame.transposed()
                b = self._bend(P, R, ref)
                if best is None or b < best[0]:
                    best = (b, fwd)
        return [tuple(float(x) for x in point), tuple(best[1]), tuple(upv), float(amount), float(anchor)]

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
        if self.elbow_floor and E.z < floor:
            for k in range(1, 19):                                    # swing it up round the arm's line
                for sgn in (1, -1):
                    pq = Quaternion(dirv, sgn * math.radians(10 * k)) @ pole
                    e2 = S + dirv * a + pq * h
                    if e2.z >= floor:
                        return W, e2
        return W, E

    def apply(self, p):
        """p = (point, fwd, up, finger amount[, anchor]) in the book's own space. The point is where
        the pinch (between thumb and index tips) goes, or with anchor 1 where the finger pads go."""
        point, fwd, up, amount = Vector(p[0]), self.arm_dir(p[1]), self.arm_dir(p[2]), float(p[3])
        w_anchor = float(p[4]) if len(p) > 4 else 0.0
        pad = self.pad_rel.lerp(self.pad_flat, min(1.0, max(0.0, -amount)))
        ref = self.pinch0.lerp(pad, w_anchor)
        Q = _frame(fwd, up) @ self.rest_frame.transposed()          # rest hand -> wanted hand
        P = self.arm(point)
        S = self.shoulder
        rest_fwd = self.rest_frame.col[0]
        for _ in range(12):       # keep the wrist's bend natural: turn the hand towards the forearm
            W, E = self._ik(P - Q @ (ref - self.wrist0))
            ydir = (W - E).normalized()
            hf = Q @ rest_fwd
            bend = hf.angle(ydir)
            if bend <= math.radians(MAX_BEND) + 1e-4:
                break
            axis = hf.cross(ydir)
            if axis.length < 1e-6:
                break
            Q = Quaternion(axis.normalized(), 0.7 * (bend - math.radians(MAX_BEND)) + 1e-3).to_matrix() @ Q
        W, E = self._ik(P - Q @ (ref - self.wrist0))
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
        """-1 = flat open hand, 0 = relaxed, 1 = pinching. Each finger bends about its own true
        bending axis and swings sideways at its root (the fingers come together from the model's
        splayed rest pose)."""
        pbs = self.rig.pose.bones
        P = self.info['poses']
        axes, sp_axes = self.info.get('finger_axes'), self.info.get('spread_axes')
        rel, pin, flat = P['relaxed'], P['pinch'], P['flat']
        a, b, w = (rel, pin, amount) if amount >= 0 else (rel, flat, -amount)
        span = 1.0 + max(FINGER_DELAY.values())
        for f in FINGERS:
            wf = _smooth(w * span - FINGER_DELAY[f])           # one after another, eased
            for k in range(3):
                name = f'{f}_0{k + 1}_r'
                deg = a[f][k] * (1 - wf) + b[f][k] * wf
                q = Quaternion(axes[name] if axes else (1, 0, 0), math.radians(deg))
                if k == 0 and sp_axes and 'spread' in a:
                    sp = a['spread'][f] * (1 - wf) + b['spread'][f] * wf
                    q = Quaternion(sp_axes[name], math.radians(sp)) @ q
                pbs[name].rotation_quaternion = q

    # ---------------------------------------------------------------- where things are
    def page_at(self, k, t, curve, along, up):
        """A point on sheet k as it is now, at (along: 0 spine .. 1 fore-edge, up: 0 bottom .. 1
        top), and the page's frame there (towards the spine, up the page, its front). Smoothly
        interpolated, so a hand sliding over the page moves smoothly."""
        return _surface(G.sheet_state(k, t, curve), along, up)

    def cover_at(self, theta, along, up, z_share=0.5):
        """The same on the front cover, open by theta (z_share: 0 its inside face .. 1 outside)."""
        pv = G.cover_pivot(theta)
        c, s_ = math.cos(-theta), math.sin(-theta)
        R = np.array(((c, 0, s_), (0, 1, 0), (-s_, 0, c)))
        local = np.array((along * G.WC, -G.HC / 2 + up * G.HC, G.TB * z_share))
        point = np.array((pv[0], 0.0, pv[1])) + R @ local
        return point, (R @ np.array((-1.0, 0, 0)), R @ np.array((0, 1.0, 0)), R @ np.array((0, 0, 1.0)))

    def strap_grip(self, u):
        """(grab point, frame) at the tip of the journal strap's tongue, undone by u."""
        _, _, tip, along, outer = G.strap_points(u)
        # same handedness as a page's frame: front = along-the-edge x towards-inside
        return tip - along * STRAP_GRAB_IN, (-along, np.array((0.0, -1.0, 0.0)), outer)

    # ---------------------------------------------------------------- how the hand holds things
    def grip_rotation(self, frame, deg, side=1):
        """The hand's rotation pinching an edge with frame (towards inside, along the edge,
        front): thumb on the front, index finger behind, fingers along the edge turned in by
        GRIP_IN_DEG, then turned by `deg` round the pinch (as fingers turn on paper)."""
        e_in, e_edge, n = (Vector(v) for v in frame)
        a = -n * side                       # thumb -> index across it (side 1: thumb on its front)
        base = e_edge * math.cos(math.radians(GRIP_IN_DEG)) + e_in * math.sin(math.radians(GRIP_IN_DEG))
        f = Quaternion(a, math.radians(deg)) @ base
        return _basis(a, f) @ _basis(self.pinch_axis0, self.rest_frame.col[0]).transposed()

    def best_turn(self, point, frame, prev=None, side=1):
        """The turn round the pinch that keeps the wrist most natural (and close to the last one)."""
        P = Vector(point) / self.s
        p0 = 0.0 if prev is None else prev

        def score(d):
            return self._bend(P, self.grip_rotation(frame, d, side)) + 0.25 * abs(d - p0)
        best = min(range(-150, 151, 15), key=score)
        lo, hi = best - 15.0, best + 15.0                        # then exactly (golden section)
        g = (math.sqrt(5) - 1) / 2
        c, d = hi - g * (hi - lo), lo + g * (hi - lo)
        fc, fd = score(c), score(d)
        for _ in range(16):
            if fc < fd:
                hi, d, fd = d, c, fc
                c = hi - g * (hi - lo)
                fc = score(c)
            else:
                lo, c, fc = c, d, fd
                d = lo + g * (hi - lo)
                fd = score(d)
        return (lo + hi) / 2

    def turn_path(self, points, frames, side=1, step=5.0, turn_cost=1.2):
        """The best turns round the pinch for a whole hold at once (no sudden flips): every frame
        tries turns every `step` degrees, and the path keeping the wrist natural with the least
        turning wins (degrees of wrist bend + turn_cost x degrees turned). Then refined smoothly.
        Returns (turn per frame, mean wrist bend)."""
        states = np.arange(-180.0, 180.0, step)
        n = len(states)
        circ = np.abs(((states[:, None] - states[None, :]) + 180.0) % 360.0 - 180.0)
        cost = None
        back = []
        bends = []
        for pt, fr in zip(points, frames):
            P = Vector(pt) / self.s
            b = np.array([self._bend(P, self.grip_rotation(fr, d, side)) for d in states])
            bends.append(b)
            if cost is None:
                cost = b.copy()
                back.append(np.arange(n))
                continue
            tot = cost[None, :] + turn_cost * circ          # [to, from]
            arg = np.argmin(tot, axis=1)
            cost = tot[np.arange(n), arg] + b
            back.append(arg)
        j = int(np.argmin(cost))
        path = [j]
        for arg in reversed(back[1:]):
            j = int(arg[j])
            path.append(j)
        path.reverse()
        degs = np.unwrap(np.radians(states[path]))          # continuous, then smoothed
        degs = np.degrees(np.array(_smooth_series(list(degs), ANGLE_SMOOTH_FRAMES)))
        mean_bend = float(np.mean([bends[i][path[i]] for i in range(len(path))]))
        return list(degs), mean_bend

    def bend_at(self, point, frame, deg, side=1):
        return self._bend(Vector(point) / self.s, self.grip_rotation(frame, deg, side))

    def _bend(self, P, R, ref=None):
        """Degrees the wrist would bend for the hand at rotation R with its pinch at P (metres)."""
        ref = self.pinch0 if ref is None else ref
        W, E = self._ik(P - R @ (ref - self.wrist0))
        return math.degrees((R @ self.rest_frame.col[0]).angle((W - E).normalized()))

    def pose(self, point, R, amount, anchor):
        return [tuple(float(x) for x in point), tuple(R @ self.rest_frame.col[0]),
                tuple(R @ self.rest_frame.col[1]), float(amount), float(anchor)]

    def lay_rotation(self):
        """In a page's own frame (_fmat): the open hand lying on the page's back, palm on it,
        fingers up the page and a little out, pressing slightly into it."""
        fwd = Vector((-0.35, 0.85, -LAY_TILT)).normalized()
        return _frame(fwd, (0.0, 0.0, 1.0)) @ self.rest_frame.transposed()

    def catch_rotation(self, point, frame):
        """Fingertips resting on a thing's front near its edge, palm towards it, the fingers
        pointing the way the arm naturally reaches (how a flat page is first touched)."""
        n = Vector(tuple(map(float, frame[2])))
        reach = Vector(tuple(map(float, point))) - self.shoulder * self.s
        along = reach - n * reach.dot(n)
        fwd = along.normalized() - n * 0.6                      # fingertips down on it, palm raised
        return _frame(fwd, n) @ self.rest_frame.transposed()

    def rest_pose(self, where_cm=None):
        """Waiting off to the front right (or at where_cm): the hand in line with the forearm,
        palm down."""
        p = self.book_cm(where_cm or REST_CM)
        best = None
        for yaw in range(0, 360, 10):       # the direction that keeps the wrist straightest
            for pitch in (-25, -10, 0, 10):
                y, pt = math.radians(yaw), math.radians(pitch)
                fwd = Vector((math.cos(y) * math.cos(pt), math.sin(y) * math.cos(pt), math.sin(pt)))
                R = _frame(fwd, (0.0, 0.0, 1.0)) @ self.rest_frame.transposed()
                b = self._bend(p / self.s, R, self.pad0)
                if best is None or b < best[0]:
                    best = (b, R)
        return self.pose(p, best[1], 0.0, 1.0)


def _surface(g, along, up):
    """Bilinear point and frame on a sheet's grid (rows go up the page, columns from the spine to
    the fore-edge)."""
    nr, nc = g.shape[0], g.shape[1]
    c = min(max(along, 0.0), 1.0) * (nc - 1)
    c0 = min(int(math.floor(c)), nc - 2)
    fc = c - c0
    col = g[:, c0] * (1 - fc) + g[:, c0 + 1] * fc
    ys = col[:, 1]
    target = ys.min() + min(max(up, 0.0), 1.0) * (ys.max() - ys.min())
    r = float(np.interp(target, ys, np.arange(nr)))
    r0 = min(int(math.floor(r)), nr - 2)
    fr = r - r0
    point = col[r0] * (1 - fr) + col[r0 + 1] * fr
    d_row = col[r0 + 1] - col[r0]
    d_col = ((g[r0, c0 + 1] - g[r0, c0]) * (1 - fr) + (g[r0 + 1, c0 + 1] - g[r0 + 1, c0]) * fr)
    e_edge = d_row / np.linalg.norm(d_row)
    e_in = -d_col / np.linalg.norm(d_col)
    n = np.cross(e_edge, e_in)
    n /= np.linalg.norm(n)
    e_in = np.cross(n, e_edge)
    e_in /= np.linalg.norm(e_in)
    return point, (e_in, e_edge, n)


def _basis(a, f):
    """Rotation with columns (a, f made square to a, a x f)."""
    a = Vector(a).normalized()
    f = Vector(f)
    f = (f - a * f.dot(a)).normalized()
    return Matrix((a, f, a.cross(f))).transposed()


def _fmat(frame):
    """A thing's frame as a true rotation: (towards inside, along the edge, its back's normal)."""
    e_in, e_edge = Vector(tuple(map(float, frame[0]))), Vector(tuple(map(float, frame[1])))
    return Matrix((e_in, e_edge, e_in.cross(e_edge))).transposed()


def _slerp_m(Ra, Rb, w):
    return Ra.to_quaternion().slerp(Rb.to_quaternion(), w).to_matrix()


def _smooth_poses(poses, sigma):
    """Gaussian-smoothed copy of a pose sequence: point, finger amount and anchor smoothed; the
    pointing and back-of-hand directions smoothed and made square again."""
    if len(poses) < 3 or sigma <= 0:
        return poses
    cols = [np.array([p[i] for p in poses], dtype=float) for i in range(3)]
    sm = [np.stack([_smooth_series(list(c[:, a]), sigma) for a in range(3)], 1) for c in cols]
    am = _smooth_series([p[3] for p in poses], sigma)
    an = _smooth_series([p[4] for p in poses], sigma)
    out = []
    for i in range(len(poses)):
        f = sm[1][i] / np.linalg.norm(sm[1][i])
        u = sm[2][i] - f * (sm[2][i] @ f)
        u /= np.linalg.norm(u)
        out.append([tuple(sm[0][i]), tuple(f), tuple(u), float(am[i]), float(an[i])])
    return out


def _rot_deg(A, B):
    """The angle (degrees) of the rotation taking matrix A to matrix B."""
    M = np.array(A, dtype=float).T @ np.array(B, dtype=float)
    return math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(M) - 1.0) / 2.0))))


def _smooth_series(xs, sigma):
    """Gaussian-smoothed copy of a list of numbers (ends held)."""
    if len(xs) < 3 or sigma <= 0:
        return list(xs)
    r = int(math.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.concatenate([[xs[0]] * r, xs, [xs[-1]] * r])
    return list(np.convolve(pad, k, mode='valid'))


def _blend(a, b, u, lift=0.0):
    """Between two poses (point, fwd, up, amount, anchor): eased, with an arc over the book."""
    w = _smoother(u)
    pa, pb = np.array(a[0]), np.array(b[0])
    p = pa + (pb - pa) * w
    p[2] += lift * _smoother(u / 0.4) * (1 - _smoother((u - 0.6) / 0.4))  # up, over, down onto it
    m = _slerp_m(_frame(a[1], a[2]), _frame(b[1], b[2]), w)
    return [tuple(p), tuple(m.col[0]), tuple(m.col[1]), a[3] + (b[3] - a[3]) * w, a[4] + (b[4] - a[4]) * w]


def plan(hand, n_frames, fps, state_at, strap_u=None):
    """The hand's pose for every frame: [(point, fwd, up, finger amount, anchor)].
    state_at(f) sets the book's shape for frame f and returns (progress list, curve weights, cover
    angle). Per page (as in Red Dead Redemption 2's journal): come down onto the page's edge and
    touch it with the fingertips; as it lifts, close into a pinch (thumb in front, finger behind)
    and go wherever the page goes; past upright open the fingers and ride the page down, sliding
    onto its back palm down; smooth it; rise and go for the next. The same for the cover (and a
    journal's strap first). Time between pages is shared out so the hand never has to rush."""
    global LAST_PHASES
    cm = 1.0 / hand.pw                                           # one centimetre in book units
    PAD_GAP, LET_GO_OUT, LET_GO_BACK, TRAVEL_LIFT = (x * cm for x in (PAD_GAP_CM, LET_GO_OUT_CM, LET_GO_BACK_CM,
                                                                        TRAVEL_LIFT_CM))
    lead_full, pinch, press_full, enter = (max(1, round(x * fps)) for x in (LEAD_S, PINCH_S, PRESS_S, ENTER_S))
    min_travel, min_lead = max(2, round(MIN_TRAVEL_S * fps)), max(1, round(MIN_LEAD_S * fps))
    progs = [state_at(f) for f in range(n_frames)]
    thetas = [p[2] if len(p) > 2 else math.pi for p in progs]
    turns = []                      # (thing, start frame, latest let-go frame)
    n_sheets = len(progs[0][0]) if progs else 0
    for k in range(n_sheets):
        series = [p[0][k] for p in progs]
        if series[0] >= 1.0 - 1e-6:
            continue                # already turned when the video starts
        start = next((f for f, t in enumerate(series) if t > 1e-4), None)
        if start is None:
            continue
        turns.append((k, start, next((f for f, t in enumerate(series) if t >= RELEASE), n_frames - 1)))
    if strap_u and strap_u[0] < 1.0:                          # a journal's strap: undo it first
        s_start = next((f for f, u in enumerate(strap_u) if u > 1e-4), None)
        if s_start is not None:
            turns.append(('strap', s_start,
                          next((f for f, u in enumerate(strap_u) if u >= STRAP_LET_GO), n_frames - 1)))
    if thetas and thetas[0] < math.pi - 1e-3:                 # the book starts closed: open the cover
        c_start = next((f for f, th in enumerate(thetas) if th > 1e-3), None)
        if c_start is not None:
            turns.append(('cover', c_start, next((f for f, th in enumerate(thetas)
                                                  if th >= math.radians(RELEASE_DEG)), n_frames - 1)))
    turns.sort(key=lambda x: x[1])

    def where(k, f, along, up, z_share=0.5):
        """(point, frame, how far it has lifted) on thing k at frame f."""
        ts, cw = state_at(f)[:2]
        if k == 'strap':
            point, frame = hand.strap_grip(strap_u[f])
            return point, frame, G.strap_state(strap_u[f])[1]
        if k == 'cover':
            point, frame = hand.cover_at(thetas[f], along, up, z_share)
        else:
            point, frame = hand.page_at(k, ts[k], cw[k], along, up)
        n = frame[2]
        return point, frame, float(np.clip(math.atan2(-n[0], n[2]), 0.0, math.pi))

    def grab_of(k):
        return (1 - COVER_GRAB_IN, 1 - COVER_GRAB_DOWN) if k == 'cover' else (1 - GRAB_IN, GRAB_UP)

    # when each turn lets go (past upright)
    released = []
    for k, start, rel in turns:
        if k != 'strap':
            g = grab_of(k)
            rel = next((f for f in range(start, rel + 1)
                        if where(k, f, *g)[2] >= math.radians(RELEASE_DEG)), rel)
        released.append((k, start, rel))
    kept = []                       # pages faster than a hand could take them (a fast flip) turn alone
    for t in released:
        if t[0] in ('strap', 'cover') or not kept or t[1] - (kept[-1][2] + 1) >= min_lead + min_travel:
            kept.append(t)
    turns = kept
    # ... and when each lands
    info = []
    for k, start, rel in turns:
        if k == 'strap':
            land = rel
        elif k == 'cover':
            land = next((f for f, th in enumerate(thetas) if f > rel and th >= math.pi * 0.99), rel + press_full)
        else:
            series = [p[0][k] for p in progs]
            land = next((f for f, t in enumerate(series) if f > rel and t >= 0.985), rel + press_full)
        info.append(dict(k=k, start=start, rel=rel, land=min(n_frames - 1, max(land, rel + 2))))
    # share out the time between one turn's landing and the next turn's start
    for i, cur in enumerate(info):
        cur.setdefault('lead', lead_full)
        cur['lay_end'] = cur['land']
        cur['press'] = press_full if cur['k'] != 'strap' else max(4, round(0.3 * fps))
        if i + 1 < len(info):
            nxt = info[i + 1]
            gap = nxt['start'] - cur['land']
            room = gap - min_travel
            nxt['lead'] = int(min(lead_full, max(min_lead, room * 0.5)))
            cur['press'] = int(min(cur['press'], max(0, room - nxt['lead'])))
            short = min_travel + min_lead - gap
            if short > 0:                                        # no time: leave the falling page early
                cur['lay_end'] = max(cur['rel'] + 1, cur['land'] - short)
                cur['press'] = 0
                nxt['lead'] = min_lead
        cur['arrive'] = max(0, cur['start'] - cur['lead'])
        cur['done'] = min(n_frames - 1, cur['lay_end'] + cur['press'])

    seqs = []
    L_lay = hand.lay_rotation()
    for cur in info:
        k, arrive, start, rel = cur['k'], cur['arrive'], cur['start'], cur['rel']
        g = grab_of(k)
        frames, pts, frs, lift = [], [], [], []
        for f in range(arrive, rel + 1):
            point, frame, lifted = where(k, f, *g)
            frames.append(f)
            pts.append(point)
            frs.append(frame)
            lift.append(lifted)
        # thumb in front or behind, and the turn round the pinch: the most natural whole path
        # (and the one that, letting go, turns over onto the page's back without a flip of the hand)
        options = [(hand.turn_path(pts, frs, sd), sd) for sd in (1, -1)]
        flips = {sd: 0.0 for sd in (1, -1)}
        if k != 'strap':
            _, fr_land, _ = where(k, cur['land'], *(LAY_COVER if k == 'cover' else LAY_PAGE), 0.0)
            R_lay = _fmat(fr_land) @ hand.lay_rotation()
            flips = {sd: _rot_deg(hand.grip_rotation(frs[-1], a[-1], sd), R_lay) for (a, _), sd in options}
        SIDE_INFO[str(k)] = [(sd, round(b, 1), round(flips[sd], 1)) for (a, b), sd in options]
        (angles, _), side = min(options, key=lambda x: x[0][1] + LAY_FLIP_COST * flips[x[1]])
        cur['side'] = side
        SIDES[str(k)] = side
        catch_deg = CATCH_DEG * (1.8 if k == 'strap' else 1.0)
        seq, phases = {}, {}
        Fs = [_fmat(fr) for fr in frs]
        L_catches = [F.transposed() @ hand.catch_rotation(pts[j], frs[j]) for j, F in enumerate(Fs)]
        L_pinches = [F.transposed() @ hand.grip_rotation(frs[j], angles[j], side) for j, F in enumerate(Fs)]
        wcs, wc = [], 0.0
        z_rest = pts[0][2]
        for j in range(len(frames)):
            # close into the pinch once its edge is lifted enough for a finger to get under it
            # (real centimetres, whatever the book's size), and never in a snap
            lifted_cm = (pts[j][2] - z_rest) / cm
            target = _smooth(lift[j] / math.radians(catch_deg))
            if k != 'strap':                                     # (a strap's tongue is short: by angle only)
                lo, hi = COVER_PINCH_LIFT_CM if k == 'cover' else PINCH_LIFT_CM   # (a board is thick)
                target = min(target, _smooth((lifted_cm - lo) / (hi - lo)))
            wc = min(target, wc + 1.0 / max(1, round(0.25 * fps)))
            wcs.append(wc)
        if len(wcs) > 3:                                         # ease the closing in and out
            wcs = [0.0] + [min(1.0, max(0.0, x)) for x in _smooth_series(wcs, 0.06 * fps)[1:]]
        for j, f in enumerate(frames):                           # touch, then pinch and hold
            wc = wcs[j]
            R = Fs[j] @ _slerp_m(L_catches[j], L_pinches[j], wc)
            n = np.array(frs[j][2])
            touch = _smooth((f - arrive) / max(1, pinch))        # settling the fingertips on it
            pt = np.array(pts[j]) + n * PAD_GAP * (1 - wc)
            seq[f] = hand.pose(pt, R, 0.15 * touch * (1 - wc) + wc, 1 - wc)
            phases[f] = f'hold {k}'
        last = seq[rel]
        if k == 'strap':                                         # let go and lift away as it falls
            hover = [(last[0][0] + 0.75 * cm, last[0][1], last[0][2] + 2.1 * cm), last[1], last[2], 0.2, 0.0]
            for f in range(rel + 1, cur['done'] + 1):
                seq[f] = _blend(last, hover, (f - rel) / max(1, cur['done'] - rel))
                phases[f] = 'let go strap'
        else:
            lay = LAY_COVER if k == 'cover' else LAY_PAGE
            z0 = 0.5 if k == 'cover' else 0.0
            L0 = _slerp_m(L_catches[-1], L_pinches[-1], wcs[-1])   # as it let go
            wc0, a0, n0 = wcs[-1], last[3], last[4]
            land, lay_end = cur['land'], cur['lay_end']
            if lay_end < land:                                   # no time to lay it: let go and lift off,
                F0 = np.array(frs[-1][0])                        # the wrist easing straight as it goes
                p_end = np.array(last[0]) - F0 * LET_GO_OUT + np.array((0.0, 0.0, LET_GO_BACK * 1.5))
                easy = hand.natural_pose(p_end, amount=0.15, anchor=n0)
                half = _blend(last, easy, 0.5, 0.0)              # half way round; the trip on finishes it
                easy = [easy[0], half[1], half[2], easy[3], easy[4]]
                for f in range(rel + 1, lay_end + 1):
                    v = (f - rel) / max(1, lay_end - rel)
                    seq[f] = _blend(last, easy, v, 0.0)
                    phases[f] = f'let go {k}'
            for f in range(rel + 1, lay_end + 1 if lay_end == land else rel + 1):   # let go, then ride it down onto its back
                u = (f - rel) / (land - rel)
                w = _smooth(min(1.0, u * 1.8))
                su = _smooth((u - 0.25) / 0.75)                  # slides in over it once clear of it
                # the thumb (on the side the page falls towards) slips out past the edge first,
                # and the hand drops behind the page; then it comes onto the page's back
                out = LET_GO_OUT * _smooth(u / 0.25) * (1 - _smooth((u - 0.35) / 0.45))
                back = PAD_GAP * (w - (1 - wc0) * (1 - w)) + LET_GO_BACK * _smooth(u / 0.3) * (1 - _smooth((u - 0.5) / 0.5))
                pt, frame, _ = where(k, f, g[0] + (lay[0] - g[0]) * su, g[1] + (lay[1] - g[1]) * su, z0 * (1 - w))
                R = _fmat(frame) @ _slerp_m(L0, L_lay, w)
                n_, e_in_ = np.array(frame[2]), np.array(frame[0])
                seq[f] = hand.pose(np.array(pt) - n_ * back - e_in_ * out, R, a0 + (-1.0 - a0) * w, n0 + (1.0 - n0) * w)
                phases[f] = f'lay {k}'
            if lay_end == land:
                for f in range(land + 1, cur['done'] + 1):       # smooth it with a short stroke
                    v = _smooth((f - land) / max(1, cur['done'] - land))
                    pt, frame, _ = where(k, f, lay[0] + SMOOTH_STROKE[0] * v, lay[1] + SMOOTH_STROKE[1] * v, 0.0)
                    seq[f] = hand.pose(np.array(pt) - np.array(frame[2]) * PAD_GAP, _fmat(frame) @ L_lay, -1.0, 1.0)
                    phases[f] = f'smooth {k}'
        seqs.append((seq, phases))
    # ------------------------------------------------------------------ between the turns
    # As Arthur Morgan does: between turns the hand holds the book on the right (fingertips on
    # the right edge, low down, the hand off the page); to turn it slides up that edge to the
    # page; after laying the page down it comes back along the bottom of the book, from the left
    # page to the right one, and holds the book again. When turns come too fast for that, the
    # way back is cut short (straight to the next page along the bottom, or straight across).
    ret_n, slide_n = max(2, round(RETURN_S * fps)), max(2, round(SLIDE_S * fps))
    skim = SKIM_CM * cm
    hold_cache = {}

    def turned_count(f):
        return sum(1 for t in progs[f][0] if t >= 0.5)

    def flipping(f0, f1):
        """Does any page turn on its own (a fast flip) between frames f0 and f1?"""
        return any(0.0 < t < 1.0 for f in range(max(0, f0), min(n_frames, f1 + 1)) for t in progs[f][0])

    def hold_pose(f, away=False):
        """Holding the book's right side at frame f (away: just off it, clear of pages flipping)."""
        key = (thetas[f] < math.pi * 0.99, turned_count(f), away)
        if key in hold_cache:
            return hold_cache[key]
        if thetas[f] < math.pi * 0.99:                           # the closed book: on the cover
            pt, fr = hand.cover_at(0.0, RIGHT_HOLD[0], RIGHT_HOLD[1], 1.0)
        else:
            k = min(turned_count(f), n_sheets - 1)
            pt, fr, _ = where(k, f, RIGHT_HOLD[0], RIGHT_HOLD[1])
        p = np.array(pt) + np.array(fr[2]) * PAD_GAP
        if away:
            p = p + np.array((3.5, -1.0, 2.5)) * cm
        pose = hand.natural_pose(p, amount=RIGHT_FINGERS, anchor=1.0, yaws=range(95, 181, 5))
        hold_cache[key] = pose
        return pose

    def surface(k, f, along, up):
        """A point just over thing k (a turned page or the open cover, or the top page on the
        right) where the hand skims along the bottom of the book."""
        if k == 'cover':
            pt, fr, _ = where('cover', f, along, up, 0.0)
            return np.array(pt) - np.array(fr[2]) * skim
        pt, fr, _ = where(k, f, along, up)
        n = np.array(fr[2])
        return np.array(pt) + n * skim * (1.0 if n[2] > 0 else -1.0)

    skim_dir = np.array((-0.35, 0.9, -0.2))
    skim_dir /= np.linalg.norm(skim_dir)

    def skim_pose(point):
        upv = np.array((0.0, 0.0, 1.0)) - skim_dir * skim_dir[2]
        return [tuple(point), tuple(skim_dir), tuple(upv / np.linalg.norm(upv)), BACK_FINGERS, 1.0]

    def along_bottom(start, end, f0, f1, k_prev):
        """Poses from `start` (laying the page down on the left) to `end`, skimming along the
        bottom of the book: over the left page, over the right one, then to `end`."""
        k_right = min(turned_count(f0), n_sheets - 1)
        w1 = surface(k_prev, f0, BOTTOM_PATH[0], BOTTOM_PATH[1])
        w2 = surface(k_right, f0, BOTTOM_PATH[2], BOTTOM_PATH[1])
        keys = [start, skim_pose(w1), skim_pose(w2), end]
        pts = [np.array(k_[0]) for k_ in keys]
        ext = [2 * pts[0] - pts[1]] + pts + [2 * pts[-1] - pts[-2]]
        # time shared by distance, so the hand moves at an even pace along the whole way
        seg = np.array([max(1e-6, np.linalg.norm(pts[i + 1] - pts[i])) for i in range(len(pts) - 1)])
        cum = np.concatenate([[0.0], np.cumsum(seg)]) / seg.sum()
        out_ = []
        for f in range(f0 + 1, f1 + 1):
            u = _smoother((f - f0) / max(1, f1 - f0))
            i = min(int(np.searchsorted(cum, u, side='right')) - 1, len(keys) - 2)
            i = max(i, 0)
            t = (u - cum[i]) / max(1e-9, cum[i + 1] - cum[i])
            p0, p1, p2, p3 = ext[i], ext[i + 1], ext[i + 2], ext[i + 3]       # Catmull-Rom
            p = 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t +
                       (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)
            p = p + np.array((0.0, 0.0, BACK_LIFT_CM * cm * math.sin(math.pi * u)))   # clear of the edges
            m = _slerp_m(_frame(keys[i][1], keys[i][2]), _frame(keys[i + 1][1], keys[i + 1][2]), t)
            a_ = keys[i][3] + (keys[i + 1][3] - keys[i][3]) * t
            n_ = keys[i][4] + (keys[i + 1][4] - keys[i][4]) * t
            out_.append([tuple(p), tuple(m.col[0]), tuple(m.col[1]), a_, n_])
        return out_

    def slide_in(hold, arrive_pose, u):
        """From holding the right side, up along the edge to the page (low, no arc)."""
        return _blend(hold, arrive_pose, u, SLIDE_LIFT_CM * cm)

    by_item = []                                                 # (first frame, last frame, thing, seq)
    for cur, (seq, _) in zip(info, seqs):
        by_item.append((min(seq), max(seq), cur['k'], seq))
    out, LAST_PHASES = [None] * n_frames, [''] * n_frames
    for (a0_, b0_, _, seq), (_, phs) in zip(by_item, seqs):
        for f in range(a0_, b0_ + 1):
            if f in seq:
                out[f], LAST_PHASES[f] = seq[f], phs[f]
    if not by_item:
        for f in range(n_frames):
            out[f], LAST_PHASES[f] = hold_pose(f), 'hold'
    else:
        # before the first: holding the book, then sliding up to it
        a, seq = by_item[0][0], by_item[0][3]
        h = hold_pose(0, flipping(0, a))
        for f in range(0, a):
            u = (f - (a - slide_n)) / slide_n
            out[f] = slide_in(h, seq[a], u) if u > 0 else list(h)
            LAST_PHASES[f] = 'slide' if u > 0 else 'hold'
        # between two
        for (_, b, k_prev, sb), (a, _, _, sa) in zip(by_item, by_item[1:]):
            gap = a - b - 1
            if gap <= 0:
                continue
            if k_prev == 'strap' or gap < max(3, round(FAST_BACK_S * fps)):
                for f in range(b + 1, a):                        # too quick: straight across
                    out[f] = _blend(sb[b], sa[a], (f - b) / (a - b), TRAVEL_LIFT)
                    LAST_PHASES[f] = 'free'
            elif gap < ret_n + slide_n + 2:                      # straight to the next one, along the bottom
                for f, p in zip(range(b + 1, a), along_bottom(sb[b], sa[a], b, a, k_prev)):
                    out[f], LAST_PHASES[f] = p, 'back'
            else:                                                # back along the bottom, hold, slide up
                h = hold_pose(b + ret_n, flipping(b, a))
                for f, p in zip(range(b + 1, b + ret_n + 1), along_bottom(sb[b], h, b, b + ret_n, k_prev)):
                    out[f], LAST_PHASES[f] = p, 'back'
                for f in range(b + ret_n + 1, a):
                    u = (f - (a - slide_n)) / slide_n
                    out[f] = slide_in(h, sa[a], u) if u > 0 else list(h)
                    LAST_PHASES[f] = 'slide' if u > 0 else 'hold'
        # after the last: back along the bottom and hold the book
        _, b, k_prev, sb = by_item[-1]
        if b < n_frames - 1:
            if k_prev == 'strap':
                h = hold_pose(b)
                for f in range(b + 1, n_frames):
                    out[f], LAST_PHASES[f] = _blend(sb[b], h, (f - b) / ret_n), 'free'
            else:
                end = min(n_frames - 1, b + ret_n)
                h = hold_pose(end)
                for f, p in zip(range(b + 1, end + 1), along_bottom(sb[b], h, b, end, k_prev)):
                    out[f], LAST_PHASES[f] = p, 'back'
                for f in range(end + 1, n_frames):
                    out[f], LAST_PHASES[f] = list(h), 'hold'
        for f in range(n_frames):                                # (anything missed: hold)
            if out[f] is None:
                out[f], LAST_PHASES[f] = hold_pose(f), 'hold'
    # no corners: where one movement hands over to the next (taking hold, letting go, setting
    # off) the speed and the turning carry on smoothly instead of starting or stopping dead
    out = _smooth_poses(out, JOIN_SMOOTH_S * fps)
    # a free hand is never perfectly still: a slow, tiny drift (not while it touches the book)
    free = np.array([1.0 if ph in ('free', 'hold') else 0.0 for ph in LAST_PHASES])
    if len(free) > 3:
        free = np.array(_smooth_series(list(free), 0.15 * fps)) * free
    amp = IDLE_CM / hand.pw
    for f in range(n_frames):
        if free[f] > 0:
            t = f / fps
            d = np.array((math.sin(2.1 * t + 0.3), math.sin(1.7 * t + 1.9), 0.6 * math.sin(2.6 * t + 4.0)))
            out[f] = [tuple(np.array(out[f][0]) + d * amp * free[f])] + list(out[f][1:])
    return out


def _seg_dist(p1, q1, p2, q2):
    """Closest points (and distance) between segments p1-q1 and p2-q2."""
    d1, d2, r = q1 - p1, q2 - p2, p1 - p2
    a, e, f = d1 @ d1, d2 @ d2, d2 @ r
    c, b = d1 @ r, d1 @ d2
    den = a * e - b * b
    s_ = min(1.0, max(0.0, (b * f - c * e) / den)) if den > 1e-12 else 0.0
    t = (b * s_ + f) / e if e > 1e-12 else 0.0
    if t < 0:
        t, s_ = 0.0, min(1.0, max(0.0, -c / a)) if a > 1e-12 else 0.0
    elif t > 1:
        t, s_ = 1.0, min(1.0, max(0.0, (b - c) / a)) if a > 1e-12 else 0.0
    c1, c2 = p1 + d1 * s_, p2 + d2 * t
    return c1, c2, float(np.linalg.norm(c1 - c2))


def plan_left_under(hand, n_frames, thetas):
    """The left hand holding the book up from beneath, like Arthur Morgan with his journal: palm
    up under the book, fingers spread under it - under the closed book's middle, sliding over
    under the spine and the left half as the cover opens. (The arm comes up from below.)"""
    cm = 1.0 / hand.pw

    def under(x_share):
        pt = np.array((x_share, -hand.half_h + UNDER_UP * 2 * hand.half_h, -UNDER_GAP_CM * cm))
        return hand.natural_pose(pt, up=(0.0, 0.0, -1.0), amount=UNDER_FINGERS, anchor=1.0)

    closed, opened = under(UNDER_X[0]), under(UNDER_X[1])
    return [_blend(closed, opened, th / math.pi, 0.0) for th in thetas]


def plan_left(hand, n_frames, fps, state_at, right_plan=None, style='on'):
    """The left hand (a mirrored Hand) holds the book, like Arthur's: while the book is closed its
    fingertips rest on the front cover's bottom margin near the spine (steadying it while the
    strap is undone); as the cover opens it moves off and waits just below the book; once the
    cover has landed it holds the open book by the cover's bottom-left corner, below the pages (so
    turned pages never land on it). Always a little alive, never frozen.
    style='under': it holds the book up from beneath instead (plan_left_under)."""
    cm = 1.0 / hand.pw
    PAD_GAP, LEFT_EASE = PAD_GAP_CM * cm, LEFT_EASE_CM * cm
    states = [state_at(f) for f in range(n_frames)]
    thetas = [st[2] for st in states]
    if style == 'under':
        return plan_left_under(hand, n_frames, thetas)
    lands = []                                                   # when each turned page lands
    for k in range(len(states[0][0]) if states else 0):
        series = [st[0][k] for st in states]
        if series[0] < 0.985:
            f_land = next((f for f, t in enumerate(series) if t >= 0.985), None)
            if f_land is not None:
                lands.append(f_land)
    open_pt, open_fr = hand.cover_at(math.pi, LEFT_HOLD[0], LEFT_HOLD[1], 0.0)
    hold_open = hand.natural_pose(np.array(open_pt) - np.array(open_fr[2]) * PAD_GAP, amount=LEFT_FINGERS)
    # on a small book the two hands cannot both be on it: the left one rests on the table beside it
    beside = hand.natural_pose(hand.book_cm((-hand.pw - BESIDE_CM[0], BESIDE_CM[1], 0.15)), amount=0.3)
    starts_closed = bool(n_frames) and thetas[0] < math.pi - 1e-3
    if starts_closed:
        c_pt, c_fr = hand.cover_at(0.0, LEFT_HOLD_CLOSED[0], LEFT_HOLD_CLOSED[1], 1.0)
        hold_closed = hand.natural_pose(np.array(c_pt) + np.array(c_fr[2]) * PAD_GAP, amount=LEFT_FINGERS)
        hp = np.array(hold_open[0]) + np.array(HOVER_CM) * cm   # aside, by where it will hold
        hover = hand.natural_pose(hp, amount=0.2, anchor=1.0)
        c_start = next((f for f, th in enumerate(thetas) if th > 1e-3), 0)
        land = next((f for f, th in enumerate(thetas) if th >= math.pi * 0.99), n_frames - 1)
        # it lets go just after the strap is undone and is clear to the left before the cover,
        # coming over, reaches the upright
        t1 = c_start - round(0.35 * fps)
        t2 = next((f for f, th in enumerate(thetas) if th > math.radians(70)), c_start + round(0.5 * fps))
        t2 = max(t2, t1 + round(0.6 * fps))
        t3, t4 = land, land + round(0.45 * fps)
        global LAST_LEFT_T
        LAST_LEFT_T = (c_start, t1, t2, t3, t4)

    def apart(f, pose):
        """Distance between the right hand (as planned) and the left one at `pose`, frame f."""
        reach = HAND_LEN_CM * cm
        ra, la = np.array(right_plan[f][0]), np.array(pose[0])
        rb = ra - np.array(right_plan[f][1]) / np.linalg.norm(right_plan[f][1]) * reach
        lb = la - np.array(pose[1]) / np.linalg.norm(pose[1]) * reach
        return _seg_dist(la, lb, ra, rb)[2]

    if starts_closed and right_plan:
        # it settles on the open cover only once the right hand has let go of it and moved away
        dur = t4 - t3
        while t3 < n_frames - 1 and any(apart(f, hold_open) < HANDS_APART_CM * cm
                                         for f in range(t3, min(n_frames, t3 + dur))):
            t3 += 1
        t4 = t3 + dur
        LAST_LEFT_T = (c_start, t1, t2, t3, t4)

    def timeline(small):
        out = [list(beside if small else hold_open) for _ in range(n_frames)]
        if starts_closed:
            for f in range(n_frames):
                if f < t1:
                    out[f] = list(hold_closed)
                elif small:                                      # straight off to the table
                    out[f] = _blend(hold_closed, beside, (f - t1) / max(1, round(0.7 * fps)), 0.05)
                elif f < t2:
                    out[f] = _blend(hold_closed, hover, (f - t1) / max(1, t2 - t1), 0.12)
                elif f < t3:
                    out[f] = list(hover)
                elif f < t4:
                    out[f] = _blend(hover, hold_open, (f - t3) / max(1, t4 - t3), 0.08)
        if small:
            return out
        # as a page comes down on the left, the holding hand eases up and settles again
        rise = round(0.35 * fps)
        for f_land in lands:
            mid = f_land - round(0.2 * fps)                      # its bottom corner comes down first
            for f in range(max(0, mid - rise), min(n_frames, mid + rise)):
                b = math.sin(math.pi * (f - (mid - rise)) / (2 * rise)) ** 2
                out[f] = [tuple(np.array(out[f][0]) + np.array((0.0, -0.75 * cm, LEFT_EASE)) * b)] + list(out[f][1:])
        return out

    def give_way(out):
        """How far the left hand moves aside, per frame, when the right hand comes near (each hand
        ~ fingertips to the bare forearm). A few passes, each checking the hands where the last pass
        left them; every push is held a little before and after (so it is fully there when
        needed) and then smoothed."""
        reach = HAND_LEN_CM * cm
        hold = round(0.15 * fps)
        total = np.zeros((n_frames, 3))
        for _ in range(4):
            push = np.zeros((n_frames, 3))
            for f in range(n_frames):
                ra = np.array(right_plan[f][0])
                la = np.array(out[f][0]) + total[f]
                rb = ra - np.array(right_plan[f][1]) / np.linalg.norm(right_plan[f][1]) * reach
                lb = la - np.array(out[f][1]) / np.linalg.norm(out[f][1]) * reach
                cl, cr, dist = _seg_dist(la, lb, ra, rb)
                need = HANDS_APART_CM * cm - dist
                if need > 0:
                    away = cl - cr
                    away[2] = 0.0
                    nrm = np.linalg.norm(away)
                    away = away / nrm if nrm > 1e-9 else np.array((-0.7, -0.7, 0.0))
                    push[f] = away * need * 1.15 + np.array((0.0, 0.0, need * 0.35))
            if not push.any():
                break
            held = np.zeros_like(push)                           # the largest push nearby, per frame
            for f in range(n_frames):
                win = push[max(0, f - hold):f + hold + 1]
                held[f] = win[np.argmax(np.linalg.norm(win, axis=1))]
            for ax in range(3):
                held[:, ax] = _smooth_series(list(held[:, ax]), 0.1 * fps)
            total += held
        return total

    out = timeline(False)
    global LAST_TOTAL, LAST_SMALL
    LAST_TOTAL, LAST_SMALL = [], False
    if right_plan:
        total = give_way(out)
        global LAST_HOLD_PUSH
        LAST_HOLD_PUSH = [float(np.linalg.norm(p)) for p in total]
        if np.linalg.norm(total, axis=1).max() > GIVE_WAY_MAX_CM * cm:
            out, LAST_SMALL = timeline(True), True
            total = give_way(out)
        LAST_TOTAL = [float(np.linalg.norm(p)) for p in total]
        for f in range(n_frames):
            if total[f].any():
                out[f] = [tuple(np.array(out[f][0]) + total[f])] + list(out[f][1:])
    # alive: a slow drift, smaller while touching the book
    amp = IDLE_CM / hand.pw
    for f in range(n_frames):
        t = f / fps
        d = np.array((math.sin(1.3 * t + 2.2), math.sin(1.9 * t + 0.7), 0.4 * math.sin(2.3 * t + 1.1)))
        touching = abs(out[f][4] - 1.0) < 1e-6 and out[f][3] <= 0.0 + 1e-6
        k = 0.25 if touching else 0.8
        if touching:
            d[2] = abs(d[2]) * 0.3                               # never into the cover
        out[f] = [tuple(np.array(out[f][0]) + d * amp * k)] + list(out[f][1:])
    return out
