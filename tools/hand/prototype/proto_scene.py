"""Phase 2 - an isolated page-turn prototype: the existing hand, sleeve and rig, and one turning page.

    python3 proto_scene.py -- out_dir [--save scene.blend]

Everything follows ONE progress value p (0..1) of a forward page turn, a pure function of p (so
scrubbing either way gives the same pose):
  - the page: hinged at the spine, turning with a soft lag towards its free edge (a lightly curled
    sheet, not a stiff board);
  - the contact: the pinch point (between the thumb and index tips) is held on a fixed spot of the
    page (page-relative - it cannot slip), the thumb on the page's front;
  - the arm: Blender's own two-bone IK (constraint on lowerarm_r, chain 2) to a wrist target, with an
    elbow pole out to the side and down (the forearm comes in from the lower right);
  - the hand: its rotation copied from an aim object; the aim is chosen, about the pinch axis, so the
    wrist stays as close as possible to the forearm's line (a real wrist), never turning with the
    page more than holding it requires; chosen once on a fixed grid of p and interpolated.
No cloth simulation: the sleeve deforms with the bones (corrective shapes come next, see SCENE_STATE).
Writes checkpoint renders (first-person and a close-up of the fingertips and cuff) and checks.json.
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

ASSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'resources', 'hand', 'hand.blend')
PW, PH = 0.15, 0.21                  # page width, height (m)
Z0 = 0.012                           # the page lies this high (on the rest of the block)
SHOULDER = Vector((0.32, -0.32, 0.05))
POLE = Vector((0.75, -0.3, -0.6)).normalized()   # which way the elbow points
GRIP = (0.95, 0.16)                  # the pinch on the page: share of its width from the spine, share up
REST = (1.0, 0.2)                    # resting: on the page's edge here (page flat)
STAND_ALONG = 0.5                    # with the page standing up the pinch is this far out from the spine
MAX_SLANT = 60                       # degrees the thumb->index line may slant from straight through the page
VIEW_UP = Vector((0.0, -0.45, 1.0)).normalized()   # towards the reader's eyes (up and towards him)
RETURN_AT = 0.88                     # after letting go, back to resting from here
LAG = 0.35                           # the page's free edge lags this much behind its hinge (curl)
WRIST_SOFT = 25.0                    # degrees: the wrist's comfortable bend
FINGERS_HOLD = 0.55                  # finger closure while holding (0 relaxed .. 1 pinched)


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


# ---------------------------------------------------------------- timeline of p
def phase(p):
    """(page angle, contact weight, release, fingers) for progress p."""
    reach = ease(p / 0.12)                                  # 0 .. 0.12: from resting to the grip
    theta = math.pi * 0.985 * ease((p - 0.12) / 0.72)       # 0.12 .. 0.84: the page turns
    let_go = ease((p - 0.78) / 0.12)                        # 0.78 .. 0.90: let go
    fingers = FINGERS_HOLD * (1 - let_go) + 0.1 * let_go
    return theta, reach, let_go, fingers


# ---------------------------------------------------------------- the page
def page_point(a, u, theta):
    """Point and frame (towards the spine, up the page, front normal) at (a, u) of the turning page."""
    n = 24
    x = z = 0.0
    phi = theta
    for i in range(n):                                       # integrate along the width
        t = (i + 0.5) / n
        if t > a:
            break
        phi = theta - LAG * math.sin(theta) * t
        step = min(1.0 / n, a - i / n)
        x += math.cos(phi) * step * PW
        z += math.sin(phi) * step * PW
    phi = theta - LAG * math.sin(theta) * a
    pt = Vector((x, -PH / 2 + u * PH, Z0 + z))
    e_in = Vector((-math.cos(phi), 0.0, -math.sin(phi)))
    nrm = Vector((-math.sin(phi), 0.0, math.cos(phi)))
    return pt, (e_in, Vector((0.0, 1.0, 0.0)), nrm)


def make_page():
    me = bpy.data.meshes.new('Page')
    ob = bpy.data.objects.new('Page', me)
    bpy.context.scene.collection.objects.link(ob)
    na, nu = 24, 16
    verts = [(0, 0, 0)] * ((na + 1) * (nu + 1))
    faces = [(i * (nu + 1) + j, (i + 1) * (nu + 1) + j, (i + 1) * (nu + 1) + j + 1, i * (nu + 1) + j + 1)
             for i in range(na) for j in range(nu)]
    me.from_pydata(verts, [], faces)
    mat = bpy.data.materials.new('paper')
    mat.diffuse_color = (0.93, 0.88, 0.76, 1)
    me.materials.append(mat)
    ob['grid'] = (na, nu)
    for side, x0 in (('LeftPage', -PW), ('UnderPage', 0.0)):          # (context: the rest of the spread)
        bpy.ops.mesh.primitive_plane_add(size=1, location=(x0 + PW / 2, 0, Z0 - 0.001))
        o = bpy.context.active_object
        o.name = side
        o.scale = (PW, PH, 1)
        o.data.materials.append(mat)
    return ob


def set_page(ob, theta):
    na, nu = ob['grid']
    co = []
    for i in range(na + 1):
        for j in range(nu + 1):
            co.extend(page_point(i / na, j / nu, theta)[0])
    ob.data.vertices.foreach_set('co', co)
    ob.data.update()


# ---------------------------------------------------------------- the arm and hand
class Arm:
    def __init__(self):
        with bpy.data.libraries.load(ASSET) as (src, dst):
            dst.objects = [n for n in src.objects]
        for o in dst.objects:
            bpy.context.scene.collection.objects.link(o)
        self.rig = bpy.data.objects['HandRig']
        self.skin = bpy.data.objects['Hand']
        self.sleeve = bpy.data.objects['Sleeve']
        self.info = json.loads(self.rig['motioncraft_hand'])
        rig = self.rig
        rig.location = SHOULDER - (rig.matrix_world @ rig.data.bones['upperarm_r'].head_local - rig.location)
        bpy.context.view_layer.update()
        pb = rig.pose.bones
        for b in pb:
            b.rotation_mode = 'QUATERNION'
        B = rig.data.bones
        Mw = rig.matrix_world
        self.l_up = (B['lowerarm_r'].head_local - B['upperarm_r'].head_local).length * rig.scale[0]
        self.l_lo = (B['hand_r'].head_local - B['lowerarm_r'].head_local).length * rig.scale[0]
        self.S = Mw @ B['upperarm_r'].head_local
        # targets
        self.wrist_t = bpy.data.objects.new('WristTarget', None)
        self.pole_t = bpy.data.objects.new('ElbowPole', None)
        self.aim = bpy.data.objects.new('HandAim', None)
        for o in (self.wrist_t, self.pole_t, self.aim):
            bpy.context.scene.collection.objects.link(o)
            o.empty_display_size = 0.02
        self.aim.rotation_mode = 'QUATERNION'
        ik = pb['lowerarm_r'].constraints.new('IK')
        ik.target, ik.pole_target, ik.chain_count = self.wrist_t, self.pole_t, 2
        ik.pole_angle = math.radians(-90)
        cr = pb['hand_r'].constraints.new('COPY_ROTATION')
        cr.target = self.aim
        self.ik = ik
        # the pinch point and the hand's forward axis, in the hand bone's own frame, fingers half closed
        self.fingers(FINGERS_HOLD)
        bpy.context.view_layer.update()
        Mh = pb['hand_r'].matrix
        tip = (pb['thumb_03_r'].tail + pb['index_03_r'].tail) / 2
        self.pinch_local = Mh.inverted() @ tip                 # (hand bone space)
        dg = bpy.context.evaluated_depsgraph_get()
        ev = self.skin.evaluated_get(dg)
        me = ev.to_mesh()
        gname = {g.index: g.name for g in self.skin.vertex_groups}
        Mhw_inv = (Mw @ Mh).inverted()
        pts, thumb = [], []
        for v in list(me.vertices)[::3]:
            src = self.skin.data.vertices[v.index]
            if not src.groups:
                continue
            g = gname[max(src.groups, key=lambda x: x.weight).group]
            if g.startswith(('hand', 'thumb', 'index', 'middle', 'ring', 'pinky')):
                pts.append((Mhw_inv @ (self.skin.matrix_world @ v.co))[:])
                thumb.append(g.startswith('thumb'))
        ev.to_mesh_clear()
        self.hand_pts = np.array(pts) - np.array(self.pinch_local[:])   # (relative to the pinch)
        self.hand_thumb = np.array(thumb)
        self.rest_hand = Mw.to_3x3() @ B['hand_r'].matrix_local.to_3x3()
        gname = {g.index: g.name for g in self.skin.vertex_groups}
        self.thumb_verts = np.array([bool(v.groups) and gname[max(v.groups, key=lambda g: g.weight).group].startswith('thumb')
                                     for v in self.skin.data.vertices])

    def fingers(self, amount):
        P, axes, sp = self.info['poses'], self.info.get('finger_axes'), self.info.get('spread_axes')
        a, b = P['relaxed'], P['pinch']
        pb = self.rig.pose.bones
        for f in ('thumb', 'index', 'middle', 'ring', 'pinky'):
            for k in range(3):
                n = f'{f}_0{k + 1}_r'
                deg = a[f][k] * (1 - amount) + b[f][k] * amount
                q = Quaternion(axes[n] if axes else (1, 0, 0), math.radians(deg))
                if k == 0 and sp and 'spread' in a:
                    q = Quaternion(sp[n], math.radians(a['spread'][f] * (1 - amount) + b['spread'][f] * amount)) @ q
                pb[n].rotation_quaternion = q

    def elbow(self, W):
        d = W - self.S
        L = min(max(d.length, 1e-4), (self.l_up + self.l_lo) * 0.999)
        dirv = d.normalized()
        a = (L * L + self.l_up ** 2 - self.l_lo ** 2) / (2 * L)
        h = math.sqrt(max(self.l_up ** 2 - a * a, 0.0))
        pole = (POLE - dirv * POLE.dot(dirv)).normalized()
        return self.S + dirv * a + pole * h

    def hand_world(self, R_bone):
        """World rotation of the hand bone (3x3) -> the pinch's offset from the wrist (world)."""
        return R_bone @ self.pinch_local

    def crossing(self, R, fr, along, up):
        """How many points of the hand would be on the wrong side of the page (the thumb behind it,
        the rest in front) for the hand at rotation R with its pinch on the page at (along, up)."""
        O = self.hand_pts @ np.array(R).T
        e_in, e_up, nrm = (np.array(x[:]) for x in fr)
        sd, ein, eup = O @ nrm, O @ e_in, O @ e_up
        inside = (ein > -(1 - along) * PW + 0.003) & (ein < along * PW) & (eup > -up * PH) & (eup < (1 - up) * PH)
        wrong = np.where(self.hand_thumb, sd < -0.002, sd > 0.002) & inside & (np.abs(sd) < 0.04)
        return int(wrong.sum())

    def candidates(self, C, nrm, step=15):
        """Hand rotations holding the pinch at C with the page between thumb and index, thumb on the
        side nrm points to. The thumb->index line may slant up to MAX_SLANT from straight through the
        page (a real hand holds a page between the thumb pad and the side of the index, fingers lying
        along it); then turned about that line. Yields (key, R_bone, wrist, elbow, bend_deg)."""
        rest = self.rest_hand
        # the rest hand's own thumb->index axis, to line it up with -nrm (thumb in front)
        pb = self.rig.pose.bones
        Mh = pb['hand_r'].matrix
        t_loc = Mh.inverted() @ pb['thumb_03_r'].tail
        i_loc = Mh.inverted() @ pb['index_03_r'].tail
        ax_loc = (i_loc - t_loc).normalized()                 # thumb -> index, hand bone space
        fwd_loc = Vector((0, 1, 0))                            # the hand bone's own Y: towards the fingers
        perp = nrm.orthogonal().normalized()
        for slant in range(0, MAX_SLANT + 1, 15):
            for az in (range(0, 360, 30) if slant else (0,)):
                axis = Quaternion(nrm, math.radians(az)) @ (Quaternion(perp, math.radians(slant)) @ -nrm)
                base = (rest @ ax_loc).rotation_difference(axis).to_matrix() @ rest
                for psi in range(0, 360, step):
                    R = Quaternion(axis, math.radians(psi)).to_matrix() @ base
                    W = C - self.hand_world(R)
                    E = self.elbow(W)
                    bend = math.degrees((R @ fwd_loc).angle((W - E).normalized()))
                    yield (slant, az, psi), R, W, E, bend

    def apply(self, W, R, fingers):
        self.wrist_t.location = W
        self.aim.rotation_quaternion = R.to_quaternion()
        E = self.elbow(W)
        self.pole_t.location = E + (E - (self.S + W) / 2).normalized() * 0.3
        self.fingers(fingers)
        bpy.context.view_layer.update()


