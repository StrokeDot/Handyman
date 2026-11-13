# How resources/hand/hand.blend is made

Run with Python that has Blender's `bpy` module (and numpy, scipy, Pillow):

1. `build_hand2.py` - builds the hand and sleeve from the MPFB2 base mesh (CC0): male shape,
   rig, skin weights, the sleeve draped as cloth, and the skin painted from the reference photos
   (`photo_bake.py`, joint positions in `landmarks.py`). See the top of the file for its inputs.
2. `finger_rig.py in.blend out.blend` - true bending axes for the fingers and the flat / relaxed /
   pinch poses (the thumb's pinch is solved to meet the side of the index fingertip).
3. `skin_look.py in.blend out.blend` - the skin's and the suede sleeve's final materials.
4. `smooth_sleeve.py hand.blend` - calms the draped sleeve's small lumps (keeps the big folds).
5. `live_maps.py hand.blend` - bakes the render's skin (colour, creases, gloss) into pictures for the
   live view (`live_albedo.png`, `live_normal.png` with the wrinkle relief, `live_rough_ao.png`) and
   makes the sleeve's seamless cloth pictures (`live_cloth_albedo.png`, `live_cloth_normal.png`).
   Takes about half an hour (Cycles on the CPU). `RELIEF_ONLY=1 RELIEF_BASE=<baked normal copy>`
   redoes only the relief, `CLOTH_ONLY=1` only the cloth.

`pose_test.py hand.blend out_prefix` renders the three finger poses from three sides, for checking.
