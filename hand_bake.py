"""Bake the hands' movement for the live view (run by Blender, no rendering).

The same planning code as the render (journal_scene.make_hands) poses the hands for every frame;
this writes, for each hand, its meshes (the skin a little smoothed, the sleeve), their bone
weights and pictures, and every deforming bone's matrix on every frame. The live view then bends
the meshes itself (live_hands.py), so the hands in the live view move exactly as in the video.

    blender -b --factory-startup -P hand_bake.py -- job.json
The job is a render job (blender_bridge.make_job) with 'hand_bake_out': the .npz to write.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Matrix  # noqa: E402

import journal_geom as G  # noqa: E402
import journal_scene as JS  # noqa: E402

MAX_INFLUENCES = 4


def _mesh_data(ob, bone_index, smooth_levels):
    """(rest positions in the mesh's own space, corner -> vertex, corner UVs, bone ids, weights)."""
    mods = {m.type: m for m in ob.modifiers}
    keep = {}
    for m in ob.modifiers:
        keep[m.name] = m.show_viewport
        m.show_viewport = m.type == 'SUBSURF' and smooth_levels > 0
        if m.type == 'SUBSURF':
            m.levels = smooth_levels
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    pos = np.array([v.co[:] for v in me.vertices], np.float32)
    uv_layer = me.uv_layers.get('hand') or me.uv_layers.get('uv') or me.uv_layers.active
    corners, uvs = [], []
    for tri in me.loop_triangles:
        for li in tri.loops:
            corners.append(me.loops[li].vertex_index)
            uvs.append(uv_layer.data[li].uv[:] if uv_layer else (0.0, 0.0))
    names = {g.index: g.name for g in ob.vertex_groups}
    bi = np.zeros((len(me.vertices), MAX_INFLUENCES), np.int16)
    bw = np.zeros((len(me.vertices), MAX_INFLUENCES), np.float32)
    for v in me.vertices:
        ws = sorted(((g.weight, bone_index[names[g.group]]) for g in v.groups
                     if names.get(g.group) in bone_index and g.weight > 1e-4), reverse=True)[:MAX_INFLUENCES]
        tot = sum(w for w, _ in ws) or 1.0
        for k, (w, b) in enumerate(ws):
            bi[v.index, k], bw[v.index, k] = b, w / tot
    ev.to_mesh_clear()
    for m in ob.modifiers:
        m.show_viewport = keep[m.name]
    _ = mods
    return pos, np.array(corners, np.int32), np.array(uvs, np.float32), bi, bw


def _skin_picture(hand, out_dir, tag):
    """The bare skin's colour picture, saved small for the live view (None if none)."""
    ob = next(o for o in hand.objects if o.type == 'MESH' and not o.name.startswith('Sleeve'))
    nt = ob.data.materials[0].node_tree
    img = next((n.image for n in nt.nodes if n.type == 'TEX_IMAGE' and n.image and 'colour' in n.image.name), None)
    if img is None:
        return None
    path = os.path.join(out_dir, f'hand_skin_{tag}.png')
    copy = img.copy()
    copy.scale(1024, 1024)
    copy.filepath_raw = path
    copy.file_format = 'PNG'
    copy.save()
    return path


def main():
    job_path = sys.argv[sys.argv.index('--') + 1]
    with open(job_path, encoding='utf-8') as fh:
        job = json.load(fh)
    out_path = job['hand_bake_out']
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.engine = 'CYCLES'
    root, _pivot, _sp, _core, obs, strap = JS.build(job)
    sc = JS.job_scene(job)
    starts_closed = sc.evaluate(0)['cover_progress'] < 1.0 - 1e-6
    c_start = next((f for f in range(sc.frames) if sc.evaluate(f)['cover_progress'] > 1e-6), 0)
    strap_u = [JS.strap_u_at(f, c_start, job['fps'], starts_closed) for f in range(sc.frames)] if strap else None
    held_up = bool(job.get('hand_left', True)) and job.get('hand_left_style') == 'under'
    hand, hand_plan, left, left_plan = JS.make_hands(dict(job, hand=True), root, sc, len(obs), strap_u, held_up)
    data = {'frames': np.int32(sc.frames)}
    meta = {'frames': sc.frames, 'hands': []}
    root_inv = root.matrix_world.inverted()
    for tag, h, plan in (('R', hand, hand_plan), ('L', left, left_plan)):
        if h is None:
            continue
        rig = h.rig
        bones = [b.name for b in rig.data.bones if b.use_deform]
        index = {n: i for i, n in enumerate(bones)}
        A = root_inv @ rig.matrix_world
        parts = []
        for ob in h.objects:
            if ob.type != 'MESH':
                continue
            part = 'sleeve' if ob.name.startswith('Sleeve') else 'skin'
            pos, corners, uvs, bi, bw = _mesh_data(ob, index, 0 if part == 'sleeve' else 1)
            key = f'{tag}_{part}'
            data[key + '_pos'], data[key + '_corner'], data[key + '_uv'] = pos, corners, uvs
            data[key + '_bi'], data[key + '_bw'] = bi, bw
            # per bone: mesh space -> armature rest -> (posed) -> book space
            B = [rig.data.bones[n].matrix_local.inverted() @ rig.matrix_world.inverted() @ ob.matrix_world
                 for n in bones]
            parts.append((key, B))
        mats = {key: np.zeros((sc.frames, len(bones), 4, 4), np.float32) for key, _ in parts}
        for f in range(sc.frames):
            if f % 20 == 0:                                       # the app shows how far along it is
                done = (len(meta['hands']) + f / sc.frames) / (2 if left is not None else 1)
                print(f'PROGRESS {done:.3f}', flush=True)
            h.apply(plan[min(f, len(plan) - 1)])
            bpy.context.view_layer.update()
            P = [rig.pose.bones[n].matrix for n in bones]
            for key, B in parts:
                for i in range(len(bones)):
                    mats[key][f, i] = np.array(A @ P[i] @ B[i], np.float32)
        for key, m in mats.items():
            data[key + '_mats'] = m
        meta['hands'].append(dict(tag=tag, parts=[k for k, _ in parts],
                                  skin_picture=job.get('hand_skin') or _skin_picture(h, os.path.dirname(out_path), tag),
                                  skin_is_photo=not job.get('hand_skin'),
                                  sleeve_picture=job.get('hand_sleeve')))
    data['meta'] = np.frombuffer(json.dumps(meta).encode('utf-8'), np.uint8)
    tmp = out_path + '.part.npz'
    np.savez_compressed(tmp, **data)
    os.replace(tmp, out_path)
    print('DONE', out_path, flush=True)
    _ = (G, Matrix)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:            # the app shows this line
        import traceback
        traceback.print_exc()
        print(f'ERROR hand bake failed: {exc}', flush=True)
        sys.exit(1)
