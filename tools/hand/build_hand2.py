"""A game-style 3D right hand from MakeHuman's free (CC0) body model: the hand and forearm, its
finger bones and skin weights, skin and nails coloured from Alejandro's photos, and a suede
sleeve made from the sleeve in his photo. Run: python3 build_hand2.py <out_dir> <pose>"""
import json
import math
import os
import sys

import bpy  # noqa: I001  (bmesh and mathutils come with bpy)
import bmesh
import numpy as np
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
MH = '/home/claude/makehumancommunity/mpfb2/src/mpfb/data'
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'out2')
POSE = sys.argv[2] if len(sys.argv) > 2 else 'relaxed'
os.makedirs(OUT, exist_ok=True)

FINGERS = ('thumb', 'index', 'middle', 'ring', 'pinky')
HAND_BONES = ['lowerarm_r', 'hand_r'] + [f'{f}_0{k}_r' for f in FINGERS for k in (1, 2, 3)]

# ---------------------------------------------------------------- read the body model
V, VT, faces, groups, cur = [], [], [], {}, None
for line in open(os.path.join(MH, '3dobjs', 'base.obj')):
    if line.startswith('v '):
        V.append([float(x) for x in line.split()[1:4]])
    elif line.startswith('vt '):
        VT.append([float(x) for x in line.split()[1:3]])
    elif line.startswith('g '):
        cur = line.split()[1]
    elif line.startswith('f '):
        idx = [t.split('/') for t in line.split()[1:]]
        vs = [int(a[0]) - 1 for a in idx]
        groups.setdefault(cur, set()).update(vs)
        if cur == 'body':
            faces.append((vs, [int(a[1]) - 1 for a in idx]))
V = np.array(V)
# a man's hand: MakeHuman's own shape targets (CC0), mixed in like its sliders
import gzip
T = MH + '/targets/'
MALE = [('macrodetails/universal-male-young-maxmuscle-averageweight', 1.0),
        ('macrodetails/universal-male-young-averagemuscle-maxweight', 0.25),
        ('hands/r-hand-fingers-diameter-incr', float(os.environ.get('FINGER_THICK', 1.0))),
        ('hands/measure-wrist-circ-incr', 1.0),
        ('hands/r-hand-scale-incr', 0.4),
        ('hands/r-hand-fingers-distance-incr', 0.3),
        ('hands/r-hand-fingers-length-decr', 0.35)]
for name, w in (MALE if os.environ.get('MALE', '1') == '1' else []):
    for row in gzip.open(T + name + '.target.gz', 'rt'):
        f_ = row.split()
        if len(f_) == 4 and not row.startswith('#'):
            V[int(f_[0])] += w * np.array([float(x) for x in f_[1:]])
V = V * 0.1
V = np.stack([V[:, 0], -V[:, 2], V[:, 1]], axis=1)          # Blender axes, metres

rig_def = json.load(open(os.path.join(MH, 'rigs', 'standard', 'rig.game_engine.json')))
weights = json.load(open(os.path.join(MH, 'rigs', 'standard', 'weights.game_engine.json')))['weights']
wsum = np.zeros(len(V))
for b in HAND_BONES:
    for vi, w in weights.get(b, []):
        wsum[vi] += w
lower_w = np.zeros(len(V))
for vi, w in weights['lowerarm_r']:
    lower_w[vi] = w


def cube(name):
    return Vector(V[list(groups[name])].mean(axis=0))


# keep the hand and the lower half of the forearm (the sleeve covers the rest)
elbow, wrist = cube(rig_def['lowerarm_r']['head']['cube_name']), cube(rig_def['hand_r']['head']['cube_name'])
fore = (wrist - elbow)
SHOULDER = elbow + fore.normalized() * -0.29     # the upper arm (asset only): straight on from the forearm
ASSET = os.environ.get('ASSET')
keep = set(np.nonzero(wsum > 0.5)[0])
keep = {i for i in keep if (Vector(V[i]) - elbow).dot(fore) / fore.length_squared > 0.35}
sel = [(vs, ts) for vs, ts in faces if all(v in keep for v in vs)]
used = sorted({v for vs, _ in sel for v in vs})
remap = {v: i for i, v in enumerate(used)}

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
me = bpy.data.meshes.new('Hand')
me.from_pydata([tuple(V[v]) for v in used], [], [[remap[v] for v in vs] for vs, _ in sel])
me.update()
uv = me.uv_layers.new(name='mh')
li = 0
for _, ts in sel:
    for t in ts:
        uv.data[li].uv = VT[t]
        li += 1
hand = bpy.data.objects.new('Hand', me)
scene.collection.objects.link(hand)
for p in me.polygons:
    p.use_smooth = True
huv = me.uv_layers.new(name='hand')            # the hand's own layout, filling the whole texture
me.uv_layers.active = huv
bpy.context.view_layer.objects.active = hand
hand.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.uv.smart_project(angle_limit=math.radians(70), island_margin=0.004)
bpy.ops.object.mode_set(mode='OBJECT')
me.uv_layers.active = me.uv_layers['mh']
for b in HAND_BONES:                      # skin weights
    vg = hand.vertex_groups.new(name=b)
    for vi, w in weights.get(b, []):
        if vi in remap:
            vg.add([remap[vi]], w, 'REPLACE')

