"""Checks GitHub for a newer release and installs it.

Uses the repository's permanent ID, so renaming the repository never breaks updates.
"""
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from version import APP_NAME, APP_VERSION, REPO_ID

API = f'https://api.github.com/repositories/{REPO_ID}/releases/latest'


def parse_version(text):
    nums = re.findall(r'\d+', text or '')
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def is_newer(remote, local=APP_VERSION):
    return parse_version(remote) > parse_version(local)


def pick_installer(release):
    for asset in release.get('assets', []):
        name = asset.get('name', '')
        if name.lower().endswith('.exe') and 'setup' in name.lower():
            return asset
    return None


def sha256_file(path):
    """SHA-256 of a file, for integrity verification."""
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(1 << 16), b''):
            h.update(block)
    return h.hexdigest()


def _asset_digest(asset):
    """GitHub returns e.g. 'sha256:2f4f…'; strip the algorithm prefix."""
    return (asset.get('digest') or '').split(':', 1)[-1]


def check(timeout=8):
    """Returns dict(version, notes, url, size, name) when a newer installer exists, else None."""
    req = urllib.request.Request(API, headers={'Accept': 'application/vnd.github+json',
                                               'User-Agent': f'{APP_NAME}/{APP_VERSION}'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        release = json.loads(resp.read().decode('utf-8'))
    version = release.get('tag_name', '').lstrip('v')
    asset = pick_installer(release)
    if not asset or not is_newer(version):
        return None
    return dict(version=version, notes=release.get('body') or '', url=asset['browser_download_url'],
                size=asset.get('size', 0), name=asset['name'], digest=_asset_digest(asset))


def download(info, progress=None, chunk=1 << 16):
    """Downloads the installer to a temp folder, verifying size and SHA-256.

    progress(done_bytes, total_bytes). Raises IOError on an incomplete or corrupt download.
    """
    dest = Path(tempfile.gettempdir()) / info['name']
    req = urllib.request.Request(info['url'], headers={'User-Agent': f'{APP_NAME}/{APP_VERSION}'})
    with urllib.request.urlopen(req, timeout=30) as resp, open(dest, 'wb') as fh:
        total = int(resp.headers.get('Content-Length') or info.get('size') or 0)
        done = 0
        while True:
            block = resp.read(chunk)
            if not block:
                break
            fh.write(block)
            done += len(block)
            if progress:
                progress(done, total)
    if info.get('size') and dest.stat().st_size != info['size']:
        dest.unlink(missing_ok=True)
        raise IOError('The download was incomplete. Please try again.')
    if info.get('digest') and sha256_file(dest) != info['digest']:
        dest.unlink(missing_ok=True)
        raise IOError('The download failed its integrity check. Please try again.')
    return dest


def run_installer(path):
    """Starts the installer quietly; it closes this app, updates it and starts it again."""
    flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    subprocess.Popen([str(path), '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS'],
                     creationflags=flags, close_fds=True, cwd=os.path.dirname(str(path)))