# ---------------------------------------------------------------- the pose for every p
def solve(arm, samples=61, keep=70, max_step=9.0):
    """The hand's rotation on a fixed grid of p, planned over the whole turn at once (dynamic
    programming over the best candidate grips at each step): the wrist as comfortable as possible
    and no sudden turns - it eases into a better grip early instead of snapping to it. Any p is then a
    pure interpolation, the same whichever way it is played."""
    steps = []
    for i in range(samples):
        p = i / (samples - 1)
        C, fr = target(p)
        cands = []
        theta = phase(p)[0]
        along = GRIP[0] - (GRIP[0] - STAND_ALONG) * math.sin(theta)
        holding = phase(p)[1] > 0.5 and phase(p)[2] < 0.5
        for key, R, W, E, bend in arm.candidates(C, fr[2]):
            c = max(0.0, bend - WRIST_SOFT) * 3 + bend * 0.2 + key[0] * 0.05
            back = R @ Vector((1, 0, 0))                          # (the back of the hand: bone +X)
            c += max(0.0, 0.25 - back.dot(VIEW_UP)) * 120.0       # (palm towards the page, back to the eyes)
            if holding:
                c += arm.crossing(R, fr, along, GRIP[1]) * 1.5
            cands.append((c, R.to_quaternion()))
        cands.sort(key=lambda c: c[0])
        steps.append(cands[:keep])
    cost = [c[0] for c in steps[0]]
    back = []
    for i in range(1, samples):
        new, ptr = [], []
        for c_now, q_now in steps[i]:
            best = None
            for j, (c_prev, q_prev) in enumerate(steps[i - 1]):
                d = math.degrees(q_prev.rotation_difference(q_now).angle)
                t = cost[j] + d * 0.8 + max(0.0, d - max_step) * 20.0
                if best is None or t < best[0]:
                    best = (t, j)
            new.append(best[0] + c_now)
            ptr.append(best[1])
        cost = new
        back.append(ptr)
    k = int(np.argmin(cost))
    path = [k]
    for ptr in reversed(back):
        k = ptr[k]
        path.append(k)
    path.reverse()
    quats = []
    for i, k in enumerate(path):
        q = steps[i][k][1].copy()
        if quats and quats[-1].dot(q) < 0:
            q.negate()
        quats.append(q)
    # smooth the path (the candidates are on a coarse grid of angles): a gaussian over the steps
    Q = np.array([q[:] for q in quats])
    from scipy.ndimage import gaussian_filter1d
    Q = gaussian_filter1d(Q, 1.5, axis=0, mode='nearest')
    Q /= np.linalg.norm(Q, axis=1, keepdims=True)
    return [Quaternion(q) for q in Q]


