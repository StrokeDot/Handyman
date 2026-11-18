"""Picking a Blender version and the automatic fallback (no Blender, no Qt)."""
import os
import tempfile

os.environ['APPDATA'] = tempfile.mkdtemp()
os.environ.pop('MOTIONCRAFT_BLENDER', None)
os.environ.pop('HANDYMAN_BLENDER', None)

import blender_bridge as bb  # noqa: E402

B44 = r'C:\Program Files\Blender Foundation\Blender 4.4\blender.exe'
B52 = r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
B53 = r'C:\Program Files\Blender Foundation\Blender 5.3\blender.exe'


def fake_installs(monkeypatch, paths):
    def glob(pattern):
        return list(paths) if pattern.startswith(r'C:\Program Files\Blender') else []
    monkeypatch.setattr(bb.glob, 'glob', glob)


def test_version_from_path():
    assert bb.version_from_path(B53) == '5.3'
    assert bb.version_from_path(B44) == '4.4'
    assert bb.version_from_path(r'D:\tools\blender.exe') == ''
    assert bb.version_from_path(None) == ''


def test_newest_first(monkeypatch):
    fake_installs(monkeypatch, [B44, B53, B52])
    assert bb.find_blenders() == [('5.3', B53), ('5.2', B52), ('4.4', B44)]
    assert bb.find_blender() == B53


def test_fallback_is_the_next_older(monkeypatch):
    fake_installs(monkeypatch, [B44, B53, B52])
    assert bb.fallback_blender(B53) == B52
    assert bb.fallback_blender(B52) == B44
    assert bb.fallback_blender(B44) == B53      # nothing older: the newest other one
    assert bb.fallback_blender(None) is None


def test_no_fallback_with_one_install(monkeypatch):
    fake_installs(monkeypatch, [B53])
    assert bb.fallback_blender(B53) is None