# ---------------------------------------------------------------- bones
arm = bpy.data.armatures.new('HandRig')
rig = bpy.data.objects.new('HandRig', arm)
scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='EDIT')
for b in HAND_BONES:
    d = rig_def[b]
    eb = arm.edit_bones.new(b)
    eb.head, eb.tail = cube(d['head']['cube_name']), cube(d['tail']['cube_name'])
    eb.roll = d.get('roll', 0.0)
for b in HAND_BONES:
    par = rig_def[b].get('parent')
    if par in arm.edit_bones:
        arm.edit_bones[b].parent = arm.edit_bones[par]
        arm.edit_bones[b].use_connect = bool(rig_def[b].get('use_connect'))
bpy.ops.object.mode_set(mode='OBJECT')
mod = hand.modifiers.new('rig', 'ARMATURE')
mod.object = rig
hand.parent = rig
sub = hand.modifiers.new('sub', 'SUBSURF')
sub.levels = sub.render_levels = 2


def rest(b):
    return arm.bones[b]


# a frame on the hand: forward = wrist -> middle knuckle, back of the hand = up
w0 = rest('hand_r').head_local
mid = rest('middle_01_r').head_local
side = rest('index_01_r').head_local - rest('pinky_01_r').head_local
fwd = (mid - w0).normalized()
up = fwd.cross(side).normalized()           # right hand: index on the thumb side
# (checked below with the thumb: the thumb must be on the index side)
right = up.cross(fwd).normalized()


def pose_finger(f, angles, spread=0.0):
    """Bend one finger: degrees per joint towards the palm, plus sideways spread (degrees)."""
    for k, a in enumerate(angles):
        pb = rig.pose.bones[f'{f}_0{k + 1}_r']
        pb.rotation_mode = 'XYZ'
        pb.rotation_euler = (math.radians(a), 0, math.radians(spread) if k == 0 else 0)


POSES = {
    'flat': {f: (0, 0, 0) for f in FINGERS},
    'relaxed': {'thumb': (5, 10, 10), 'index': (10, 15, 10), 'middle': (14, 18, 12), 'ring': (18, 22, 14),
                'pinky': (22, 26, 16)},
    'pinch': {'thumb': (15, 25, 30), 'index': (40, 50, 25), 'middle': (35, 55, 35), 'ring': (45, 60, 40),
              'pinky': (50, 65, 40)},
}
SIGN = float(os.environ.get('BEND_SIGN', 1))
for f, angs in POSES.get(POSE, POSES['relaxed']).items():
    pose_finger(f, [SIGN * a for a in angs])

# ---------------------------------------------------------------- sleeve (suede, from the photo)
CUFF = 0.036           # the cuff band, metres
# with the cloth drape the folds come from the cloth itself; the drawn folds only seed them
FOLD_AMP = 0.35 if (os.environ.get('ASSET') and os.environ.get('DRAPE', '1') == '1') else 1.0


def drape(ob, rings, segs, L_, base, dirs, ax0, axis):
    """Real cloth: the sleeve starts 12% longer, its cuff and top are held, and the top is pushed
    down to the right length, so the suede buckles over the arm into its own folds. The result is
    kept as the sleeve's shape."""
    me_ = ob.data
    co = np.array([v.co for v in me_.vertices])
    n = np.array(axis.normalized())
    along = (co - np.array(ax0)) @ n
    sk0 = ob.shape_key_add(name='Basis')
    long_ = ob.shape_key_add(name='Long')
    long_.data.foreach_set('co', (co + np.outer(along * float(os.environ.get('PUSH', 0.08)), n)).ravel())
    long_.value = 1.0
    long_.keyframe_insert('value', frame=1)
    long_.value = 0.0
    long_.keyframe_insert('value', frame=45)
    pin = ob.vertex_groups.new(name='pin')
    for vi in range(len(me_.vertices)):
        r = vi // segs
        y = r / rings * L_
        if y < CUFF + 0.004 or r >= rings - 1:
            pin.add([vi], 1.0, 'REPLACE')
    # the arm inside, for the cloth to rest on
    cbm = bmesh.new()
    cgrid = []
    for r in range(rings + 1):
        c = ax0 + axis * (r / rings)
        cgrid.append([cbm.verts.new(c + Vector(dirs[s_]) * (base[r, s_] + 0.0025)) for s_ in range(segs)])
    for r in range(rings):
        for s_ in range(segs):
            cbm.faces.new((cgrid[r][s_], cgrid[r][(s_ + 1) % segs], cgrid[r + 1][(s_ + 1) % segs], cgrid[r + 1][s_]))
    cme = bpy.data.meshes.new('ArmCollider')
    cbm.to_mesh(cme)
    col_ob = bpy.data.objects.new('ArmCollider', cme)
    scene.collection.objects.link(col_ob)
    cm = col_ob.modifiers.new('col', 'COLLISION')
    col_ob.collision.thickness_outer = 0.0015
    cloth = ob.modifiers.new('cloth', 'CLOTH')
    cs = cloth.settings
    cs.quality = 8
    cs.mass = 0.35
    cs.tension_stiffness = cs.compression_stiffness = 60
    cs.shear_stiffness = 40
    cs.bending_stiffness = float(os.environ.get('BEND', 80))   # suede is thick: few, rounded folds
    cs.air_damping = 2.0
    cs.vertex_group_mass = 'pin'
    cs.effector_weights.gravity = 0.0              # the arm may point any way: no sag baked in
    cc = cloth.collision_settings
    cc.use_collision = True
    cc.distance_min = 0.0015
    cc.use_self_collision = True
    cc.self_distance_min = 0.0015
    cloth.point_cache.frame_start, cloth.point_cache.frame_end = 1, 70
    for f in range(1, 71):
        scene.frame_set(f)
    dg = bpy.context.evaluated_depsgraph_get()
    draped = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    ob.modifiers.remove(cloth)
    ob.shape_key_clear()
    old = ob.data
    ob.data = draped
    bpy.data.meshes.remove(old)
    if 'pin' in ob.vertex_groups:
        ob.vertex_groups.remove(ob.vertex_groups['pin'])
    bpy.data.objects.remove(col_ob)
    bpy.data.meshes.remove(cme)
    scene.frame_set(1)
    for poly in ob.data.polygons:
        poly.use_smooth = True
    print('DRAPED', len(ob.data.vertices), flush=True)
