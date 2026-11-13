"""Arthur Morgan style leather gloves for the hand (step 7): pictures on the hand's UV map 'glove'
(an even unwrap of the hand made for them - the skin's own map squeezes a few faces), made
from the hand mesh itself (no outside pictures), so the glove fits the hand exactly:

    live_glove_albedo.png     dark, worn brown leather - lighter and greyer where it rubs (the
                              knuckles, the finger tips and pads), darker in the creases
    live_glove_normal.png     its relief: pebbled grain, creases across every finger joint,
                              stitched seams along the fingers' sides, the hem's rolled edge
    live_glove_rough_ao.png   red: shadowing (the hand's baked AO), green: roughness (worn spots
                              polished, creases dull)

    python3 glove_maps.py resources/hand/hand.blend [size] [--repair-skin]
--repair-skin first fills the skin's own baked pictures past their islands' edges (once, after
live_maps.py: the bake leaves them black there, which shows as dark squares in the live view).
The glove ends a few cm past the wrist (under the coat's cuff); beyond it the skin's own picture.
"""
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

HEM_CM = 5.0            # the glove reaches this far past the wrist towards the elbow
LEATHER = np.array((0.245, 0.212, 0.182))        # grey-brown worn leather (sampled from RDR2's glove)
WORN = np.array((0.40, 0.375, 0.345))            # rubbed pale grey
CREASE = np.array((0.12, 0.10, 0.088))


