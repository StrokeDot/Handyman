"""Checks GitHub for a newer release and installs it.

Uses the repository's permanent ID, so renaming the repository never breaks updates.

Network behaviour is deliberately gentle, because GitHub's public API rate-limits by IP:
- a successful check is cached and reused for six hours (manual checks always go out),
- the API request is conditional (`If-None-Match`), so an unchanged release costs one 304,
- a 403/429 is remembered until the server's reset time instead of being retried in a loop,
- a static `latest.json` is preferred, which needs no authenticated API call at all,
- only one check can run at a time, and a network failure falls back to the cached answer.
"""
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import paths
from version import APP_NAME, APP_VERSION, REPO_ID

API = f'https://api.github.com/repositories/{REPO_ID}/releases/latest'
# Mirrored by the release workflow; served by raw.githubusercontent.com with no API limit.
META = 'https://raw.githubusercontent.com/StrokeDot/Handyman/main/latest.json'
CHECK_INTERVAL = 6 * 3600          # seconds between automatic checks
CACHE_NAME = 'update-check.json'

_lock = threading.Lock()


# --------------------------------------------------------------------- versions
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


# ------------------------------------------------------------------------ cache
def _cache_path():
    return paths.user_dir() / CACHE_NAME


def _load_cache():
    try:
        data = json.loads(_cache_path().read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(data):
    try:
        _cache_path().write_text(json.dumps(data, indent=2), encoding='utf-8')
    except OSError:
        pass


def _clock(seconds):
    """'in about 3 minutes' for a friendly status line."""
    seconds = max(0, int(seconds))
    if seconds < 90:
        return 'in a moment'
    minutes = seconds // 60
    if minutes < 60:
        return f'in {minutes} minute' + ('s' if minutes != 1 else '')
    hours = minutes // 60
    return f'in {hours} hour' + ('s' if hours != 1 else '')


def _retry_at(exc):
    """When a 403/429 says to come back: Retry-After, else X-RateLimit-Reset."""
    headers = exc.headers or {}
    try:
        after = int(headers.get('Retry-After') or 0)
        if after > 0:
            return time.time() + after
    except (TypeError, ValueError):
        pass
    try:
        reset = int(headers.get('X-RateLimit-Reset') or 0)
        if reset > 0:
            return float(reset)
    except (TypeError, ValueError):
        pass
    return time.time() + CHECK_INTERVAL


# ---------------------------------------------------------------------- sources
def _info_from_dict(data):
    version = str(data.get('version') or data.get('tag_name') or '').lstrip('v')
    asset = pick_installer(data) if data.get('assets') else data
    if not version or not asset or not is_newer(version):
        return None
    return dict(version=version, notes=data.get('notes') or data.get('body') or '',
                url=asset.get('browser_download_url') or asset.get('url'),
                size=int(asset.get('size') or 0), name=asset.get('name') or '',
                digest=_asset_digest(asset))


def _from_meta(timeout):
    """(answered, info): a static file that needs no GitHub API call."""
    try:
        req = urllib.request.Request(META, headers={'User-Agent': f'{APP_NAME}/{APP_VERSION}'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, _info_from_dict(json.loads(resp.read().decode('utf-8')))
    except Exception:
        return False, None


def _from_api(etag, timeout, cached_info=None):
    """(answered, info, etag, blocked_until)."""
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': f'{APP_NAME}/{APP_VERSION}'}
    if etag:
        headers['If-None-Match'] = etag
    req = urllib.request.Request(API, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return True, _info_from_dict(data), resp.headers.get('ETag') or etag, 0
    except urllib.error.HTTPError as exc:
        if exc.code == 304:                       # unchanged since the cached ETag
            return True, cached_info, etag, 0
        if exc.code in (403, 429):
            return False, None, etag, _retry_at(exc)
        return False, None, etag, 0
    except Exception:
        return False, None, etag, 0


# ------------------------------------------------------------------------ check
def check(manual=False, timeout=8):
    """Returns {'info': release|None, 'message': str, 'next': epoch}.

    `manual` skips the six-hour interval (the "Check for updates" button).
    """
    if not _lock.acquire(blocking=False):
        cache = _load_cache()
        return {'info': cache.get('info'), 'message': 'An update check is already running.',
                'next': 0}
    try:
        return _check_locked(manual, timeout)
    finally:
        _lock.release()


def _check_locked(manual, timeout):
    now = time.time()
    cache = _load_cache()
    checked = float(cache.get('checked_at') or 0)
    blocked = float(cache.get('blocked_until') or 0)

    if blocked > now:
        return {'info': cache.get('info'),
                'message': f'GitHub is limiting how often we can check. Next try {_clock(blocked - now)}.',
                'next': blocked}
    if not manual and checked and now - checked < CHECK_INTERVAL:
        return {'info': cache.get('info'),
                'message': f'Already checked {_clock(now - checked).replace("in ", "")} ago; next check {_clock(checked + CHECK_INTERVAL - now)}.',
                'next': checked + CHECK_INTERVAL}

    answered, info = _from_meta(timeout)
    etag = cache.get('etag')
    if not answered:
        answered, info, etag, blocked = _from_api(etag, timeout, cache.get('info'))
        if blocked:
            cache['blocked_until'] = blocked
            cache['checked_at'] = now
            _save_cache(cache)
            return {'info': cache.get('info'),
                    'message': f'GitHub is limiting how often we can check. Next try {_clock(blocked - now)}.',
                    'next': blocked}
    if answered:
        cache.update(checked_at=now, etag=etag, info=info, blocked_until=0)
        _save_cache(cache)
        if info:
            return {'info': info, 'message': f'Version {info["version"]} is available.',
                    'next': now + CHECK_INTERVAL}
        return {'info': None, 'message': f'You have the latest version ({APP_VERSION}).',
                'next': now + CHECK_INTERVAL}

    # Offline: keep the app usable and repeat what we knew.
    if cache.get('info'):
        return {'info': cache.get('info'),
                'message': 'GitHub could not be reached; offering the last known update.',
                'next': 0}
    return {'info': None, 'message': 'GitHub could not be reached. The app still works normally.',
            'next': 0}


# --------------------------------------------------------------------- download
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
