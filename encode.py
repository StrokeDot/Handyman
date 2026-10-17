"""Turns the transparent PNG frames into videos Filmora can layer over footage.

Same approach as StrokeScribe's tested export: ProRes 4444 (.mov) keeps full-quality
transparency; VP9 WebM is much smaller and also transparent.
"""
import json
import shutil
import subprocess
from pathlib import Path

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def find_ffmpeg():
    return shutil.which('ffmpeg')


def _run(cmd, what):
    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
    if result.returncode:
        raise RuntimeError(f'{what} failed: ' + result.stderr[-1500:])


def encode_mov(folder, fps, name='page_turn_prores4444.mov'):
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError('FFmpeg was not found on PATH. The PNG frames were kept.')
    folder = Path(folder)
    out = folder / name
    _run([ffmpeg, '-n', '-hide_banner', '-loglevel', 'error', '-framerate', str(fps),
          '-i', str(folder / 'frame_%06d.png'), '-c:v', 'prores_ks', '-profile:v', '4',
          '-pix_fmt', 'yuva444p10le', '-alpha_bits', '16', '-threads', '0', str(out)], 'ProRes encoding')
    return out


def encode_webm(folder, fps, quality=28, name='page_turn_vp9_alpha.webm'):
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError('FFmpeg was not found on PATH. The PNG frames were kept.')
    folder = Path(folder)
    out = folder / name
    _run([ffmpeg, '-n', '-hide_banner', '-loglevel', 'error', '-framerate', str(fps),
          '-i', str(folder / 'frame_%06d.png'), '-an', '-c:v', 'libvpx-vp9', '-deadline', 'good',
          '-cpu-used', '4', '-row-mt', '1', '-threads', '0', '-b:v', '0', '-crf', str(int(quality)),
          '-auto-alt-ref', '0', '-pix_fmt', 'yuva420p', str(out)], 'WebM encoding')
    _verify_alpha(out)
    return out


def _verify_alpha(path):
    """Refuse to report success unless the WebM really carries transparency."""
    probe = shutil.which('ffprobe')
    if not probe:
        return
    result = subprocess.run([probe, '-v', 'error', '-select_streams', 'v:0', '-of', 'json',
                             '-show_entries', 'stream=codec_name:stream_tags=alpha_mode', str(path)],
                            capture_output=True, text=True, creationflags=NO_WINDOW)
    try:
        stream = json.loads(result.stdout)['streams'][0]
    except (ValueError, KeyError, IndexError):
        raise RuntimeError('WebM was written but could not be checked; the PNG frames were kept.')
    if stream.get('codec_name') != 'vp9' or str(stream.get('tags', {}).get('alpha_mode')) != '1':
        raise RuntimeError('WebM was encoded without transparency; the PNG frames were kept.')


def delete_frames(folder):
    for f in Path(folder).glob('frame_*.png'):
        f.unlink()