SEAM_R = 0.05          # the radius used for the 'uv' x coordinate (metres around)


def sleeve_mesh():
    """A suede sleeve like the one in the photos: a snug cuff band with a folded, stitched lip;
    a stitched seam where it joins the sleeve, which gathers a little above it; a few soft
    diagonal folds; and a stitched seam along the side of the arm. UV 'uv' is in metres."""
    import random
    global SEAM_X
    rnd = random.Random(int(os.environ.get('FOLD_SEED', 11)))
    ax0 = wrist + (elbow - wrist) * 0.035
    ax1 = SHOULDER if ASSET else elbow + (elbow - wrist) * 0.05
    Lf = (elbow - ax0).length
    axis = (ax1 - ax0)
    L_ = axis.length
    n = axis.normalized()
    u_ = up - n * up.dot(n)
    u_.normalize()
    v_ = n.cross(u_)
    sd = side - n * side.dot(n)
    sd.normalize()
    seam_dir = (sd * 0.55 - u_ * 0.85).normalized()           # the side seam: thumb side, underneath
    a_seam = math.atan2(seam_dir.dot(v_), seam_dir.dot(u_)) % (2 * math.pi)
    SEAM_X = a_seam * SEAM_R
    pts = np.array([V[i] for i in used])
    rings, segs = 110, 96
    folds = []
    for _ in range(13):
        tilt = rnd.choice((-1, 1)) * rnd.uniform(0.35, 0.75)
        folds.append((rnd.uniform(CUFF + 0.012, L_ - 0.02), rnd.uniform(0, 2 * math.pi), tilt,
                      rnd.uniform(0.04, 0.08), rnd.uniform(0.007, 0.012), rnd.uniform(0.004, 0.0072)))
    base = np.zeros((rings + 1, segs))
    ang = np.arange(segs) * 2 * math.pi / segs
    dirs = np.array([u_ * math.cos(x) + v_ * math.sin(x) for x in ang])
    for r in range(rings + 1):
        c = np.array(ax0 + axis * (r / rings))
        rel = pts - c
        ax_d = rel @ np.array(n)
        near = rel[np.abs(ax_d) < 0.012]
        if len(near) < 10:
            base[r] = base[r - 1] if r else 0.03
            continue
        perp = near - np.outer(near @ np.array(n), np.array(n))
        proj = perp @ dirs.T                                   # (points, directions)
        base[r] = np.maximum(proj.max(0), 0.02)
    # cloth doesn't follow every bump: smooth round and along
    from scipy.ndimage import uniform_filter1d
    base = uniform_filter1d(uniform_filter1d(base, 11, axis=1, mode='wrap'), 5, axis=0, mode='nearest')
    bm = bmesh.new()
    grid = []
    for r in range(rings + 1):
        t = r / rings
        y = t * L_
        c = ax0 + axis * t
        row = []
        for s_ in range(segs):
            a = ang[s_]
            rb = base[r, s_]
            if y < CUFF:                                       # the snug cuff band
                rad = rb + 0.0045
                lip = max(0.0, 1 - y / 0.003)                  # its folded, rounded lip
                rad -= 0.0022 * (1 - math.sqrt(max(0.0, 1 - lip * lip)))
            else:                                              # the sleeve: a little fuller above the cuff
                k = min(1.0, (y - CUFF) / 0.006)
                rad = rb + 0.0045 + 0.0045 * k * k * (3 - 2 * k) + 0.012 * min(y - CUFF, Lf) / Lf + 0.012 * min(max(y - Lf, 0) / 0.12, 1)
                rad += 0.0009 * math.exp(-((y - CUFF - 0.0018) / 0.0014) ** 2)   # the welt of the seam
                for y0, a0, tilt, ln, w, amp in folds:         # soft diagonal folds
                    dx = ((a - a0 + math.pi) % (2 * math.pi) - math.pi) * SEAM_R
                    dy = y - y0
                    along = dx * math.cos(tilt) + dy * math.sin(tilt)
                    across = -dx * math.sin(tilt) + dy * math.cos(tilt)
                    rad += FOLD_AMP * amp * math.exp(-(across / w) ** 2 - (along / ln) ** 4)
                ds = ((a - a_seam + math.pi) % (2 * math.pi) - math.pi) * SEAM_R
                rad += 0.0007 * math.exp(-((ds - 0.0025) / 0.0015) ** 2) - 0.0008 * math.exp(-(ds / 0.0009) ** 2)
            row.append(bm.verts.new(c + Vector(dirs[s_]) * rad))
        grid.append(row)
    for r in range(rings):
        for s_ in range(segs):
            bm.faces.new((grid[r][s_], grid[r][(s_ + 1) % segs], grid[r + 1][(s_ + 1) % segs],
                          grid[r + 1][s_]))
    m = bpy.data.meshes.new('Sleeve')
    bm.to_mesh(m)
    lay = m.uv_layers.new(name='uv')
    for poly in m.polygons:
        ss = [m.loops[k].vertex_index % segs for k in poly.loop_indices]
        wrap = max(ss) - min(ss) > segs / 2
        for k in poly.loop_indices:
            r, s_ = divmod(m.loops[k].vertex_index, segs)
            if wrap and s_ < segs / 2:
                s_ += segs
            lay.data[k].uv = (s_ / segs * 2 * math.pi * SEAM_R, r / rings * L_)
    for poly in m.polygons:
        poly.use_smooth = True
    ob = bpy.data.objects.new('Sleeve', m)
    scene.collection.objects.link(ob)
    if ASSET and os.environ.get('DRAPE', '1') == '1':
        drape(ob, rings, segs, L_, base, dirs, ax0, axis)
        m = ob.data
    if ASSET:                                      # bends with the elbow
        lo, up_ = ob.vertex_groups.new(name='lowerarm_r'), ob.vertex_groups.new(name='upperarm_r')
        for vi in range(len(m.vertices)):
            y = (vi // segs) / rings * L_
            k = min(1.0, max(0.0, (y - (Lf - 0.035)) / 0.07))
            k = k * k * (3 - 2 * k)
            lo.add([vi], 1 - k, 'REPLACE')
            up_.add([vi], k, 'REPLACE')
        am = ob.modifiers.new('rig', 'ARMATURE')
        am.object = rig
    ob.modifiers.new('thick', 'SOLIDIFY').thickness = 0.002
    ob.modifiers.new('sub', 'SUBSURF').levels = 1
    ob.parent = rig
    return ob


sleeve = sleeve_mesh()

# ---------------------------------------------------------------- materials (game look)
def detail_map(path, res=2048):
    """Knuckles, tendons and veins on the back of the hand, drawn as a height map in the hand's UV
    layout (so they stay put when the fingers bend)."""
    P = np.array([v.co for v in me.vertices])
    N = np.array([v.normal for v in me.vertices])
    UVs = np.zeros((len(me.loops), 2))
    me.uv_layers['hand'].data.foreach_get('uv', UVs.ravel())
    upv, w = np.array(up), np.array(w0)
    backside = (N @ upv) > 0.3

    def surf(pt, lift=0.0):
        """The point on the back of the hand straight above a joint."""
        pt = np.array(pt)
        rel = P - pt
        lat = np.linalg.norm(rel - np.outer(rel @ upv, upv), axis=1)
        m = backside & (lat < 0.006)
        if not m.any():
            return pt
        return pt + upv * ((rel[m] @ upv).max() + lift)
    heads = {f: surf(rest(f'{f}_01_r').head_local) for f in FINGERS}
    pips = [surf(rest(f'{f}_02_r').head_local) for f in FINGERS[1:]]
    dips = [surf(rest(f'{f}_03_r').head_local) for f in FINGERS[1:]]
    wr = surf(np.array(w0) + np.array(fwd) * 0.01)

    def seg(x, a, b):
        ab = b - a
        t = np.clip(((x - a) @ ab) / (ab @ ab), 0, 1)
        return np.linalg.norm(x - (a + t[:, None] * ab), axis=1), t

    def height(x, n):
        back = np.clip(((n @ upv) - 0.15) / 0.4, 0, 1)
        h = np.zeros(len(x))
        for f in FINGERS[1:]:
            h += 1.0 * np.exp(-np.sum((x - heads[f]) ** 2, 1) / (2 * 0.0055 ** 2))        # big knuckles
            mid = wr + (heads[f] - wr) * 0.0 + (heads[f] - heads['middle']) * 0.35
            d, t = seg(x, mid, heads[f])
            h += 0.22 * np.exp(-d ** 2 / (2 * 0.0035 ** 2)) * np.sin(np.pi * np.clip(t, 0, 1)) ** 0.6   # tendons
        for k in pips:
            h += 0.55 * np.exp(-np.sum((x - k) ** 2, 1) / (2 * 0.0040 ** 2))
        for k in dips:
            h += 0.3 * np.exp(-np.sum((x - k) ** 2, 1) / (2 * 0.0030 ** 2))
        # two veins: from the wrist, forking between the knuckles
        side_ = np.array(side) / np.linalg.norm(side)
        for a_, b_ in (((wr - side_ * 0.012), (heads['ring'] + heads['middle']) / 2 - np.array(fwd) * 0.02),
                       ((wr + side_ * 0.010), (heads['index'] + heads['middle']) / 2 - np.array(fwd) * 0.025),
                       ((wr - side_ * 0.004), (wr - side_ * 0.004) - np.array(fwd) * 0.05)):
            d, t = seg(x, a_, b_)
            h += 0.14 * np.exp(-d ** 2 / (2 * 0.0017 ** 2))
        return h * back

    img = np.zeros((res, res), np.float32)
    for poly in me.polygons:
        vs, ls = list(poly.vertices), list(poly.loop_indices)
        for k in range(1, len(vs) - 1):
            tri = [0, k, k + 1]
            uv3 = UVs[[ls[i] for i in tri]] * res
            p3, n3 = P[[vs[i] for i in tri]], N[[vs[i] for i in tri]]
            x0, y0 = np.floor(uv3.min(0)).astype(int) - 1
            x1, y1 = np.ceil(uv3.max(0)).astype(int) + 1
            xs, ys = np.meshgrid(np.arange(max(x0, 0), min(x1, res)), np.arange(max(y0, 0), min(y1, res)))
            q = np.stack([xs.ravel() + 0.5, ys.ravel() + 0.5], 1)
            T_ = np.array([uv3[1] - uv3[0], uv3[2] - uv3[0]]).T
            if abs(np.linalg.det(T_)) < 1e-9:
                continue
            l12 = np.linalg.solve(T_, (q - uv3[0]).T).T
            bary = np.column_stack([1 - l12.sum(1), l12])
            ok = (bary > -0.02).all(1)
            if not ok.any():
                continue
            b = bary[ok]
            img[ys.ravel()[ok], xs.ravel()[ok]] = height(b @ p3, b @ n3)
    from PIL import Image as _I
    _I.fromarray(np.clip(img[::-1] * 200, 0, 255).astype(np.uint8)).save(path)
    return path


def photo_maps():
    import photo_bake
    P = np.array([v.co for v in me.vertices])
    N = np.array([v.normal for v in me.vertices])
    UVs = np.zeros((len(me.loops), 2))
    me.uv_layers['hand'].data.foreach_get('uv', UVs.ravel())
    polys = [(list(p.vertices), list(p.loop_indices)) for p in me.polygons]
    joints = {}
    for f in FINGERS:
        b1, b2, b3 = (rest(f'{f}_0{k}_r') for k in (1, 2, 3))
        joints[f] = [b3.tail_local, b3.head_local, b2.head_local, b1.head_local]
    return photo_bake.bake(P, N, UVs, polys, joints, w0, right, fwd, up,
                           os.path.join(HERE, 'back_filled.png'), os.path.join(HERE, 'palm_filled.png'),
                           os.path.join(HERE, 'back.png'), os.path.join(HERE, 'palm.png'),
                           int(os.environ.get('TEX', 3072)),
                           os.path.join(OUT, 'hand_colour.png'), os.path.join(OUT, 'hand_wrinkles.png'))


def skin_material():
    m = bpy.data.materials.new('Skin')
    nt = m.node_tree if m.node_tree else None
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes['Principled BSDF']
    base = (0.33, 0.145, 0.06)                 # the photo's tan, in linear colour
    knuckle = (0.30, 0.11, 0.045)
    ao = nt.nodes.new('ShaderNodeAmbientOcclusion')
    ao.inputs['Distance'].default_value = 0.012
    mix = nt.nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.inputs[6].default_value = (*knuckle, 1)
    mix.inputs[7].default_value = (*base, 1)
    nt.links.new(ao.outputs['AO'], mix.inputs[0])
    nails = nt.nodes.new('ShaderNodeTexImage')
    nails.image = bpy.data.images.load(os.path.join(HERE, 'mpfb_fingernails.jpg'))
    nails.image.colorspace_settings.name = 'Non-Color'
    uvn = nt.nodes.new('ShaderNodeUVMap')
    uvn.uv_map = 'mh'
    nt.links.new(uvn.outputs['UV'], nails.inputs['Vector'])
    nailmix = nt.nodes.new('ShaderNodeMix')
    nailmix.data_type = 'RGBA'
    nailmix.inputs[7].default_value = (0.42, 0.20, 0.11, 1)
    nt.links.new(nails.outputs['Color'], nailmix.inputs[0])
    nt.links.new(mix.outputs[2], nailmix.inputs[6])
    nt.links.new(nailmix.outputs[2], bsdf.inputs['Base Color'])
    rough = nt.nodes.new('ShaderNodeMapRange')
    rough.inputs['To Min'].default_value = 0.55
    rough.inputs['To Max'].default_value = 0.4
    nt.links.new(nails.outputs['Color'], rough.inputs['Value'])
    nt.links.new(rough.outputs['Result'], bsdf.inputs['Roughness'])
    bsdf.inputs['Subsurface Weight'].default_value = 0.3
    bsdf.inputs['Subsurface Radius'].default_value = (1.0, 0.4, 0.25)
    bsdf.inputs['Subsurface Scale'].default_value = 0.004
    noise = nt.nodes.new('ShaderNodeTexNoise')       # pores and fine wrinkles
    noise.inputs['Scale'].default_value = 900.0
    noise.inputs['Detail'].default_value = 10.0
    wave = nt.nodes.new('ShaderNodeTexWave')
    wave.inputs['Scale'].default_value = 140.0
    wave.inputs['Distortion'].default_value = 12.0
    add = nt.nodes.new('ShaderNodeMath')
    add.operation = 'ADD'
    nt.links.new(noise.outputs['Fac'], add.inputs[0])
    nt.links.new(wave.outputs['Fac'], add.inputs[1])
    bmp = nt.nodes.new('ShaderNodeBump')
    bmp.inputs['Strength'].default_value = 0.06
    bmp.inputs['Distance'].default_value = 0.0003
    nt.links.new(add.outputs[0], bmp.inputs['Height'])
    det = nt.nodes.new('ShaderNodeTexImage')
    det.image = bpy.data.images.load(detail_map(os.path.join(OUT, 'hand_detail.png')))
    det.image.colorspace_settings.name = 'Non-Color'
    uvh = nt.nodes.new('ShaderNodeUVMap')
    uvh.uv_map = 'hand'
    nt.links.new(uvh.outputs['UV'], det.inputs['Vector'])
    bmp2 = nt.nodes.new('ShaderNodeBump')
    bmp2.inputs['Strength'].default_value = float(os.environ.get('DETAIL', 0.8))
    bmp2.inputs['Distance'].default_value = float(os.environ.get('DETAIL_MM', 4)) / 1000
    nt.links.new(det.outputs['Color'], bmp2.inputs['Height'])
    nt.links.new(bmp.outputs['Normal'], bmp2.inputs['Normal'])
    tint = nt.nodes.new('ShaderNodeMix')                     # knuckles a little darker and redder
    tint.data_type = 'RGBA'
    tint.inputs[7].default_value = (0.24, 0.085, 0.04, 1)
    tf = nt.nodes.new('ShaderNodeMath')
    tf.operation = 'MULTIPLY'
    tf.inputs[1].default_value = 0.45
    nt.links.new(det.outputs['Color'], tf.inputs[0])
    nt.links.new(tf.outputs[0], tint.inputs[0])
    nt.links.new(mix.outputs[2], tint.inputs[6])
    nt.links.new(tint.outputs[2], nailmix.inputs[6])
    if os.environ.get('PHOTO', '1') == '1':          # the skin painted from the photos
        cpath, hpath = photo_maps()
        ph = nt.nodes.new('ShaderNodeTexImage')
        ph.image = bpy.data.images.load(cpath)
        ph.interpolation = 'Cubic'
        nt.links.new(uvh.outputs['UV'], ph.inputs['Vector'])
        nt.links.new(ph.outputs['Color'], bsdf.inputs['Base Color'])
        wr = nt.nodes.new('ShaderNodeTexImage')
        wr.image = bpy.data.images.load(hpath)
        wr.image.colorspace_settings.name = 'Non-Color'
        nt.links.new(uvh.outputs['UV'], wr.inputs['Vector'])
        bmp3 = nt.nodes.new('ShaderNodeBump')
        bmp3.inputs['Strength'].default_value = float(os.environ.get('WRINKLE', 0.04))
        bmp3.inputs['Distance'].default_value = 0.0006
        nt.links.new(wr.outputs['Color'], bmp3.inputs['Height'])
        nt.links.new(bmp2.outputs['Normal'], bmp3.inputs['Normal'])
        nt.links.new(bmp3.outputs['Normal'], bsdf.inputs['Normal'])
        bmp2.inputs['Strength'].default_value = float(os.environ.get('DETAIL', 0.2))
    else:
        nt.links.new(bmp2.outputs['Normal'], bsdf.inputs['Normal'])
    return m


def suede_material():
    """Brown suede coloured from the photo's sleeve (sRGB about 82,39,14): a soft nap, light
    scuffs, and a stitched line near the cuff's edge."""
    m = bpy.data.materials.new('Suede')
    m.use_nodes = True
    nt = m.node_tree
    N_, L_ = nt.nodes, nt.links
    bsdf = N_['Principled BSDF']
    uvn = N_.new('ShaderNodeUVMap')
    uvn.uv_map = 'uv'
    sep = N_.new('ShaderNodeSeparateXYZ')
    L_.new(uvn.outputs['UV'], sep.inputs[0])
    tco = N_.new('ShaderNodeTexCoord')

    def noise(scale, detail=6.0, rough=0.6):
        nz = N_.new('ShaderNodeTexNoise')
        nz.inputs['Scale'].default_value = scale
        nz.inputs['Detail'].default_value = detail
        nz.inputs['Roughness'].default_value = rough
        L_.new(tco.outputs['Object'], nz.inputs['Vector'])     # 3D: no seam where the sleeve wraps round
        return nz.outputs['Fac']

    def math_(op, a, b):
        mn = N_.new('ShaderNodeMath')
        mn.operation = op
        for i, x in enumerate((a, b)):
            if isinstance(x, (int, float)):
                mn.inputs[i].default_value = x
            else:
                L_.new(x, mn.inputs[i])
        return mn.outputs[0]

    patches = noise(18.0, 4.0, 0.5)                        # rubbed-light and dark patches
    nap = noise(900.0, 8.0, 0.75)                          # the fine nap
    ramp = N_.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.38
    ramp.color_ramp.elements[0].color = (0.042, 0.012, 0.003, 1)
    ramp.color_ramp.elements[1].position = 0.62
    ramp.color_ramp.elements[1].color = (0.105, 0.034, 0.008, 1)
    L_.new(math_('ADD', math_('MULTIPLY', patches, 0.55), math_('MULTIPLY', nap, 0.45)), ramp.inputs['Fac'])
    def ring_stitch(y0):
        on = math_('LESS_THAN', math_('ABSOLUTE', math_('SUBTRACT', sep.outputs['Y'], y0), 0), 0.00055)
        dash = math_('LESS_THAN', math_('FRACT', math_('MULTIPLY', sep.outputs['X'], 1 / 0.0038), 0), 0.6)
        return math_('MULTIPLY', on, dash)

    stitch = math_('MAXIMUM', ring_stitch(0.0045), ring_stitch(CUFF - 0.0045))
    stitch = math_('MAXIMUM', stitch, ring_stitch(CUFF + 0.0055))
    xs = SEAM_X + 0.0045                                   # along the side seam, past the cuff
    on = math_('LESS_THAN', math_('ABSOLUTE', math_('SUBTRACT', sep.outputs['X'], xs), 0), 0.00055)
    on = math_('MULTIPLY', on, math_('GREATER_THAN', sep.outputs['Y'], CUFF + 0.004))
    dash = math_('LESS_THAN', math_('FRACT', math_('MULTIPLY', sep.outputs['Y'], 1 / 0.0038), 0), 0.6)
    stitch = math_('MAXIMUM', stitch, math_('MULTIPLY', on, dash))
    edge = math_('LESS_THAN', math_('ABSOLUTE', math_('SUBTRACT', sep.outputs['Y'], CUFF), 0), 0.0009)
    blotch = N_.new('ShaderNodeMix')                       # darker mottling, as in the palm photo
    blotch.data_type = 'RGBA'
    bl = N_.new('ShaderNodeMapRange')
    L_.new(noise(70.0, 4.0, 0.55), bl.inputs['Value'])
    bl.inputs['From Min'].default_value = 0.5
    bl.inputs['From Max'].default_value = 0.72
    bl.inputs['To Max'].default_value = 0.18
    L_.new(bl.outputs['Result'], blotch.inputs[0])
    L_.new(ramp.outputs['Color'], blotch.inputs[6])
    blotch.inputs[7].default_value = (0.03, 0.009, 0.002, 1)
    dark = N_.new('ShaderNodeMix')
    dark.data_type = 'RGBA'
    L_.new(math_('MULTIPLY', stitch, 0.6), dark.inputs[0])
    L_.new(blotch.outputs[2], dark.inputs[6])
    dark.inputs[7].default_value = (0.03, 0.01, 0.003, 1)
    L_.new(dark.outputs[2], bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 0.92
    bsdf.inputs['Sheen Weight'].default_value = 0.15
    bsdf.inputs['Sheen Roughness'].default_value = 0.45
    bsdf.inputs['Sheen Tint'].default_value = (1.0, 0.6, 0.35, 1)
    h = math_('ADD', math_('MULTIPLY', nap, 0.6), math_('MULTIPLY', noise(160.0, 6.0, 0.7), 0.4))
    h = math_('SUBTRACT', h, math_('MULTIPLY', stitch, 1.2))
    h = math_('SUBTRACT', h, math_('MULTIPLY', edge, 0.8))
    bmp = N_.new('ShaderNodeBump')
    bmp.inputs['Strength'].default_value = 0.35
    bmp.inputs['Distance'].default_value = 0.0006
    L_.new(h, bmp.inputs['Height'])
    L_.new(bmp.outputs['Normal'], bsdf.inputs['Normal'])
    return m


hand.data.materials.append(skin_material())
sleeve.data.materials.append(suede_material())

# ---------------------------------------------------------------- the asset for the app
if ASSET:
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    pose_finger_all = lambda name: [pose_finger(f, a) for f, a in POSES[name].items()]   # noqa: E731
    pose_finger_all('pinch')
    bpy.context.view_layer.update()
    pb = rig.pose.bones
    thumb_tip = rig.matrix_world.inverted() @ (rig.matrix_world @ pb['thumb_03_r'].tail)
    index_tip = pb['index_03_r'].tail.copy()
    middle_tip = pb['middle_03_r'].tail.copy()
    pinch = (thumb_tip * 0.5 + index_tip * 0.5)
    for b in pb:
        b.rotation_mode = 'XYZ'
        b.rotation_euler = (0, 0, 0)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    ub = arm.edit_bones.new('upperarm_r')
    ub.head, ub.tail = SHOULDER, elbow
    ub.roll = arm.edit_bones['lowerarm_r'].roll
    arm.edit_bones['lowerarm_r'].parent = ub
    arm.edit_bones['lowerarm_r'].use_connect = True
    bpy.ops.object.mode_set(mode='OBJECT')
    info = dict(poses=POSES, pinch=list(pinch), thumb_tip=list(thumb_tip), index_tip=list(index_tip),
                middle_tip=list(middle_tip), wrist=list(w0), elbow=list(elbow), shoulder=list(SHOULDER),
                fwd=list(fwd), up=list(up), right=list(right),
                licence='Hand and arm shape from MakeHuman / MPFB2 (CC0). Skin from the owner\'s photos.')
    rig['motioncraft_hand'] = json.dumps(info)
    for ob in list(scene.collection.objects):
        if ob.type not in ('MESH', 'ARMATURE'):
            bpy.data.objects.remove(ob)
    col = bpy.data.collections.new('MotionCraftHand')
    scene.collection.children.link(col)
    for ob in (rig, hand, sleeve):
        scene.collection.objects.unlink(ob)
        col.objects.link(ob)
    for img in bpy.data.images:          # smaller files: the photo skin as JPEG
        if img.filepath and img.filepath.endswith('hand_colour.png'):
            img.scale(2048, 2048)
            img.filepath_raw = os.path.join(OUT, 'hand_colour.jpg')
            img.file_format = 'JPEG'
            scene.render.image_settings.quality = 90
            img.save()
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=ASSET, compress=True)
    print('ASSET saved', ASSET, json.dumps(info)[:300])
    sys.exit(0)

# ---------------------------------------------------------------- lights, cameras, render
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
pts = np.array([hand.evaluated_get(dg).matrix_world @ v.co for v in hand.evaluated_get(dg).data.vertices])
tip = rest('middle_03_r').tail_local
near = pts[(pts - np.array(w0)) @ np.array(fwd) > -0.05]
centre = Vector((near.max(0) + near.min(0)) / 2)
size = float(np.linalg.norm(near.max(0) - near.min(0)))

world = bpy.data.worlds.new('w')
scene.world = world
world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.010, 0.008, 0.007, 1)


