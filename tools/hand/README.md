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

## Testing a page turn

`turn_test.py base_job.json out_dir [--durations 0.5,1.0,2.0] [--style under|on] [--render]` - an
isolated scene with one page turned over and then back, at each speed; measures whether thumb and
finger stay on the same spot of the paper while holding it (slip), how far they are from it, the
hand cutting through any page, and that every frame is the same whichever way you scrub; with
`--render` it renders the key moments of both turns.

## Finger poses from a filmed page turn

`capture.py video.mp4 hand_landmarker.task out_dir` - tracks a real hand turning pages (filmed
from above) with MediaPipe's hand landmarker (`pip install mediapipe`; the model file is Google's,
Apache-2.0, downloaded separately and never shipped with the app) and writes each finger's bend
while holding the page's edge, pushing it over, pressing and returning, plus how long each part
took, an overlay sheet to check the tracking and the curves over time. `hand_scene.CAPTURED_GRIP`
came from it. Game footage with gloved hands is not tracked: film a bare hand.