def target(p):
    theta, reach, let_go, fing = phase(p)
    C_rest, fr_rest = page_point(*REST, 0.0)
    if p >= RETURN_AT:                                             # let go: back to resting on the right edge
        C_off, _ = target(RETURN_AT - 1e-6)
        w = ease((p - RETURN_AT) / (1.0 - RETURN_AT))
        return C_off.lerp(C_rest, w), fr_rest
    along = GRIP[0] - (GRIP[0] - STAND_ALONG) * math.sin(theta)   # (slides in as the page stands)
    C_grip, fr_grip = page_point(along, GRIP[1], theta)
    C = C_rest.lerp(C_grip, reach)
    C = C - fr_grip[2] * 0.03 * let_go + Vector((0.02, -0.02, 0.01)) * let_go     # (letting go: off the page)
    return C, fr_grip


def pose_at(arm, quats, p):
    x = p * (len(quats) - 1)
    i = min(int(x), len(quats) - 2)
    R = quats[i].slerp(quats[i + 1], x - i).to_matrix()
    theta, reach, let_go, fing = phase(p)
    C, fr = target(p)
    return theta, C - arm.hand_world(R), R, fing


# ---------------------------------------------------------------- checks
def evaluate(arm, page, psis, p):
    theta, W, R, fing = pose_at(arm, psis, p)
    set_page(page, theta)
    arm.apply(W, R, fing)
    pb = arm.rig.pose.bones
    Mw = arm.rig.matrix_world
    tip = Mw @ ((pb['thumb_03_r'].tail + pb['index_03_r'].tail) / 2)
    C, fr = target(p)
    hand_head = Mw @ pb['hand_r'].head
    elbow = Mw @ pb['lowerarm_r'].head
    fwd = (Mw.to_3x3() @ pb['hand_r'].matrix.to_3x3()) @ Vector((0, 1, 0))
    bend = math.degrees(fwd.angle((hand_head - elbow).normalized()))
    # skin points on the wrong side of the page (all but the thumb behind it)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = arm.skin.evaluated_get(dg)
    me = ev.to_mesh()
    V = np.array([(arm.skin.matrix_world @ v.co)[:] for v in me.vertices])
    ev.to_mesh_clear()
    G = np.array([page_point(a / 12, u / 12, theta)[0][:] for a in range(13) for u in range(13)])
    N = np.array([page_point(a / 12, u / 12, theta)[1][2][:] for a in range(13) for u in range(13)])
    d2 = ((V[:, None] - G[None]) ** 2).sum(2)
    k = d2.argmin(1)
    sd = ((V - G[k]) * N[k]).sum(1)
    inpl = np.sqrt(np.maximum(d2[np.arange(len(V)), k] - sd ** 2, 0))
    near = inpl < PW / 12
    thumb = arm.thumb_verts
    wrong = np.where(thumb, sd < -0.002, sd > 0.002) & near & (np.abs(sd) < 0.03)   # thumb behind / rest in front
    through = int(wrong.sum()) if phase(p)[2] < 0.5 and phase(p)[1] > 0.5 else 0
    bones = np.array([np.array(b.matrix) for b in pb])
    return dict(p=p, theta=math.degrees(theta), contact_err_mm=float((tip - C).length * 1000) if phase(p)[2] < 0.2 else None,
                wrist_bend=bend, elbow_z=elbow.z, skin_on_page=through), bones


