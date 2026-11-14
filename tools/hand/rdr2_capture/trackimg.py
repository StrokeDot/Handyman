"""Per-frame (IMAGE mode) hand detection streamed from one ffmpeg pipe: trackimg.py video out.npz fps width [vf]"""
import sys, subprocess, json, numpy as np, mediapipe as mp
from mediapipe.tasks import python as mpp
from mediapipe.tasks.python import vision
video, out, fps, W = sys.argv[1], sys.argv[2], float(sys.argv[3]), int(sys.argv[4])
extra = sys.argv[5] if len(sys.argv) > 5 else ''
st = json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','json',video],capture_output=True,text=True).stdout)['streams'][0]
H = int(round(st['height'] * W / st['width'] / 2) * 2)
model = __import__('os').environ.get('HAND_MODEL', 'hand_landmarker.task')   # Google's MediaPipe model (Apache-2.0)
lm = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(base_options=mpp.BaseOptions(model_asset_path=model),
    running_mode=vision.RunningMode.IMAGE, num_hands=2, min_hand_detection_confidence=0.2, min_hand_presence_confidence=0.2))
p = subprocess.Popen(['ffmpeg','-loglevel','error','-i',video,'-vf',f'fps={fps},scale={W}:{H}{extra}','-f','rawvideo','-pix_fmt','rgb24','-'],stdout=subprocess.PIPE)
IMG, WLD, LB, SC = [], [], [], []
while True:
    raw = p.stdout.read(W * H * 3)
    if len(raw) < W * H * 3: break
    r = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.frombuffer(raw, np.uint8).reshape(H, W, 3).copy()))
    ip = np.full((2,21,3), np.nan, np.float32); wp = ip.copy(); lb = np.full(2,-1,np.int8); sc = np.zeros(2,np.float32)
    for h, (a, b, c) in enumerate(zip(r.hand_landmarks, r.hand_world_landmarks, r.handedness)):
        if h > 1: break
        ip[h] = [(q.x, q.y, q.z) for q in a]; wp[h] = [(q.x, q.y, q.z) for q in b]
        lb[h] = 1 if c[0].category_name == 'Right' else 0; sc[h] = c[0].score
    IMG.append(ip); WLD.append(wp); LB.append(lb); SC.append(sc)
np.savez(out, img=np.array(IMG), world=np.array(WLD), label=np.array(LB), score=np.array(SC), fps=fps, size=(W, H))
a = np.isfinite(np.array(IMG)[:, :, 0, 0]).any(1)
print('frames', len(a), 'with hand', int(a.sum()))
