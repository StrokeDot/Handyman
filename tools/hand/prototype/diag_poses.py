"""Phase 1: the arm alone, bent at the elbow / wrist / twisted, rendered (Workbench) to see how the
skin and the sleeve deform. python3 diag_poses.py -- out_dir"""
import math, os, sys
import bpy
from mathutils import Quaternion, Vector
out = sys.argv[-1]; os.makedirs(out, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath='/home/claude/handyman/resources/hand/hand.blend')
sc = bpy.context.scene
sc.render.engine = 'BLENDER_WORKBENCH'
sc.display.shading.light = 'STUDIO'; sc.display.shading.color_type = 'MATERIAL'
sc.display.shading.show_cavity = True; sc.display.shading.cavity_type = 'BOTH'
sc.render.resolution_x, sc.render.resolution_y = 520, 400
sc.render.film_transparent = False
rig = bpy.data.objects['HandRig']
pb = rig.pose.bones
for b in pb:
    b.rotation_mode = 'QUATERNION'
Mw = rig.matrix_world
S = Mw @ rig.data.bones['upperarm_r'].head_local
E = Mw @ rig.data.bones['lowerarm_r'].head_local
W = Mw @ rig.data.bones['hand_r'].head_local
cam_d = bpy.data.cameras.new('c'); cam = bpy.data.objects.new('cam', cam_d); sc.collection.objects.link(cam); sc.camera = cam
cam_d.lens = 50
def look(frm, to):
    cam.location = frm
    cam.rotation_mode = 'QUATERNION'
    cam.rotation_quaternion = (Vector(to) - Vector(frm)).to_track_quat('-Z', 'Y')
def reset():
    for b in pb:
        b.rotation_quaternion = (1, 0, 0, 0); b.location = (0, 0, 0)
def pose(name, elbow=0.0, wrist_x=0.0, wrist_z=0.0, twist=0.0, axis='X'):
    reset()
    ax = Vector((1, 0, 0)) if axis == 'X' else Vector((0, 0, 1))
    pb['lowerarm_r'].rotation_quaternion = Quaternion(ax, math.radians(elbow)) @ Quaternion((0, 1, 0), math.radians(twist * 0.1))
    pb['lowerarm_twist_01_r'].rotation_quaternion = Quaternion((0, 1, 0), math.radians(twist * 0.35))
    pb['lowerarm_twist_02_r'].rotation_quaternion = Quaternion((0, 1, 0), math.radians(twist * 0.7))
    pb['hand_r'].rotation_quaternion = Quaternion((1, 0, 0), math.radians(wrist_x)) @ Quaternion((0, 0, 1), math.radians(wrist_z)) @ Quaternion((0, 1, 0), math.radians(twist * 0.3))
    bpy.context.view_layer.update()
POSES = [('straight', {}), ('elbow 45', dict(elbow=45)), ('elbow 90', dict(elbow=90)), ('elbow 120', dict(elbow=120)),
         ('elbow 90 (other axis)', dict(elbow=90, axis='Z')), ('wrist up 50', dict(wrist_x=50)), ('wrist down 50', dict(wrist_x=-50)),
         ('wrist side 30', dict(wrist_z=30)), ('twist +70', dict(twist=70)), ('twist -70', dict(twist=-70)),
         ('elbow 90 + twist 60', dict(elbow=90, twist=60)), ('elbow 90 + wrist up 40', dict(elbow=90, wrist_x=40))]
mid = (S + W) / 2
arm_dir = (W - S).normalized()
side = arm_dir.cross(Vector((0, 1, 0))).normalized()
views = {'side': mid + Vector((0, -0.9, 0)), 'top': mid + side * 0.9}
for i, (name, kw) in enumerate(POSES):
    pose(name, **kw)
    for vn, at in views.items():
        look(at, mid)
        sc.render.filepath = os.path.join(out, f'{i:02d}_{vn}.png')
        bpy.ops.render.render(write_still=True)
    # close-up of the elbow and of the cuff
    Ep = rig.matrix_world @ pb['lowerarm_r'].head
    Wp = rig.matrix_world @ pb['hand_r'].head
    look(Ep + Vector((0, -0.28, 0.05)), Ep); sc.render.filepath = os.path.join(out, f'{i:02d}_elbow.png'); bpy.ops.render.render(write_still=True)
    look(Wp + Vector((0, -0.25, 0.06)), Wp); sc.render.filepath = os.path.join(out, f'{i:02d}_cuff.png'); bpy.ops.render.render(write_still=True)
open(os.path.join(out, 'poses.txt'), 'w').write('\n'.join(n for n, _ in POSES))
print('done', len(POSES))
