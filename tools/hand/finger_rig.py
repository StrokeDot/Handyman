"""Give the hand natural fingers: each finger bends about its true bending axis (not the bone's
own X axis, which is 10-30 degrees off and made the fingers claw sideways), the fingers come
together from the model's splayed rest pose, and the three poses (flat, relaxed, pinch) are
redone: a relaxed hand is gently curved, a pinching hand holds the page between thumb and index
with the other fingers loosely curved behind (not a fist). The thumb's pinch is solved so its
tip meets the index finger's pad.

    python3 finger_rig.py in.blend out.blend
"""
import json
import math
import sys

import bpy
import numpy as np
from mathutils import Quaternion, Vector
from scipy.optimize import minimize

src, dst = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.open_mainfile(filepath=src)
rig = bpy.data.objects['HandRig']
info = json.loads(rig['motioncraft_hand'])
B = rig.data.bones
FINGERS = ('thumb', 'index', 'middle', 'ring', 'pinky')
wr = B['hand_r'].head_local
side = (B['index_01_r'].head_local - B['pinky_01_r'].head_local).normalized()
fwd = (B['middle_01_r'].head_local - wr).normalized()
up = fwd.cross(side).normalized()             # back of the hand
side = up.cross(fwd).normalized()

# fingertips converge a little towards the thumb's root as they curl (degrees; + = towards the index)
CONVERGE = {'index': -3.0, 'middle': 0.0, 'ring': 4.0, 'pinky': 8.0}

axes, spread_axes = {}, {}
for f in FINGERS:
    for k in (1, 2, 3):
        name = f'{f}_0{k}_r'
        M = B[name].matrix_local.to_3x3()
        y = M.col[1].normalized()
        if f == 'thumb':
            flex = M.col[0].normalized()            # the thumb's own axis already bends it across the palm
        else:
            flex = up.cross(y).normalized()         # perpendicular to the finger, in the palm's plane
            c = math.radians(CONVERGE[f])
            flex = (flex * math.cos(c) - fwd * math.sin(c)).normalized()
        axes[name] = list(M.transposed() @ flex)
        sp = (up - y * up.dot(y)).normalized()      # sideways swing about the palm's normal
        spread_axes[name] = list(M.transposed() @ sp)

for pb in rig.pose.bones:
    pb.rotation_mode = 'QUATERNION'


def set_pose(pose):
    for f in FINGERS:
        for k in range(3):
            name = f'{f}_0{k + 1}_r'
            q = Quaternion(Vector(axes[name]), math.radians(pose[f][k]))
            if k == 0:
                q = Quaternion(Vector(spread_axes[name]), math.radians(pose['spread'][f])) @ q
            rig.pose.bones[name].rotation_quaternion = q
    bpy.context.view_layer.update()


def P(name, end='tail'):
    return Vector(getattr(rig.pose.bones[name], end))


flat = {'thumb': [0, 4, 4], 'index': [2, 3, 2], 'middle': [2, 3, 2], 'ring': [3, 4, 2], 'pinky': [4, 5, 3],
        'spread': {'thumb': -12, 'index': -9, 'middle': -1, 'ring': 4, 'pinky': 6}}
relaxed = {'thumb': [5, 8, 10], 'index': [8, 10, 5], 'middle': [10, 12, 6], 'ring': [11, 14, 7],
           'pinky': [13, 16, 8], 'spread': {'thumb': -16, 'index': -10, 'middle': -1, 'ring': 5, 'pinky': 7}}
pinch = {'thumb': [0, 0, 0], 'index': [28, 32, 14], 'middle': [18, 22, 10], 'ring': [19, 24, 11],
         'pinky': [21, 26, 12], 'spread': {'thumb': 0, 'index': -10, 'middle': -2, 'ring': 4, 'pinky': 6}}


# the page is held between the thumb's pad and the side of the index fingertip (a paper pinch):
# the thumb sits this way from the index tip (hand frame: forward, back of hand, towards the index)
PINCH_DIR = (-0.07, -0.40, 0.91)
PINCH_GAP_M = 0.0115


def thumb_cost(x):
    p = json.loads(json.dumps(pinch))
    p['thumb'] = [x[0], x[1], x[2]]
    p['spread']['thumb'] = x[3]
    p['index'] = [x[4], x[5], 0.45 * x[5]]
    set_pose(p)
    d = (fwd * PINCH_DIR[0] + up * PINCH_DIR[1] + side * PINCH_DIR[2]).normalized()
    target = P('index_03_r') + d * PINCH_GAP_M
    tip = P('thumb_03_r')
    # a little preference for moderate bends
    return (tip - target).length ** 2 * 1e4 + 1e-5 * sum(v * v for v in x[:4]) + 6e-5 * (x[4] ** 2 + x[5] ** 2)


best = None
for x0 in ([10, 20, 20, -25, 35, 45], [20, 30, 30, -35, 40, 50], [0, 10, 10, -15, 30, 40], [15, 25, 30, 0, 40, 50], [35, -10, 0, 0, 45, 55]):
    r = minimize(thumb_cost, x0, method='Nelder-Mead', options=dict(maxiter=800, xatol=0.05, fatol=1e-8))
    if best is None or r.fun < best.fun:
        best = r
x = best.x
pinch['thumb'] = [round(float(v), 1) for v in x[:3]]
pinch['spread']['thumb'] = round(float(x[3]), 1)
pinch['index'] = [round(float(x[4]), 1), round(float(x[5]), 1), round(0.45 * float(x[5]), 1)]
set_pose(pinch)
gap = (P('thumb_03_r') - P('index_03_r')).length
ax_ = (P('index_03_r') - P('thumb_03_r')).normalized()
print('index pinch', pinch['index'], 'thumb pinch', pinch['thumb'], 'spread', pinch['spread']['thumb'], 'cost', best.fun, 'tip gap cm', round(gap * 100, 2),
      'axis (fwd, up, side)', [round(ax_.dot(v), 2) for v in (fwd, up, side)])

info['poses'] = {'flat': flat, 'relaxed': relaxed, 'pinch': pinch}
info['finger_axes'] = axes
info['spread_axes'] = spread_axes
rig['motioncraft_hand'] = json.dumps(info)
for pb in rig.pose.bones:
    pb.rotation_quaternion = (1, 0, 0, 0)
bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(filepath=dst, compress=True)
print('saved', dst)
