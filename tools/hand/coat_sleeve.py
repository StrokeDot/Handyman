"""A tailored coat sleeve (step 8), replacing the draped one (whose lumps read as a sack): a clean
tube following the arm's bones, measured round the forearm's own skin so it fits with a little
ease, soft folds gathered at the inside of the elbow, and a turned-back cuff with a rolled edge
ending just short of the wrist (the glove's hem tucks under it). Bone weights flow from the
shoulder over the elbow to the forearm's twist bones; UVs are in metres (round, along) as the live
view expects.

    python3 coat_sleeve.py resources/hand/hand.blend
"""
import math
import sys

import bpy
import bmesh  # noqa: E402  (bpy first: it provides bmesh)
import numpy as np
from mathutils import Vector

AROUND = 56                 # points round the sleeve
EASE_CM = 1.1               # room between the forearm's skin and the cloth
CUFF_END_CM = 1.2           # the cuff ends this far short of the wrist
CUFF_CM = 5.0               # the turned-back cuff's height
CUFF_OUT_CM = 0.32          # ...standing this much proud of the sleeve
UPPER_R_CM = (6.4, 5.6)     # the upper arm's sleeve: half-widths (across, front-back)
SHOULDER_CM = 4.0           # the tube starts this far down from the shoulder joint


def _smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def main():
    args = [a for a in sys.argv[1:] if a != '--']
    blend = args[0]
    bpy.ops.wm.open_mainfile(filepath=blend)
    rig = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    old = bpy.data.objects['Sleeve']
    skin = bpy.data.objects['Hand']
    Mw = rig.matrix_world
    B = {b.name: (np.array(Mw @ b.head_local), np.array(Mw @ b.tail_local)) for b in rig.data.bones}
    S, E, W = B['upperarm_r'][0], B['lowerarm_r'][0], B['hand_r'][0]
    fa = (W - E) / np.linalg.norm(W - E)                       # forearm's direction
    ua = (E - S) / np.linalg.norm(E - S)
    # a frame round the forearm: 'up' = the back of the hand at rest
    side = np.array(Mw @ rig.data.bones['index_01_r'].head_local) - np.array(Mw @ rig.data.bones['pinky_01_r'].head_local)
    upv = np.cross(np.array(Mw @ rig.data.bones['middle_01_r'].head_local) - W, side)
    upv -= fa * upv.dot(fa)
    upv /= np.linalg.norm(upv)
    # the forearm's skin, measured: per angle round the arm and distance along it, how far out it is
    sk = np.array([skin.matrix_world @ v.co for v in skin.data.vertices])
    L_fa = np.linalg.norm(W - E)

    def polar(P, origin, axis, up):
        d = P - origin
        along = d @ axis
        r = d - np.outer(along, axis)
        x2 = np.cross(axis, up)
        ang = np.arctan2(r @ x2, r @ up)
        return along, ang, np.linalg.norm(r, axis=1)
    al, an, rr = polar(sk, E, fa, upv)
    A_BINS = AROUND
    T_BINS = 24
    prof = np.zeros((T_BINS, A_BINS))
    tb = np.clip(((al / L_fa) * T_BINS).astype(int), -1, T_BINS)
    ab = ((an + math.pi) / (2 * math.pi) * A_BINS).astype(int) % A_BINS
    for t in range(T_BINS):
        for a in range(A_BINS):
            sel = (tb == t) & (ab == a)
            prof[t, a] = rr[sel].max() if sel.any() else np.nan
    for t in range(T_BINS):                                       # (gaps: from the neighbours)
        row = prof[t]
        if np.isnan(row).all():
            prof[t] = prof[t - 1] if t else 0.03
            continue
        idx = np.where(~np.isnan(row))[0]
        prof[t] = np.interp(np.arange(A_BINS), idx, row[idx], period=A_BINS)
    from scipy.ndimage import gaussian_filter
    prof = gaussian_filter(prof, (1.2, 1.5), mode=('nearest', 'wrap'))

    def forearm_r(t_share, a_idx):
        t = min(T_BINS - 1, max(0.0, t_share * T_BINS - 0.5))
        t0 = int(t)
        t1 = min(T_BINS - 1, t0 + 1)
        w = t - t0
        return prof[t0, a_idx] * (1 - w) + prof[t1, a_idx] * w
    # ---- rings along the arm: (centre, axis, up, radius per angle, share along forearm)
    cm = 0.01
    end = L_fa - CUFF_END_CM * cm
    rings = []
    n_up, n_el, n_fa = 14, 10, 40
    L_ua = np.linalg.norm(E - S)
    for i in range(n_up):                                         # upper arm
        s = SHOULDER_CM * cm + (L_ua - SHOULDER_CM * cm - 4 * cm) * i / (n_up - 1)
        rings.append(('up', S + ua * s, ua, s / L_ua))
    for i in range(n_el):                                         # round the elbow: axis blends
        u = (i + 0.5) / n_el
        ax = ua * (1 - _smooth(u)) + fa * _smooth(u)
        ax /= np.linalg.norm(ax)
        c = E + ua * (-4 * cm) * (1 - u) * (1 - u) + fa * (4 * cm) * u * u
        rings.append(('elbow', c, ax, u))
    for i in range(n_fa):                                         # forearm to the cuff
        d = 4 * cm + (end - 4 * cm) * i / (n_fa - 1)
        rings.append(('fore', E + fa * d, fa, d / L_fa))
    # the elbow's crease side: where the forearm folds towards the upper arm
    inner = -ua - fa * (-ua).dot(fa)
    inner /= np.linalg.norm(inner) + 1e-9
    verts, ws, uvs_v = [], [], []
    rng = np.random.default_rng(5)
    phase = rng.uniform(0, 2 * math.pi, 6)
    total_len = 0.0
    prev_c = None
    for ri, (kind, c, ax, share) in enumerate(rings):
        up = upv - ax * upv.dot(ax)
        up /= np.linalg.norm(up)
        x2 = np.cross(ax, up)
        if prev_c is not None:
            total_len += np.linalg.norm(c - prev_c)
        prev_c = c
        ring = []
        for a in range(AROUND):
            ang = -math.pi + 2 * math.pi * (a + 0.5) / AROUND
            dirv = up * math.cos(ang) + x2 * math.sin(ang)
            ra, rb = UPPER_R_CM[1] * cm, UPPER_R_CM[0] * cm
            r_up = 1.0 / math.sqrt((math.cos(ang) / ra) ** 2 + (math.sin(ang) / rb) ** 2)
            if kind == 'fore':
                r_fa = forearm_r(share, a) + EASE_CM * cm
                # (wider towards the elbow, as a coat sleeve tapers to the cuff)
                r_fa *= 1.0 + 0.10 * (1 - share)
                w_up = 1 - _smooth((share * L_fa - 4 * cm) / (10 * cm) + 1)
                r = r_fa * (1 - w_up) + r_up * w_up
            elif kind == 'elbow':
                r = r_up * (1 - share) + (forearm_r(0.15, a) + EASE_CM * cm) * 1.1 * share
                r = max(r, r_up * 0.92)
            else:
                r = r_up
            # soft folds: gathered at the inside of the elbow, gentle elsewhere
            crease = max(0.0, dirv.dot(inner))
            el = math.exp(-((total_len - (L_ua - 4 * cm + 2 * cm)) / (6 * cm)) ** 2)
            r += cm * (0.35 * el * crease * math.sin(total_len / (1.7 * cm) * 2 * math.pi + 0.7 * ang)
                       + 0.10 * math.sin(ang * 3 + phase[0] + total_len * 18) + 0.07 * math.sin(ang * 5 + phase[1] - total_len * 26))
            # the cuff: proud of the sleeve, a soft step at its top
            if kind == 'fore':
                to_end = (end - share * L_fa) / cm
                r += CUFF_OUT_CM * cm * _smooth((CUFF_CM - to_end) / 0.5)
            ring.append(c + dirv * r)
        verts.append(ring)
        # bone weights
        if kind == 'up':
            wv = {'upperarm_r': 1.0}
        elif kind == 'elbow':
            wv = {'upperarm_r': 1 - _smooth(share), 'lowerarm_r': _smooth(share)}
        else:
            centres = (('lowerarm_r', 0.0), ('lowerarm_twist_01_r', 1 / 3), ('lowerarm_twist_02_r', 2 / 3))
            sh = [max(0.0, 1 - abs(share - cc) * 3) for _, cc in centres]
            if share >= 2 / 3:
                sh = [0, 0, 1]
            tot = sum(sh) or 1
            wv = {n: s / tot for (n, _), s in zip(centres, sh) if s > 1e-4}
        ws.append(wv)
        uvs_v.append(total_len)
    # the rolled edge: the cloth turns inwards at the cuff's end (two more rings, inside)
    last = np.array(verts[-1])
    c_end = rings[-1][1]
    for k, (back_cm, inset) in enumerate(((0.25, 0.25), (1.4, 0.55))):
        ring = []
        for p in last:
            d = p - c_end
            rad = np.linalg.norm(d)
            ring.append(c_end - fa * back_cm * cm + d / rad * (rad - inset * cm))
        verts.append(ring)
        ws.append(ws[-1])
        uvs_v.append(uvs_v[-1] + 0.3 * cm * (k + 1))
    # ---- build the mesh
    me = bpy.data.meshes.new('CoatSleeve')
    bm = bmesh.new()
    bv = [[bm.verts.new(Vector(p)) for p in ring] for ring in verts]
    bm.verts.ensure_lookup_table()
    uvl = bm.loops.layers.uv.new('uv')
    circ = 2 * math.pi * 0.045
    for i in range(len(bv) - 1):
        for a in range(AROUND):
            b2 = (a + 1) % AROUND
            f = bm.faces.new((bv[i][a], bv[i][b2], bv[i + 1][b2], bv[i + 1][a]))
            for loop, (ii, aa) in zip(f.loops, ((i, a), (i, a + 1), (i + 1, a + 1), (i + 1, a))):
                loop[uvl].uv = (circ * aa / AROUND, uvs_v[ii])
    bm.normal_update()
    bm.faces.ensure_lookup_table()
    # outward normals: faces should face away from the arm's axis
    f0 = bm.faces[0]
    if f0.normal.dot(f0.calc_center_median() - Vector(rings[0][1])) < 0:
        for f in bm.faces:
            f.normal_flip()
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    # ---- swap it into the Sleeve object (same name, material, collection)
    old_me = old.data
    mats = list(old_me.materials)
    old.data = me
    for m in mats:
        me.materials.append(m)
    for vg in list(old.vertex_groups):
        old.vertex_groups.remove(vg)
    names = ['upperarm_r', 'lowerarm_r', 'lowerarm_twist_01_r', 'lowerarm_twist_02_r']
    groups = {n: old.vertex_groups.new(name=n) for n in names}
    to_local = old.matrix_world.inverted()
    for v in me.vertices:
        v.co = to_local @ v.co
    for i, wv in enumerate(ws):
        for a in range(AROUND):
            for n, w in wv.items():
                groups[n].add([i * AROUND + a], w, 'REPLACE')
    for m in list(old.modifiers):
        if m.type != 'ARMATURE':
            old.modifiers.remove(m)
    if not any(m.type == 'ARMATURE' for m in old.modifiers):
        mod = old.modifiers.new('Armature', 'ARMATURE')
        mod.object = rig
    if old_me.users == 0:
        bpy.data.meshes.remove(old_me)
    bpy.ops.wm.save_mainfile(filepath=blend)
    print('coat sleeve:', len(me.vertices), 'points,', len(me.polygons), 'faces; modifiers', [m.type for m in old.modifiers])


if __name__ == '__main__':
    main()
