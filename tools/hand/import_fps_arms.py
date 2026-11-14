"""Bring an artist-made first-person arm into the app (replaces build_hand2.py's home-made hand).

The model: "Hand With Gloves" by JUST (@teenjust500) on Sketchfab, CC BY 4.0
(https://sketchfab.com/3d-models/hand-with-gloves-5a6a434b8ec943ffacc581358781eecb) - a gloved
hand and sleeve, sculpted, rigged with three joints per finger and three forearm twist bones.

    python3 import_fps_arms.py HandWithGloves.blend textures_dir out.blend [hand_length_m]
    python3 finger_rig.py out.blend out.blend          (finger axes, flat / relaxed / pinch poses)
    python3 import_fps_arms.py --measure out.blend     (the grip's measurements, with those poses)
    python3 import_fps_arms.py --live out_dir          (the live view's pictures, from the model's)

Keeps the right arm (the app mirrors it for the left), renames its bones to the app's
(upperarm_r, lowerarm_r, lowerarm_twist_01_r / 02_r, hand_r, thumb_01_r ... pinky_03_r), merges
the bones the app does not drive (shoulder, the fingers' palm bones) into their neighbours'
weights, scales it to a real hand (wrist to middle fingertip, default 0.19 m), copies its
pictures next to out.blend (fps_*.png) and writes the measurements the app reads.
"""
import json
import math
import os
import shutil
import sys

import bpy
import bmesh  # noqa: E402  (bpy first)
import numpy as np
from mathutils import Matrix, Vector

CREDIT = ('"Hand With Gloves" by JUST (@teenjust500), Sketchfab, CC BY 4.0 - '
          'https://sketchfab.com/3d-models/hand-with-gloves-5a6a434b8ec943ffacc581358781eecb')

# app bone <- the model's bones (right side), and which bones' weights it takes over
BONES = {   # new name: (source bone for its place, parent)
    'upperarm_r': ('upperarm_L.R', None),
    'lowerarm_r': ('lowerarm_L.R', 'upperarm_r'),
    'lowerarm_twist_01_r': ('twist_arm_2_L.R', 'lowerarm_r'),
    'lowerarm_twist_02_r': ('twist_arm_3_L.R', 'lowerarm_r'),
    'hand_r': ('hand_L.R', 'lowerarm_r'),
    'thumb_01_r': ('thumb_L.R', 'hand_r'), 'thumb_02_r': ('thumb_L.002.R', 'thumb_01_r'),
    'thumb_03_r': ('thumb_L.001.R', 'thumb_02_r'),
    'index_01_r': ('index_L.003.R', 'hand_r'), 'index_02_r': ('index_L.002.R', 'index_01_r'),
    'index_03_r': ('index_L.001.R', 'index_02_r'),
    'middle_01_r': ('middle_L.003.R', 'hand_r'), 'middle_02_r': ('middle_L.002.R', 'middle_01_r'),
    'middle_03_r': ('middle_L.001.R', 'middle_02_r'),
    'ring_01_r': ('ring_L.001.R', 'hand_r'), 'ring_02_r': ('ring_L.002.R', 'ring_01_r'),
    'ring_03_r': ('ring_L.003.R', 'ring_02_r'),
    'pinky_01_r': ('pink_L.003.R', 'hand_r'), 'pinky_02_r': ('pink_L.002.R', 'pinky_01_r'),
    'pinky_03_r': ('pink_L.001.R', 'pinky_02_r'),
}
WEIGHTS = {  # new group: source groups summed into it
    'upperarm_r': ('upperarm_L.R', 'shoulder_L.R', 'body', 'pose_controller', 'camera', 'camera_target'),
    'lowerarm_r': ('twist_arm_1_L.R',),
    'lowerarm_twist_01_r': ('twist_arm_2_L.R',),
    'lowerarm_twist_02_r': ('twist_arm_3_L.R',),
    'hand_r': ('hand_L.R', 'index_L.R', 'middle_L.R', 'ring_L.R', 'pink_L.R'),
}
for _new, (_src, _p) in BONES.items():
    if _new not in WEIGHTS:
        WEIGHTS[_new] = (_src,)
MESHES = {'Hand': 'hardknuckle', 'Sleeve': 'sleeve'}


