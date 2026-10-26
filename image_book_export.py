"""Image-first glTF export for the app: your artwork on boards, procedural pages, baked hinge.

Reads the same job contract as book_scene.py plus `glb_path`, builds the hybrid book from the
template's artwork and the job's page images, bakes the animations to morph targets and
exports a .glb for the interactive viewport.
"""
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import book_model as bm           # noqa: E402
from page_curl import sheet_vertices, layout_pages  # noqa: E402

SHEETS = 12
GAP = 0.0016
GUT = 0.02
NFRAMES = 60
NPOSE = 9


def mat_image(name, path, fallback_colour):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    b = nt.nodes.get('Principled BSDF')
    if path:
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = bpy.data.images.load(str(path), check_existing=True)
        tex.interpolation = 'Cubic'
        nt.links.new(tex.outputs['Color'], b.inputs['Base Color'])
    elif b:
        b.inputs['Base Color'].default_value = fallback_colour
    if b:
        b.inputs['Roughness'].default_value = 0.62
    return mat


def mat_flat(name, colour):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    b = mat.node_tree.nodes.get('Principled BSDF')
    if b:
        b.inputs['Base Color'].default_value = colour
        b.inputs['Roughness'].default_value = 0.9
    return mat


def uv_quad(mesh):
    uv = mesh.uv_layers.new(name='UVMap')
    for poly in mesh.polygons:
        for j, li in enumerate(poly.loop_indices):
            uv.data[li].uv = ((0, 0), (1, 0), (1, 1), (0, 1))[j % 4]


def board(name, x0, x1, ext, inter, edge, parent, z0=0.0):
    z1 = z0 + T
    verts = [(x0, -CH / 2, z0), (x1, -CH / 2, z0), (x1, CH / 2, z0), (x0, CH / 2, z0),
             (x0, -CH / 2, z1), (x1, -CH / 2, z1), (x1, CH / 2, z1), (x0, CH / 2, z1)]
    faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    uv_quad(mesh)
    for m in (ext, inter, edge):
        mesh.materials.append(m)
    for i, poly in enumerate(mesh.polygons):
        poly.material_index = 0 if i == 0 else (1 if i == 1 else 2)
    ob = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(ob)
    if parent:
        ob.parent = parent
    return ob


def spine(parent, mat):
    seg = 16
    verts, faces = [], []
    for j in range(2):
        y = -CH / 2 + j * CH
        for i in range(seg + 1):
            a = math.pi * i / seg
            verts.append((-GUT * math.cos(a), y, T / 2 + GUT * math.sin(a)))
    for i in range(seg):
        faces.append((i, i + 1, seg + 2 + i, seg + 1 + i))
    mesh = bpy.data.meshes.new('Spine')
    mesh.from_pydata(verts, [], faces)
    uv_quad(mesh)
    mesh.materials.append(mat)
    ob = bpy.data.objects.new('Spine', mesh)
    bpy.context.scene.collection.objects.link(ob)
    if parent:
        ob.parent = parent


def hinge_strip(parent, mat):
    verts, faces = bm.hinge_ribbon(L, math.pi)
    mesh = bpy.data.meshes.new('Hinge')
    mesh.from_pydata(verts.tolist(), [], faces)
    uv_quad(mesh)
    mesh.materials.append(mat)
    ob = bpy.data.objects.new('Hinge', mesh)
    bpy.context.scene.collection.objects.link(ob)
    if parent:
        ob.parent = parent
    return ob


def page_stack(parent, paper, edge):
    top = T + 0.0006 + SHEETS * GAP
    for side, x0, x1 in ((1, GUT, W), (-1, -W, -GUT)):
        verts = [(x0, -H / 2, T), (x1, -H / 2, T), (x1, H / 2, T), (x0, H / 2, T),
                 (x1, -H / 2, top), (x1, H / 2, top), (x0, H / 2, top), (x0, -H / 2, top)]
        faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                 (2, 3, 7, 6), (3, 0, 4, 7)]
        mesh = bpy.data.meshes.new(f'Block{side}')
        mesh.from_pydata(verts, [], faces)
        uv_quad(mesh)
        mesh.materials.append(paper)
        mesh.materials.append(edge)
        for p in mesh.polygons[2:]:
            p.material_index = 1
        ob = bpy.data.objects.new(f'Block{side}', mesh)
        bpy.context.scene.collection.objects.link(ob)
        if parent:
            ob.parent = parent
    return top


