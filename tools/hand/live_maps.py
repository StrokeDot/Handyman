"""Bake the skin's full render material into pictures for the live view (step 4, after skin_look.py).

The render's skin is built from many pieces (the photo colour, its tone and redness, darker
creases, wrinkle / detail / pore relief, glossier nails). The live view cannot run that, so this
bakes it, on the hand at rest, into three pictures next to hand.blend:

    live_albedo.png   the skin's colour (as the render's Base Color)
    live_normal.png   its relief (tangent space, UV map 'hand')
    live_rough_ao.png red: how shadowed each spot is (ambient occlusion), green: roughness

    python3 live_maps.py resources/hand/hand.blend [size]
Also writes the sleeve's cloth pictures (live_cloth_albedo.png, live_cloth_normal.png): a
seamless brushed wool-and-suede weave made here (no outside pictures).
"""
import os
import sys

import bpy
import numpy as np


def bake_skin(blend, size):
    bpy.ops.wm.open_mainfile(filepath=blend)
    out_dir = os.path.dirname(os.path.abspath(blend))
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = 64
    sc.render.bake.margin = 8
    ob = bpy.data.objects['Hand']
    for m in ob.modifiers:
        if m.type == 'SUBSURF':
            m.levels = m.render_levels = 2
    ob.data.uv_layers.active = ob.data.uv_layers['hand']
    for o in bpy.data.objects:
        o.hide_render = o is not ob and o.type == 'MESH'
        o.select_set(o is ob)
    bpy.context.view_layer.objects.active = ob
    nt = ob.data.materials[0].node_tree
    tex = nt.nodes.new('ShaderNodeTexImage')
    nt.nodes.active = tex

    def bake(kind, name, colorspace='sRGB', samples=1, **kw):
        sc.cycles.samples = samples
        img = bpy.data.images.new(name, size, size, alpha=False, float_buffer=colorspace != 'sRGB')
        img.colorspace_settings.name = colorspace
        tex.image = img
        tex.select = True
        nt.nodes.active = tex
        bpy.ops.object.bake(type=kind, **kw)
        px = np.array(img.pixels[:], np.float32).reshape(size, size, 4)[:, :, :3]
        print('baked', name, px.mean(axis=(0, 1)), flush=True)
        return px

    albedo = bake('DIFFUSE', 'live_albedo', samples=16, pass_filter={'COLOR'})   # (its creases use AO)
    normal = bake('NORMAL', 'live_normal', 'Non-Color', normal_space='TANGENT')
    rough = bake('ROUGHNESS', 'live_rough', 'Non-Color')
    ao = bake('AO', 'live_ao', 'Non-Color', samples=24)
    from PIL import Image

    def save(px, name):
        a = np.clip(px[::-1] * 255.0 + 0.5, 0, 255).astype(np.uint8)
        Image.fromarray(a).save(os.path.join(out_dir, name), optimize=True)
        print('wrote', name, flush=True)
    save(albedo, 'live_albedo.png')
    save(normal, 'live_normal.png')
    save(np.stack([ao[:, :, 0], rough[:, :, 0], np.zeros_like(ao[:, :, 0])], 2), 'live_rough_ao.png')
    return out_dir