def render(out, name, cam_from, cam_to, lens=35):
    sc = bpy.context.scene
    cam = sc.camera
    cam.location = cam_from
    cam.rotation_mode = 'QUATERNION'
    cam.rotation_quaternion = (Vector(cam_to) - Vector(cam_from)).to_track_quat('-Z', 'Y')
    cam.data.lens = lens
    sc.render.filepath = os.path.join(out, name)
    bpy.ops.render.render(write_still=True)


def main():
    args = [a for a in sys.argv[1:] if a != '--']
    out = args[0]
    os.makedirs(out, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.display.shading.light, sc.display.shading.color_type = 'STUDIO', 'MATERIAL'
    sc.display.shading.show_cavity = True
    sc.display.shading.show_shadows = True
    sc.render.resolution_x, sc.render.resolution_y = 640, 400
    cam = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))
    sc.collection.objects.link(cam)
    sc.camera = cam
    page = make_page()
    arm = Arm()
    psis = solve(arm)
    report, fwd_bones = [], {}
    P = [i / 60 for i in range(61)]
    for p in P:
        r, bones = evaluate(arm, page, psis, p)
        report.append(r)
        fwd_bones[p] = bones
    scrub = max(float(np.abs(evaluate(arm, page, psis, p)[1] - fwd_bones[p]).max()) for p in reversed(P))
    # abrupt changes: the largest frame-to-frame change of the hand's rotation (deg) over the turn
    jumps = []
    for a_, b_ in zip(P, P[1:]):
        Ra = Matrix(fwd_bones[a_][arm.rig.pose.bones.find('hand_r')].tolist()).to_quaternion()
        Rb = Matrix(fwd_bones[b_][arm.rig.pose.bones.find('hand_r')].tolist()).to_quaternion()
        jumps.append(math.degrees(Ra.rotation_difference(Rb).angle))
    summary = dict(contact_err_mm_max=max(r['contact_err_mm'] for r in report if r['contact_err_mm'] is not None),
                   wrist_bend_max=max(r['wrist_bend'] for r in report), wrist_bend_median=float(np.median([r['wrist_bend'] for r in report])),
                   skin_on_page_max=max(r['skin_on_page'] for r in report), hand_turn_step_max_deg=max(jumps),
                   scrub_diff=scrub)
    json.dump(dict(summary=summary, samples=report), open(os.path.join(out, 'checks.json'), 'w'), indent=1)
    print('SUMMARY', json.dumps(summary))
    for p in (0.0, 0.25, 0.5, 0.75, 1.0):
        theta, W, R, fing = pose_at(arm, psis, p)
        set_page(page, theta)
        arm.apply(W, R, fing)
        C, _ = target(p)
        tag = f'{int(p * 100):03d}'
        render(out, f'fp_{tag}.png', Vector((0.03, -0.42, 0.42)), Vector((0.0, -0.02, 0.0)))     # first person
        render(out, f'close_{tag}.png', C + Vector((0.10, -0.16, 0.10)), C + Vector((0.03, -0.03, 0.0)), lens=50)
    if '--save' in args:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args[args.index('--save') + 1]))


if __name__ == '__main__':
    main()
