"""A more natural look for the hand's skin and the sleeve.

Skin: a touch less orange; knuckles and fingertips a little redder (where the skin is thin and
the shape sticks out), creases a little darker; light goes further into the skin (the glow at the
edges of fingers); a thin oily layer for skin's soft highlights; fine pores.
Sleeve (suede): mottled colour where the nap lies differently, a soft sheen at grazing angles,
darker in the folds, worn lighter on the edges that stick out, and the nap's fine texture.

    python3 skin_look.py in.blend out.blend
"""
import sys

import bpy

src, dst = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.open_mainfile(filepath=src)


def node(nt, kind, name, loc, **inputs):
    n = nt.nodes.new(kind)
    n.name = n.label = name
    n.location = loc
    for k, v in inputs.items():
        n.inputs[k].default_value = v
    return n


def mix(nt, name, loc, blend, fac=1.0):
    n = nt.nodes.new('ShaderNodeMix')
    n.data_type = 'RGBA'
    n.blend_type = blend
    n.name = n.label = name
    n.location = loc
    n.inputs['Factor'].default_value = fac
    return n


def map_range(nt, name, loc, a, b, c, d):
    n = nt.nodes.new('ShaderNodeMapRange')
    n.name = n.label = name
    n.location = loc
    n.clamp = True
    for k, v in zip(('From Min', 'From Max', 'To Min', 'To Max'), (a, b, c, d)):
        n.inputs[k].default_value = v
    return n


# ------------------------------------------------------------------ skin
skin = next(o for o in bpy.data.objects if o.type == 'MESH' and not o.name.startswith('Sleeve'))
nt = skin.data.materials[0].node_tree
L = nt.links
bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
photo = nt.nodes['Image Texture.002']                       # the colour painted from the photos
geo = node(nt, 'ShaderNodeNewGeometry', 'SkinGeometry', (-900, 700))
hs = node(nt, 'ShaderNodeHueSaturation', 'SkinTone', (-500, 600), Hue=0.5, Saturation=0.84, Value=1.0, Fac=1.0)
L.new(photo.outputs['Color'], hs.inputs['Color'])
# thin skin that sticks out (knuckles, fingertips): a little redder
red_f = map_range(nt, 'SkinRedness', (-700, 800), 0.5, 0.6, 0.0, 0.4)
L.new(geo.outputs['Pointiness'], red_f.inputs['Value'])
red = mix(nt, 'SkinRed', (-300, 650), 'MULTIPLY')
red.inputs['B'].default_value = (1.0, 0.8, 0.76, 1.0)
L.new(red_f.outputs['Result'], red.inputs['Factor'])
L.new(hs.outputs['Color'], red.inputs['A'])
# creases: a little darker
ao = node(nt, 'ShaderNodeAmbientOcclusion', 'SkinAO', (-700, 950))
ao.inputs['Distance'].default_value = 0.006
ao.samples = 8
ao_f = map_range(nt, 'SkinCrease', (-500, 950), 0.55, 1.0, 0.8, 1.0)
L.new(ao.outputs['AO'], ao_f.inputs['Value'])
dark = mix(nt, 'SkinCreaseDark', (-100, 650), 'MULTIPLY')
L.new(red.outputs['Result'], dark.inputs['A'])
L.new(ao_f.outputs['Result'], dark.inputs['B'])
L.new(dark.outputs['Result'], bsdf.inputs['Base Color'])
# light into the skin, an oily layer, slightly glossier
bsdf.inputs['Subsurface Weight'].default_value = 0.45
bsdf.inputs['Subsurface Radius'].default_value = (1.0, 0.38, 0.22)
bsdf.inputs['Subsurface Scale'].default_value = 0.007
bsdf.inputs['Coat Weight'].default_value = 0.1
bsdf.inputs['Coat Roughness'].default_value = 0.32
bsdf.inputs['Coat IOR'].default_value = 1.4
rough_src = bsdf.inputs['Roughness'].links[0].from_socket
rm = node(nt, 'ShaderNodeMath', 'SkinGloss', (-150, 200))
rm.operation = 'MULTIPLY'
rm.inputs[1].default_value = 0.92
L.new(rough_src, rm.inputs[0])
L.new(rm.outputs['Value'], bsdf.inputs['Roughness'])
# pores
tc = node(nt, 'ShaderNodeTexCoord', 'SkinCoord', (-900, -600))
pn = node(nt, 'ShaderNodeTexNoise', 'SkinPores', (-700, -600))
pn.inputs['Scale'].default_value = 2600.0
pn.inputs['Detail'].default_value = 2.0
L.new(tc.outputs['Object'], pn.inputs['Vector'])
pb = node(nt, 'ShaderNodeBump', 'SkinPoreBump', (-300, -500))
pb.inputs['Strength'].default_value = 0.035
pb.inputs['Distance'].default_value = 0.0003
L.new(pn.outputs['Fac'], pb.inputs['Height'])
last = bsdf.inputs['Normal'].links[0].from_socket
L.new(last, pb.inputs['Normal'])
L.new(pb.outputs['Normal'], bsdf.inputs['Normal'])

