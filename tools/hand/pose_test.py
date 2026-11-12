import bpy, json, sys, math
from mathutils import Quaternion, Vector
bpy.ops.wm.open_mainfile(filepath=sys.argv[-2]); out = sys.argv[-1]
sc = bpy.context.scene; rig = bpy.data.objects['HandRig']; info = json.loads(rig['motioncraft_hand'])
b = rig.data.bones
wr = b['hand_r'].head_local; mid = b['middle_01_r'].head_local; side = b['index_01_r'].head_local - b['pinky_01_r'].head_local
fwd = (mid - wr).normalized(); up = fwd.cross(side).normalized(); right = up.cross(fwd)
centre = wr + fwd * 0.08
w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True
w.node_tree.nodes['Background'].inputs['Color'].default_value = (0.2, 0.2, 0.22, 1)
sc.render.engine = 'BLENDER_EEVEE' if 'BLENDER_EEVEE' in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items] else 'CYCLES'
sc.render.engine = 'CYCLES'; sc.cycles.samples = 8; sc.render.resolution_x = sc.render.resolution_y = 360
ld = bpy.data.lights.new('s', 'SUN'); ld.energy = 3; lo = bpy.data.objects.new('s', ld); sc.collection.objects.link(lo)
cd = bpy.data.cameras.new('c'); cd.lens = 50; co = bpy.data.objects.new('c', cd); sc.collection.objects.link(co); sc.camera = co
for pb in rig.pose.bones: pb.rotation_mode = 'QUATERNION'
P = info['poses']
for name in ('flat', 'relaxed', 'pinch'):
    for f in ('thumb', 'index', 'middle', 'ring', 'pinky'):
        for k in range(3):
            bn = f'{f}_0{k+1}_r'
            ax = Vector(info['finger_axes'][bn]) if 'finger_axes' in info else Vector((1, 0, 0))
            q = Quaternion(ax, math.radians(P[name][f][k]))
            if k == 0 and 'spread' in P[name]:
                q = Quaternion(Vector(info['spread_axes'][bn]), math.radians(P[name]['spread'][f])) @ q
            rig.pose.bones[bn].rotation_quaternion = q
    for vn, d in (('palm', -up), ('side', -right * 0.7 - up * 0.4), ('back', up * 0.8 + right * 0.5 - fwd * 0.5)):
        co.location = centre + d.normalized() * 0.32; co.rotation_euler = (centre - co.location).to_track_quat('-Z', 'Y').to_euler()
        lo.rotation_euler = (centre - co.location).to_track_quat('-Z', 'Y').to_euler()
        sc.render.filepath = f'{out}_{name}_{vn}.png'; bpy.ops.render.render(write_still=True)