def relief(blend, size, strength=(0.9, 0.4)):
    """The live view's relief picture: the render's own wrinkle and detail height pictures (same
    UV map) turned into normals - a little stronger than the render's very fine bump, which the
    live view's simple light would otherwise lose - over the baked normals."""
    from PIL import Image
    bpy.ops.wm.open_mainfile(filepath=blend)
    out_dir = os.path.dirname(os.path.abspath(blend))

    def height(name):
        img = bpy.data.images[name]
        w, h = img.size
        px = np.array(img.pixels[:], np.float32).reshape(h, w, img.channels)[:, :, :3].mean(2)
        im = Image.fromarray(px).resize((size, size), Image.BILINEAR)
        return np.asarray(im, np.float32)                  # rows bottom-up, as Blender keeps them

    total_x = np.zeros((size, size), np.float32)
    total_y = np.zeros((size, size), np.float32)
    for name, k in zip(('hand_wrinkles.png', 'hand_detail.png'), strength):
        hgt = height(name)
        gy, gx = np.gradient(hgt)                          # per pixel, along u (x) and v (y, upwards)
        total_x += gx * k * size / 1024.0
        total_y += gy * k * size / 1024.0
    # (the baked normals as bake_skin left them; RELIEF_BASE: a saved copy, so this can be re-run)
    src = os.environ.get('RELIEF_BASE') or os.path.join(out_dir, 'live_normal.png')
    base = np.asarray(Image.open(src).convert('RGB'), np.float32) / 127.5 - 1.0
    base = base[::-1]                                       # (saved top-down) -> bottom-up
    n = np.stack([base[:, :, 0] - total_x, base[:, :, 1] - total_y, np.maximum(base[:, :, 2], 0.2)], 2)
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    a = np.clip((n[::-1] * 0.5 + 0.5) * 255 + 0.5, 0, 255).astype(np.uint8)
    Image.fromarray(a).save(os.path.join(out_dir, 'live_normal.png'), optimize=True)
    print('wrote live_normal.png (with relief)', float(np.abs(total_x).mean()), flush=True)


def _periodic_noise(n, scale, rng):
    """Seamless noise: white noise filtered in frequency space (wraps at the edges)."""
    f = np.fft.fftfreq(n)
    fx, fy = np.meshgrid(f, f)
    r = np.sqrt(fx ** 2 + fy ** 2) * n
    w = np.exp(-(r / scale) ** 2)
    x = np.real(np.fft.ifft2(np.fft.fft2(rng.standard_normal((n, n))) * w))
    return (x - x.mean()) / (x.std() + 1e-9)


def cloth(out_dir, n=1024, seed=7):
    """A seamless sleeve cloth: a fine diagonal twill under a soft brushed nap, gently mottled."""
    from PIL import Image
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:n, 0:n].astype(np.float32)
    threads = 96                                              # weave repeats across the picture
    twill = np.sin(2 * np.pi * (x + y) * threads / n) * 0.5 + 0.5
    warp = np.sin(2 * np.pi * x * threads * 2 / n) * 0.5 + 0.5
    weave = 0.65 * twill + 0.35 * warp * twill
    nap = _periodic_noise(n, n / 6.0, rng)                    # fine fibres
    streak = _periodic_noise(n, n / 40.0, rng)                # brushed streaks (stretched along y)
    streak = np.roll(np.repeat(streak[::8], 8, axis=0), 4, axis=0)
    mottle = _periodic_noise(n, 6.0, rng)                     # broad patches
    height = 0.55 * weave + 0.18 * nap + 0.12 * streak + 0.15 * mottle
    shade = 1.0 + 0.055 * mottle + 0.05 * nap + 0.08 * (weave - 0.5)
    base = np.array((0.205, 0.158, 0.118), np.float32)        # dark greyish-brown wool (an Arthur Morgan coat)
    albedo = np.clip(base[None, None, :] * shade[:, :, None], 0, 1)
    gy, gx = np.gradient(np.pad(height, 1, mode='wrap'))
    gx, gy = gx[1:-1, 1:-1], gy[1:-1, 1:-1]
    k = 1.6
    nrm = np.stack([-gx * k, -gy * k, np.ones_like(gx)], 2)
    nrm /= np.linalg.norm(nrm, axis=2, keepdims=True)
    for name, px in (('live_cloth_albedo.png', albedo), ('live_cloth_normal.png', nrm * 0.5 + 0.5)):
        Image.fromarray(np.clip(px * 255 + 0.5, 0, 255).astype(np.uint8)).save(os.path.join(out_dir, name), optimize=True)
        print('wrote', name, flush=True)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--']
    blend = args[0]
    size = int(args[1]) if len(args) > 1 else 2048
    d = os.path.dirname(os.path.abspath(blend))
    if os.environ.get('CLOTH_ONLY') != '1' and os.environ.get('RELIEF_ONLY') != '1':
        d = bake_skin(blend, size)
    if os.environ.get('CLOTH_ONLY') != '1':
        relief(blend, size)
    cloth(d)