# ------------------------------------------------------------------ sleeve
sl = next(o for o in bpy.data.objects if o.type == 'MESH' and o.name.startswith('Sleeve'))
nt = sl.data.materials[0].node_tree
L = nt.links
bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
nt.nodes['Mix'].name = 'FabricColour'                       # where a picked fabric picture goes in
nt.nodes['FabricColour'].label = 'FabricColour'
base = bsdf.inputs['Base Color'].links[0].from_socket       # fabric with its stitches
tc = node(nt, 'ShaderNodeTexCoord', 'NapCoord', (-900, 900))
geo = node(nt, 'ShaderNodeNewGeometry', 'NapGeometry', (-900, 1100))
# mottling: patches where the nap lies differently
mo = node(nt, 'ShaderNodeTexNoise', 'NapMottle', (-700, 900))
mo.inputs['Scale'].default_value = 16.0
mo.inputs['Detail'].default_value = 4.0
mo.inputs['Roughness'].default_value = 0.6
L.new(tc.outputs['Object'], mo.inputs['Vector'])
mo_f = map_range(nt, 'NapMottleRange', (-500, 900), 0.3, 0.7, 0.78, 1.14)
L.new(mo.outputs['Fac'], mo_f.inputs['Value'])
m1 = mix(nt, 'NapMottleMix', (-200, 800), 'MULTIPLY')
L.new(base, m1.inputs['A'])
L.new(mo_f.outputs['Result'], m1.inputs['B'])
# folds darker
ao = node(nt, 'ShaderNodeAmbientOcclusion', 'NapAO', (-700, 1250))
ao.inputs['Distance'].default_value = 0.025
ao.samples = 8
ao_f = map_range(nt, 'NapFoldRange', (-500, 1250), 0.4, 1.0, 0.62, 1.0)
L.new(ao.outputs['AO'], ao_f.inputs['Value'])
m2 = mix(nt, 'NapFoldMix', (0, 800), 'MULTIPLY')
L.new(m1.outputs['Result'], m2.inputs['A'])
L.new(ao_f.outputs['Result'], m2.inputs['B'])
# worn lighter where it sticks out (fold ridges, the cuff's edge)
wf = map_range(nt, 'NapWornRange', (-500, 1450), 0.52, 0.62, 0.0, 0.35)
L.new(geo.outputs['Pointiness'], wf.inputs['Value'])
m3 = mix(nt, 'NapWornMix', (200, 800), 'SCREEN')
m3.inputs['B'].default_value = (0.32, 0.22, 0.14, 1.0)
L.new(wf.outputs['Result'], m3.inputs['Factor'])
L.new(m2.outputs['Result'], m3.inputs['A'])
L.new(m3.outputs['Result'], bsdf.inputs['Base Color'])
# suede's soft sheen at grazing angles, slightly less matte
bsdf.inputs['Sheen Weight'].default_value = 0.42
bsdf.inputs['Sheen Roughness'].default_value = 0.62
bsdf.inputs['Sheen Tint'].default_value = (0.92, 0.78, 0.64, 1.0)
bsdf.inputs['Roughness'].default_value = 0.86
# the nap's fine texture
nn = node(nt, 'ShaderNodeTexNoise', 'NapFibres', (-700, -700))
nn.inputs['Scale'].default_value = 1900.0
nn.inputs['Detail'].default_value = 1.5
L.new(tc.outputs['Object'], nn.inputs['Vector'])
nb = node(nt, 'ShaderNodeBump', 'NapBump', (-300, -600))
nb.inputs['Strength'].default_value = 0.1
nb.inputs['Distance'].default_value = 0.0004
L.new(nn.outputs['Fac'], nb.inputs['Height'])
last = bsdf.inputs['Normal'].links[0].from_socket
L.new(last, nb.inputs['Normal'])
L.new(nb.outputs['Normal'], bsdf.inputs['Normal'])

bpy.ops.wm.save_as_mainfile(filepath=dst, compress=True)
print('saved', dst)