def convert(src, tex_dir, dst, hand_len):
    bpy.ops.wm.open_mainfile(filepath=src, load_ui=False, use_scripts=False)
    srig = bpy.data.objects['Armature']
    # the artist's own posed right hand (an 'OK' sign: thumb meeting the index) gives the true axis
    # each thumb joint bends about - the bones' own axes do not (finger_rig.py reads these)
    bpy.context.scene.frame_set(0)
    bpy.context.view_layer.update()
    axis_hint, angle_hint = {}, {}
    for name in ('thumb_01_r', 'thumb_02_r', 'thumb_03_r', 'index_01_r'):
        q = srig.pose.bones[BONES[name][0]].matrix_basis.to_quaternion()
        ax, ang = q.to_axis_angle()
        axis_hint[name], angle_hint[name] = list(ax), math.degrees(ang)
    srig.data.pose_position = 'REST'
    if srig.animation_data:
        srig.animation_data_clear()
    bpy.context.view_layer.update()
    Mw = srig.matrix_world
    sb = srig.data.bones

    def W(p):
        return Mw @ p
    wrist = W(sb['hand_L.R'].head_local)
    tip = W(sb['middle_L.001.R'].tail_local)
    k = hand_len / (tip - wrist).length
    origin = W(sb['upperarm_L.R'].head_local)

    def T(p):                                       # model space -> app space (metres, shoulder at 0)
        return (Vector(p) - origin) * k
    print('scale', round(k, 5), 'm per unit; forearm', round((W(sb['hand_L.R'].head_local) - W(sb['lowerarm_L.R'].head_local)).length * k, 3), 'm')
    # ---- the new rig
    arm = bpy.data.armatures.new('HandRig')
    rig = bpy.data.objects.new('HandRig', arm)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    for o in bpy.context.view_layer.objects:
        o.select_set(o is rig)
    bpy.ops.object.mode_set(mode='EDIT')
    R3 = Mw.to_3x3().normalized()
    for name, (s, parent) in BONES.items():
        b = sb[s]
        eb = arm.edit_bones.new(name)
        eb.head, eb.tail = T(W(b.head_local)), T(W(b.tail_local))
        z = (R3 @ b.matrix_local.to_3x3()).col[2].normalized()
        eb.align_roll(z)
        eb.use_deform = True
    for name, (s, parent) in BONES.items():
        if parent:
            arm.edit_bones[name].parent = arm.edit_bones[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    # ---- the meshes: right arm only, in app space, weights renamed / merged
    for new_name, src_name in MESHES.items():
        so = bpy.data.objects[src_name]
        me = so.data.copy()
        me.name = new_name
        Mo = so.matrix_world
        for v in me.vertices:
            v.co = T(Mo @ v.co)
        groups = {g.index: g.name for g in so.vertex_groups}
        n = len(me.vertices)
        wsrc = {}
        for v in me.vertices:
            for g in v.groups:
                wsrc.setdefault(groups[g.group], np.zeros(n))[v.index] = g.weight
        left = sum((w for gname, w in wsrc.items() if gname.endswith('.L')), np.zeros(n))
        right = sum((w for gname, w in wsrc.items() if gname.endswith('.R')), np.zeros(n))
        xs = np.array([v.co.x for v in me.vertices])
        keep = (right > left) | ((right == left) & (xs < 0))           # (the model's right side: x < 0)
        ob = bpy.data.objects.new(new_name, me)
        bpy.context.scene.collection.objects.link(ob)
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.verts.ensure_lookup_table()
        old_index = [v.index for v in bm.verts]
        bmesh.ops.delete(bm, geom=[bm.verts[i] for i in range(n) if not keep[i]], context='VERTS')
        bm.to_mesh(me)
        bm.free()
        kept = [i for i in old_index if keep[i]]
        ob.vertex_groups.clear()
        for gname, srcs in WEIGHTS.items():
            w = sum((wsrc[s] for s in srcs if s in wsrc), np.zeros(n))[kept]
            g = ob.vertex_groups.new(name=gname)
            for i in np.nonzero(w > 1e-4)[0]:
                g.add([int(i)], float(w[i]), 'REPLACE')
        if me.uv_layers:
            me.uv_layers[0].name = 'hand'
            if 'glove' not in me.uv_layers:
                me.uv_layers.new(name='glove')       # (the live view's glove pictures use this name)
        for p in me.polygons:
            p.use_smooth = True
        used = sorted({p.material_index for p in me.polygons})      # (drop unused slots: the glove first)
        mats = [me.materials[i] for i in used]
        remap = {old: new_i for new_i, old in enumerate(used)}
        idx = [remap[p.material_index] for p in me.polygons]
        me.materials.clear()
        for m in mats:
            me.materials.append(m)
        for p, i in zip(me.polygons, idx):
            p.material_index = i
        ob.parent = rig
        mod = ob.modifiers.new('Armature', 'ARMATURE')
        mod.object = rig
        print(new_name, 'points kept', len(me.vertices), 'of', n, 'materials', [m.name for m in me.materials if m])
    # ---- its pictures, copied next to the output
    out_dir = os.path.dirname(os.path.abspath(dst))
    for im in bpy.data.images:
        base = os.path.basename(im.filepath)
        cand = [os.path.join(tex_dir, base), os.path.join(tex_dir, base.replace('Normal.png', 'Normal_OpenGL.png'))]
        found = next((c for c in cand if os.path.exists(c)), None)
        if found:
            target = os.path.join(out_dir, 'fps_' + os.path.basename(found))
            shutil.copyfile(found, target)
            im.filepath = target                 # (made relative to the saved file below)
            im.reload()
    for m in bpy.data.materials:                 # (missing pictures: unlinked, so nothing renders pink)
        if not m.use_nodes:
            continue
        for nd in list(m.node_tree.nodes):
            if nd.type == 'TEX_IMAGE' and (nd.image is None or not os.path.exists(bpy.path.abspath(nd.image.filepath))):
                for out in nd.outputs:
                    for ln in list(out.links):
                        m.node_tree.links.remove(ln)
    # ---- the measurements the app reads (finger poses come from finger_rig.py)
    B = arm.bones
    w0 = B['hand_r'].head_local
    side = (B['index_01_r'].head_local - B['pinky_01_r'].head_local).normalized()
    fwd = (B['middle_01_r'].head_local - w0).normalized()
    up = fwd.cross(side).normalized()
    right = up.cross(fwd).normalized()
    info = dict(poses={'flat': {}, 'relaxed': {}, 'pinch': {}}, wrist=list(w0), elbow=list(B['lowerarm_r'].head_local),
                shoulder=list(B['upperarm_r'].head_local), fwd=list(fwd), up=list(up), right=list(right),
                licence=CREDIT, axis_hint=axis_hint, angle_hint=angle_hint, gloved=True)
    info.update(_tips(rig))
    rig['motioncraft_hand'] = json.dumps(info)
    # ---- keep only the new hand
    keep_obs = {'HandRig', 'Hand', 'Sleeve'}
    for o in list(bpy.data.objects):
        if o.name not in keep_obs:
            bpy.data.objects.remove(o, do_unlink=True)
    col = bpy.data.collections.new('MotionCraftHand')
    bpy.context.scene.collection.children.link(col)
    for name in ('HandRig', 'Hand', 'Sleeve'):
        o = bpy.data.objects[name]
        for c in list(o.users_collection):
            c.objects.unlink(o)
        col.objects.link(o)
    for c in list(bpy.data.collections):
        if c is not col:
            bpy.data.collections.remove(c)
    bpy.ops.outliner.orphans_purge(do_recursive=True) if hasattr(bpy.ops.outliner, 'orphans_purge') else None
    bpy.ops.wm.save_as_mainfile(filepath=dst, compress=True)
    bpy.ops.file.make_paths_relative()          # pictures found beside hand.blend, wherever it goes
    bpy.ops.wm.save_mainfile(filepath=dst, compress=True)
    print('saved', dst, [im.filepath for im in bpy.data.images if im.filepath.startswith('//fps_')][:3])


def _tips(rig):
    pb = rig.pose.bones
    bpy.context.view_layer.update()
    thumb_tip, index_tip, middle_tip = (Vector(pb[n].tail) for n in ('thumb_03_r', 'index_03_r', 'middle_03_r'))
    return dict(thumb_tip=list(thumb_tip), index_tip=list(index_tip), middle_tip=list(middle_tip),
                pinch=list(thumb_tip * 0.5 + index_tip * 0.5))


def measure(path):
    """With the finger poses in place: where thumb, index and middle tips are when pinching."""
    from mathutils import Quaternion
    bpy.ops.wm.open_mainfile(filepath=path)
    rig = bpy.data.objects['HandRig']
    info = json.loads(rig['motioncraft_hand'])
    P, axes, sp = info['poses']['pinch'], info['finger_axes'], info['spread_axes']
    for pbn in rig.pose.bones:
        pbn.rotation_mode = 'QUATERNION'
    for f in ('thumb', 'index', 'middle', 'ring', 'pinky'):
        for kk in range(3):
            name = f'{f}_0{kk + 1}_r'
            q = Quaternion(Vector(axes[name]), math.radians(P[f][kk]))
            if kk == 0:
                q = Quaternion(Vector(sp[name]), math.radians(P['spread'][f])) @ q
            rig.pose.bones[name].rotation_quaternion = q
    info.update(_tips(rig))
    for pbn in rig.pose.bones:
        pbn.rotation_quaternion = (1, 0, 0, 0)
    rig['motioncraft_hand'] = json.dumps(info)
    bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)
    print('measured', {k: [round(x, 4) for x in info[k]] for k in ('pinch', 'thumb_tip', 'index_tip')})