def main():
    job = json.loads(Path(sys.argv[sys.argv.index('--') + 1]).read_text(encoding='utf-8'))
    book = job['book']
    images = job.get('images') or []
    glb_path = job.get('glb_path')
    if not glb_path:
        raise SystemExit('job has no glb_path')
    global W, H, T, CH, CW, L
    L = bm.Layout(float(book.get('page_aspect', 1.4)), max(1, layout_pages(len(images))[0]), 0.04)
    W, H = L.page_w, L.page_h
    M = bm.COVER_MARGIN
    CW, CH = W + M, H + 2 * M
    T = bm.COVER_T
    HINGE = L.hinge

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.eevee.taa_render_samples = 8
    scene.render.film_transparent = True
    scene.render.resolution_x, scene.render.resolution_y = 480, 270
    scene.view_settings.view_transform = 'Standard'
    root = bpy.data.objects.new('Book', None)
    scene.collection.objects.link(root)

    leather = tuple(float(c) for c in book.get('leather_color', (0.4, 0.2, 0.08))) + (1.0,)
    leather_img = book.get('leather_image')
    fe = mat_image('FrontExt', book.get('front_exterior_image') or leather_img, leather)
    be = mat_image('BackExt', book.get('back_exterior_image') or leather_img, leather)
    fi = mat_image('FrontIn', book.get('front_interior_image') or book.get('inside_leather_image'), leather)
    bi = mat_image('BackIn', book.get('back_interior_image') or book.get('inside_leather_image'), leather)
    sp = mat_image('SpineArt', book.get('spine_exterior_image') or leather_img, leather)
    paper = mat_flat('Paper', (0.88, 0.82, 0.68, 1))
    edge = mat_flat('PaperEdge', (0.74, 0.66, 0.52, 1))

    board('BackBoard', GUT, CW - GUT, be, bi, edge, root)
    pivot = bpy.data.objects.new('FrontHinge', None)
    scene.collection.objects.link(pivot)
    pivot.parent = root
    pivot.location = (-CW + GUT, 0, HINGE)
    board('FrontBoard', 0, CW - 2 * GUT, fe, fi, edge, pivot, z0=-T / 2)
    spine(root, sp)
    hinge_ob = hinge_strip(root, sp)
    top_z = page_stack(root, paper, edge)

    # Turning sheet with the first page image.
    first = images[0] if images else None
    page_mat = mat_image('PageArt', first, (0.88, 0.82, 0.68, 1))
    v = sheet_vertices(0.0, W, H, 9, 5, top_z + 0.001, top_z + 0.001, curl=0.9, gutter=L.gutter)
    mesh = bpy.data.meshes.new('TurningSheet')
    faces = [(j * 10 + i, j * 10 + i + 1, (j + 1) * 10 + i + 1, (j + 1) * 10 + i)
             for j in range(4) for i in range(9)]
    mesh.from_pydata(v.tolist(), [], faces)
    uv_quad(mesh)
    mesh.materials.append(page_mat)
    turn = bpy.data.objects.new('TurningSheet', mesh)
    scene.collection.objects.link(turn)
    turn.parent = root

    # Bake cover + page turn.
    for f in range(NFRAMES):
        pivot.rotation_euler = (0, math.pi * (1 - f / (NFRAMES - 1)), 0)
        pivot.keyframe_insert('rotation_euler', frame=f)
    turn.shape_key_add(name='Basis', from_mix=False)
    keys = []
    for i in range(NPOSE):
        t = i / (NPOSE - 1)
        sk = turn.shape_key_add(name=f'Pose{i}', from_mix=False)
        vv = sheet_vertices(t, W, H, 9, 5, top_z + 0.001, top_z + 0.001, curl=0.9, gutter=L.gutter)
        sk.data.foreach_set('co', vv.astype(np.float32).ravel())
        keys.append(sk)
    for f in range(NFRAMES):
        t = min(1.0, max(0.0, (f - NFRAMES * 0.4) / (NFRAMES * 0.6)))
        pos = t * (NPOSE - 1)
        lo = min(NPOSE - 2, int(math.floor(pos)))
        frac = pos - lo
        for j, sk in enumerate(keys):
            sk.value = (1 - frac) if j == lo else (frac if j == lo + 1 else 0.0)
            sk.keyframe_insert('value', frame=f)

    scene.frame_start = 0
    scene.frame_end = NFRAMES - 1
    scene.frame_set(0)
    # Hinge morph targets.
    hinge_ob.shape_key_add(name='Basis', from_mix=False)
    hkeys = []
    for i in range(NPOSE):
        ang = math.pi * (1 - i / (NPOSE - 1))
        sk = hinge_ob.shape_key_add(name=f'HPose{i}', from_mix=False)
        hv, _ = bm.hinge_ribbon(L, ang)
        sk.data.foreach_set('co', hv.astype(np.float32).ravel())
        hkeys.append(sk)
    for f in range(NFRAMES):
        prog = f / (NFRAMES - 1)
        pos = prog * (NPOSE - 1)
        lo = min(NPOSE - 2, int(math.floor(pos)))
        frac = pos - lo
        for j, sk in enumerate(hkeys):
            sk.value = (1 - frac) if j == lo else (frac if j == lo + 1 else 0.0)
            sk.keyframe_insert('value', frame=f)
    Path(glb_path).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=glb_path, export_format='GLB', export_animations=True,
                              export_morph=True, export_yup=True, export_apply=False)
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
