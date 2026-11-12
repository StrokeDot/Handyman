# How resources/hand/hand.blend is made

Run with Python that has Blender's `bpy` module (and numpy, scipy, Pillow):

1. `build_hand2.py` - builds the hand and sleeve from the MPFB2 base mesh (CC0): male shape,
   rig, skin weights, the sleeve draped as cloth, and the skin painted from the reference photos
   (`photo_bake.py`, joint positions in `landmarks.py`). See the top of the file for its inputs.
2. `finger_rig.py in.blend out.blend` - true bending axes for the fingers and the flat / relaxed /
   pinch poses (the thumb's pinch is solved to meet the side of the index fingertip).
3. `skin_look.py in.blend out.blend` - the skin's and the suede sleeve's final materials.

`pose_test.py hand.blend out_prefix` renders the three finger poses from three sides, for checking.
