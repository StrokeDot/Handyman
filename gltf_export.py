"""Export the book scene to .glb for the interactive viewport (run inside Blender).

Same job contract as book_scene.py, plus `glb_path`. Bakes the cover/spine transforms and the
page/hinge deformation into morph targets, because per-frame vertex rewriting cannot be
expressed in a .blend or carried by glTF any other way.
"""
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import book_scene as bs          # noqa: E402
import book_model as bm          # noqa: E402
import scene as scene_mod        # noqa: E402
from page_curl import sheet_vertices  # noqa: E402


def bake_morphs(ob, poses, frames, progress_of_frame):
    """Create shape keys for each pose and keyframe an adjacent-pose blend."""
    ob.shape_key_add(name='Basis', from_mix=False)
    keys = []
    for i, verts in enumerate(poses):
        sk = ob.shape_key_add(name=f'Pose{i}', from_mix=False)
        sk.data.foreach_set('co', verts.astype(np.float32).ravel())
        keys.append(sk)
    n = len(keys)
    for f in frames:
        prog = min(1.0, max(0.0, progress_of_frame(f)))
        pos = prog * (n - 1)
        lo = min(n - 2, int(math.floor(pos)))
        frac = pos - lo
        for j, sk in enumerate(keys):
            sk.value = (1.0 - frac) if j == lo else (frac if j == lo + 1 else 0.0)
            sk.keyframe_insert('value', frame=f)


def main():
    job_path = sys.argv[sys.argv.index('--') + 1]
    with open(job_path, encoding='utf-8') as fh:
        job = json.load(fh)
    glb_path = job.get('glb_path')
    if not glb_path:
        raise SystemExit('job has no glb_path')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bs.setup_render(job)
    turns, moving, root, pivot, spine_key, hinge_ob, cover_w = bs.build_book(job)
    bs.Camera(job)
    bs.setup_lights(job)
    sc = scene_mod.Scene(turns, job['book']['page_aspect'], job.get('open_at', 0.04), job['fps'],
                         job['start_hold'], job['turn_seconds'], job['pause'], job['end_hold'],
                         job.get('open_seconds', 0.0), job.get('slide', True),
                         page_count=job.get('page_count'), smoothness=job.get('smoothness', 1.0),
                         recorded_clips=job.get('recorded_clips'), clip_list=job.get('clip_list'))
    frames = list(range(sc.frames))
    poses = {f: sc.evaluate(f) for f in frames}

    # Cover: animated transform + spine shape key.
    for f in frames:
        ev = poses[f]
        pivot.rotation_euler = (0, ev['cover_angle'], 0)
        pivot.keyframe_insert('rotation_euler', frame=f)
        spine_key.value = ev['cover_angle'] / math.pi
        spine_key.keyframe_insert('value', frame=f)

    N = 9
    sample = [round(i * (sc.frames - 1) / (N - 1)) for i in range(N)]

    def sheet_prog(f):
        sp = poses[f]['sheet_progress']
        return min(1.0, max(0.0, float(sp[0]))) if sp else 0.0

    # Hinge: morph targets.
    hinge_poses = [bm.hinge_ribbon(bs.LAYOUT, poses[f]['cover_angle'])[0] for f in sample]
    bake_morphs(hinge_ob, hinge_poses, frames, lambda f: 1.0 - poses[f]['cover_angle'] / math.pi)

    # First turning sheet: morph targets.
    sheet, zr, zl = moving[0]
    sheet_poses = [sheet_vertices(sheet_prog(f), bs.PAGE_W, bs.PAGE_H, bs.GRID_X, bs.GRID_Y,
                                  zr, zl, curl=job['curl'], gutter=bs.LAYOUT.gutter)
                   for f in sample]
    bake_morphs(sheet, sheet_poses, frames, sheet_prog)

    bpy.context.scene.frame_start = 0
    bpy.context.scene.frame_end = sc.frames - 1
    bpy.context.scene.frame_set(0)
    Path(glb_path).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=glb_path, export_format='GLB', export_animations=True,
                              export_morph=True, export_yup=True, export_apply=False)
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