def live_maps(out_dir, size=2048):
    """The live view's pictures from the model's own: the glove recoloured to worn brown leather
    (Arthur Morgan's, keeping all the artist's stitching, scuffs and grain), its relief as it is,
    and the sleeve's cloth (already a dark grey-brown coat) with its relief."""
    from PIL import Image, ImageFilter

    def load(name, mode='RGB'):
        return Image.open(os.path.join(out_dir, name)).convert(mode).resize((size, size), Image.LANCZOS)
    alb = np.asarray(load('fps_glove_hardknuckle_Base_color.png'), np.float32) / 255.0
    lum = alb @ np.array((0.299, 0.587, 0.114), np.float32)
    broad = np.asarray(Image.fromarray((lum * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(24)), np.float32) / 255.0
    detail = np.clip(lum / (broad + 0.02), 0.4, 1.8)                 # (the fine detail, kept)
    tone = np.clip((broad - 0.08) / 0.55, 0, 1) ** 0.85               # dark panels .. light panels
    dark = np.array((0.155, 0.115, 0.085), np.float32)               # dark brown leather
    light = np.array((0.40, 0.31, 0.225), np.float32)                # lighter, rubbed brown
    col = (dark[None, None] * (1 - tone[..., None]) + light[None, None] * tone[..., None]) * detail[..., None]
    col = np.clip(col * 0.85 + alb.mean(2, keepdims=True) * 0.15 * detail[..., None] * 0.6, 0, 1)
    Image.fromarray((col * 255 + 0.5).astype(np.uint8)).save(os.path.join(out_dir, 'live_glove_albedo.png'), optimize=True)
    load('fps_glove_hardknuckle_Normal_OpenGL.png').save(os.path.join(out_dir, 'live_glove_normal.png'), optimize=True)
    rough = np.clip(0.72 - 0.25 * (detail - 1.0) - 0.1 * tone, 0.35, 0.9)   # worn spots a little glossier
    ra = np.stack([np.clip(0.75 + 0.25 * detail.clip(0, 1), 0, 1), rough, np.zeros_like(rough)], 2)
    Image.fromarray((ra * 255 + 0.5).astype(np.uint8)).save(os.path.join(out_dir, 'live_glove_rough_ao.png'), optimize=True)
    load('fps_sleeve_st6_generalist_Base_color.png').save(os.path.join(out_dir, 'live_sleeve_albedo.png'), optimize=True)
    load('fps_sleeve_st6_generalist_Normal_OpenGL.png').save(os.path.join(out_dir, 'live_sleeve_normal.png'), optimize=True)
    print('wrote the live view pictures in', out_dir)
    blend = os.path.join(out_dir, 'hand.blend')
    if os.path.exists(blend):                        # the render wears the same brown gloves
        bpy.ops.wm.open_mainfile(filepath=blend)
        for im in bpy.data.images:
            if os.path.basename(im.filepath) == 'fps_glove_hardknuckle_Base_color.png':
                im.filepath = '//live_glove_albedo.png'
                im.reload()
        bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)
        print('the render\'s glove now uses live_glove_albedo.png')


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--']
    if args[0] == '--measure':
        measure(args[1])
    elif args[0] == '--live':
        live_maps(args[1])
    else:
        convert(args[0], args[1], args[2], float(args[3]) if len(args) > 3 else 0.19)
    _ = Matrix