def raster(ob, size, uv_name='glove'):
    """Per texel: the rest position (metres, mesh space) of the surface there, and a mask - from
    the mesh as the live view draws it (smoothed once: its picture coordinates shift a little)."""
    keep = {m.name: m.show_viewport for m in ob.modifiers}
    for m in ob.modifiers:
        m.show_viewport = m.type == 'SUBSURF'
        if m.type == 'SUBSURF':
            m.levels = 1
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    me.calc_loop_triangles()
    uvl = me.uv_layers[uv_name].data
    P = np.zeros((size, size, 3), np.float32)
    N = np.zeros((size, size, 3), np.float32)
    M = np.zeros((size, size), bool)
    co = np.array([v.co[:] for v in me.vertices], np.float32)
    nr = np.array([v.normal[:] for v in me.vertices], np.float32)
    for tri in me.loop_triangles:
        uv = np.array([uvl[li].uv[:] for li in tri.loops], np.float64) * size     # (u right, v up)
        vs = list(tri.vertices)
        x0, y0 = np.floor(uv.min(0)).astype(int)
        x1, y1 = np.ceil(uv.max(0)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, size - 1), min(y1, size - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        (ax, ay), (bx, by), (cx, cy) = uv
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            continue
        w0 = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / den
        w1 = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / den
        w2 = 1 - w0 - w1
        ins = (w0 >= -1e-3) & (w1 >= -1e-3) & (w2 >= -1e-3)
        if not ins.any():
            continue
        W = np.stack([w0[ins], w1[ins], w2[ins]], 1)
        rr, cc = (ys[ins] - 0.5).astype(int), (xs[ins] - 0.5).astype(int)
        P[rr, cc] = W @ co[vs]
        N[rr, cc] = W @ nr[vs]
        M[rr, cc] = True
    ev.to_mesh_clear()
    for m in ob.modifiers:
        m.show_viewport = keep[m.name]
    return P, N, M


def fill_out(a, mask, steps=12):
    """Spread values past the islands' edges (no dark seams when the picture is filtered)."""
    from scipy import ndimage
    idx = ndimage.distance_transform_edt(~mask, return_distances=False, return_indices=True)
    return a[tuple(idx)]


def periodic_noise(n, scale, rng):
    f = np.fft.fftfreq(n)
    fx, fy = np.meshgrid(f, f)
    r = np.sqrt(fx ** 2 + fy ** 2) * n
    x = np.real(np.fft.ifft2(np.fft.fft2(rng.standard_normal((n, n))) * np.exp(-(r / scale) ** 2)))
    return (x - x.mean()) / (x.std() + 1e-9)


def repair_skin_maps(out_dir):
    """The skin's baked pictures (live_maps.py) were baked a little inside the picture's islands,
    black beyond: the live view's smoothed hand samples there in places (dark squares). Spread
    each picture outwards from its baked texels (from well inside, past the bake's own edge)."""
    from PIL import Image
    from scipy import ndimage
    alb = np.asarray(Image.open(os.path.join(out_dir, 'live_albedo.png')).convert('RGB'), np.float32)
    valid = ndimage.binary_erosion(alb.sum(2) > 12.0, iterations=2)
    for name in ('live_albedo.png', 'live_normal.png', 'live_rough_ao.png'):
        path = os.path.join(out_dir, name)
        px = np.asarray(Image.open(path).convert('RGB'))
        Image.fromarray(np.ascontiguousarray(fill_out(px, valid))).save(path, optimize=True)
        print('repaired', name, flush=True)


def noise3(P, scale, seed=0):
    """Smooth value noise over the surface's own 3D positions (metres; features about scale apart):
    the same on both sides of any edge of the picture's islands. The lattice is turned at random
    (no grain lined up with the axes). About -1..1."""
    rot = np.linalg.qr(np.random.default_rng(seed + 101).standard_normal((3, 3)))[0]
    p = (P.reshape(-1, 3).astype(np.float64) @ rot) / scale
    i = np.floor(p).astype(np.int64)
    f = p - i
    f = f * f * (3 - 2 * f)
    i = i + 1_000_000

    def h(dx, dy, dz):                       # an integer hash of the lattice point (even, no streaks)
        x = (i[:, 0] + dx) * 73856093 ^ (i[:, 1] + dy) * 19349663 ^ (i[:, 2] + dz) * 83492791 ^ (seed * 2654435761)
        x = (x ^ (x >> 13)) * 1274126177
        x = x ^ (x >> 16)
        return (x & 0xFFFFFF).astype(np.float64) / float(0xFFFFFF)
    x00 = h(0, 0, 0) * (1 - f[:, 0]) + h(1, 0, 0) * f[:, 0]
    x10 = h(0, 1, 0) * (1 - f[:, 0]) + h(1, 1, 0) * f[:, 0]
    x01 = h(0, 0, 1) * (1 - f[:, 0]) + h(1, 0, 1) * f[:, 0]
    x11 = h(0, 1, 1) * (1 - f[:, 0]) + h(1, 1, 1) * f[:, 0]
    y0 = x00 * (1 - f[:, 1]) + x10 * f[:, 1]
    y1 = x01 * (1 - f[:, 1]) + x11 * f[:, 1]
    v = y0 * (1 - f[:, 2]) + y1 * f[:, 2]
    return (v.reshape(P.shape[:2]) * 2.0 - 1.0).astype(np.float32)


def fbm3(P, scale, octaves=3, seed=0):
    out = np.zeros(P.shape[:2], np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        out += amp * noise3(P, scale / 2 ** o, seed + o)
        tot += amp
        amp *= 0.5
    out /= tot
    return (out - out.mean()) / (out.std() + 1e-9)


def main():
    from PIL import Image
    from scipy import ndimage
    args = [a for a in sys.argv[1:] if a != '--']
    blend = args[0]
    size = int(args[1]) if len(args) > 1 and args[1].isdigit() else 2048
    out_dir = os.path.dirname(os.path.abspath(blend))
    if '--repair-skin' in sys.argv:
        repair_skin_maps(out_dir)
    bpy.ops.wm.open_mainfile(filepath=blend)
    ob = bpy.data.objects['Hand']
    rig = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    to_mesh = ob.matrix_world.inverted() @ rig.matrix_world
    bone = {b.name: (to_mesh @ b.head_local, to_mesh @ b.tail_local) for b in rig.data.bones}
    P, Nrm, M = raster(ob, size)
    print('texels on the hand', int(M.sum()), flush=True)
    wrist = np.array(bone['hand_r'][0])
    elbow = np.array(bone['lowerarm_r'][0])
    axis = (wrist - elbow) / np.linalg.norm(wrist - elbow)
    t = (P - wrist) @ axis * 100.0                                  # cm past the wrist (+ towards the fingers)
    # (the back of the hand's side: from the palm towards the back)
    side = np.array(bone['index_01_r'][0]) - np.array(bone['pinky_01_r'][0])
    fwd = np.array(bone['middle_01_r'][0]) - wrist
    up = np.cross(fwd, side)
    up /= np.linalg.norm(up)
    back = (Nrm @ up)                                               # +1 back of the hand, -1 palm
    glove = M & (t > -HEM_CM)
    # ---- joints: distance to each finger joint, and how far along the finger past it
    crease_h = np.zeros((size, size), np.float32)
    wear = np.zeros((size, size), np.float32)
    on_finger = np.zeros((size, size), bool)                        # (seams run along the fingers only)
    finger_along = np.zeros((size, size), np.float32)               # (cm along the finger there)
    wobble = fbm3(P, 0.004, 2, seed=11)
    uneven = np.clip(0.55 + 0.45 * fbm3(P, 0.005, 2, seed=13), 0.1, 1.0)
    for f in ('thumb', 'index', 'middle', 'ring', 'pinky'):
        for k in (1, 2, 3):
            h0, h1 = (np.array(v) for v in bone[f'{f}_0{k}_r'])
            ax = (h1 - h0) / (np.linalg.norm(h1 - h0) + 1e-9)
            d = P - h0
            along = d @ ax * 100.0                                  # cm along the finger from the joint
            radial = np.linalg.norm(d - np.outer(d.reshape(-1, 3) @ ax, ax).reshape(d.shape), axis=2) * 100.0
            near = np.exp(-(along / (0.55 if k > 1 else 0.8)) ** 2) * (radial < 1.6)
            seg = np.linalg.norm(h1 - h0) * 100.0
            here = (along > (0.4 if k == 1 else -0.2)) & (along < seg + 0.3) & (radial < 1.3) & (f != 'thumb' or k > 1)
            on_finger |= here
            finger_along = np.where(here, along + 10.0 * k, finger_along)
            # creases: fine ridges across the finger at the joint, deeper on the palm side
            depth = 0.6 + 0.4 * np.clip(-back, 0, 1)
            wob = along + 0.09 * wobble                             # (wavy, uneven - not rings)
            crease_h += near * depth * uneven * (0.5 + 0.5 * np.cos(wob * 2 * np.pi / 0.36))
            if k == 1 or k == 2:                                    # knuckles rub pale on the back
                wear += np.exp(-(along / 0.9) ** 2 - (radial / 1.6) ** 2 * 0.0) * np.clip(back, 0, 1) * (radial < 1.8)
        tip = np.array(bone[f'{f}_03_r'][1])
        dt = np.linalg.norm(P - tip, axis=2) * 100.0
        wear += np.exp(-(dt / 1.1) ** 2) * 1.2                      # finger ends and pads
    wear += 0.35 * np.exp(-((t - 6.0) / 3.0) ** 2) * np.clip(-back, 0, 1)   # the palm's heel
    mott = fbm3(P, 0.012, 3, seed=1)
    wear = np.clip(wear * (0.75 + 0.35 * mott), 0, 1) * glove
    # ---- grain: pebbled leather (cells), a finer pore, and broad wrinkles
    grain = 1.0 - np.abs(fbm3(P, 0.0013, 2, seed=2))                # ~0.6 mm pebbles (on the surface itself)
    pore = fbm3(P, 0.0007, 1, seed=5)
    broad = fbm3(P, 0.009, 3, seed=7)
    # ---- seams: down each finger's sides (where its surface turns from the back to the palm), a
    # groove with a row of stitches beside it
    side_band = glove & on_finger
    groove = np.exp(-(back / 0.05) ** 2) * side_band
    stitch = (np.sin(finger_along * 2 * np.pi / 0.32) > 0.15) * np.exp(-((np.abs(back) - 0.13) / 0.035) ** 2) * side_band
    # ---- the hem: a rolled edge, then the skin beyond
    hem = np.exp(-((t + HEM_CM - 0.35) / 0.25) ** 2) * M
    # ---- height and normal (texels: rows are v upwards, as built)
    h = (0.55 * grain + 0.18 * pore + 0.35 * broad) * glove
    h += 2.2 * crease_h * glove
    h -= 3.0 * groove
    h += 1.6 * stitch
    h += 3.5 * hem
    h = ndimage.gaussian_filter(h, 0.7)
    gy, gx = np.gradient(h)
    k = 0.9
    n = np.stack([-gx * k, -gy * k, np.ones_like(h)], 2)
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    # ---- colour, roughness
    shade = 1.0 + 0.10 * broad + 0.06 * pore - 0.25 * np.clip(crease_h, 0, 1)
    col = LEATHER[None, None, :] * shade[..., None]
    col = col * (1 - wear[..., None]) + WORN[None, None, :] * (0.85 + 0.2 * grain[..., None]) * wear[..., None]
    col = col * (1 - 0.6 * np.clip(crease_h, 0, 1)[..., None]) + CREASE * 0.6 * np.clip(crease_h, 0, 1)[..., None]
    col = col * (1 - 0.5 * groove[..., None])
    col = col + np.array((0.42, 0.36, 0.28)) * 0.45 * stitch[..., None]      # pale thread
    skin = np.array((0.60, 0.44, 0.35))                                         # (the arm under the sleeve)
    edge = np.clip((t + HEM_CM) / 0.15, 0, 1)[..., None]                       # glove .. skin at the hem
    col = col * edge + skin * (1 - edge)
    rough = 0.74 - 0.16 * wear + 0.12 * np.clip(crease_h, 0, 1) + 0.04 * pore      # (matte, almost suede)
    rough = rough * edge[..., 0] + 0.5 * (1 - edge[..., 0])
    ao = 1.0 - 0.3 * np.clip(crease_h, 0, 1) - 0.4 * groove
    n = n * edge + np.array((0.0, 0.0, 1.0)) * (1 - edge)
    # (outside the islands: copied from just inside the nearest island)
    inner = ndimage.binary_erosion(M, iterations=2)
    col, rough, ao = fill_out(col, inner), fill_out(rough, inner), fill_out(ao, inner)
    n = fill_out(n, inner)

    def save(px, name):
        a = np.clip(px[::-1] * 255.0 + 0.5, 0, 255).astype(np.uint8)
        Image.fromarray(a).save(os.path.join(out_dir, name), optimize=True)
        print('wrote', name, flush=True)
    save(np.clip(col, 0, 1), 'live_glove_albedo.png')
    save(n * 0.5 + 0.5, 'live_glove_normal.png')
    save(np.stack([ao, np.clip(rough, 0, 1), np.zeros_like(ao)], 2), 'live_glove_rough_ao.png')
    _ = Vector


if __name__ == '__main__':
    main()