def light(name, d, energy, sz, col):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy, ld.size, ld.color = energy, sz, col
    lo = bpy.data.objects.new(name, ld)
    scene.collection.objects.link(lo)
    lo.location = centre + d
    lo.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()


light('Key', (up * 0.9 - right * 0.6 + fwd * 0.3), 22, 0.35, (1.0, 0.92, 0.84))
light('Fill', (up * 0.5 + right * 0.9 - fwd * 0.2), 5, 0.6, (0.75, 0.82, 1.0))
light('Under', (-up * 0.9 + right * 0.2), 6, 0.6, (1.0, 0.85, 0.7))
light('Rim', (-up * 0.1 + fwd * 0.8 + right * 0.4), 6, 0.25, (1.0, 0.85, 0.72))

scene.render.engine = 'CYCLES'
scene.cycles.samples = int(os.environ.get('SAMPLES', 48))
scene.cycles.use_denoising = True
scene.render.resolution_x = scene.render.resolution_y = int(os.environ.get('RES', 800))
scene.view_settings.view_transform = 'AgX'
scene.view_settings.look = 'AgX - Medium High Contrast'
views = {
    'back': up * 0.75 - fwd * 0.10,
    'three_quarter': up * 0.5 - right * 0.45 + fwd * 0.25,
    'thumb_side': right * -0.70 + up * 0.15,
    'palm': -up * 0.70 + right * 0.1,
}
dist = size * 1.1
if os.environ.get('SLEEVE') == '1':               # close-ups of the cuff and forearm
    centre = wrist + (elbow - wrist) * 0.30 + (w0 - wrist) * 0.0
    dist = 0.19
    views = {'sleeve_back': up * 0.8 - right * 0.25, 'sleeve_three_quarter': up * 0.45 - right * 0.6 + fwd * 0.3,
             'sleeve_under': -up * 0.5 - right * 0.6, 'sleeve_palm': -up * 0.75 + right * 0.3}
for vname, d in views.items():
    cd = bpy.data.cameras.new(vname)
    cd.lens = 50
    co = bpy.data.objects.new(vname, cd)
    scene.collection.objects.link(co)
    co.location = centre + d.normalized() * dist * 1.9
    co.rotation_euler = (centre - co.location).to_track_quat('-Z', 'Y').to_euler()
    scene.camera = co
    scene.render.filepath = os.path.join(OUT, f'{POSE}_{vname}.png')
    bpy.ops.render.render(write_still=True)
    print('rendered', vname, flush=True)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, f'hand_{POSE}.blend'))
thumb_tip = rest('thumb_03_r').tail_local
print('verts', len(used), 'thumb on the index side:', (thumb_tip - w0).dot(side) > 0)
