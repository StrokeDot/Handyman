"""Updater checks against simulated rate limits, ETags and outages."""
import json
import tempfile
import time
import urllib.error
from pathlib import Path

import updater


class Resp:
    def __init__(self, data, headers=None):
        self._data = json.dumps(data).encode('utf-8')
        self.headers = headers or {}

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def release(version='9.9.9'):
    return {'tag_name': f'v{version}', 'body': 'notes',
            'assets': [{'name': 'Handyman-Setup-9.9.9.exe', 'size': 5,
                        'browser_download_url': 'http://x/y.exe', 'digest': 'sha256:abc'}]}


def with_cache(fn):
    def run():
        with tempfile.TemporaryDirectory() as tmp:
            updater._cache_path = lambda: Path(tmp) / 'cache.json'
            real = updater.urllib.request.urlopen
            try:
                fn(real)
            finally:
                updater.urllib.request.urlopen = real
    return run


@with_cache
def test_rate_limit_backoff(real):
    def boom(*a, **k):
        raise urllib.error.HTTPError('u', 403, 'rate limit', {'Retry-After': '3600'}, None)
    updater.urllib.request.urlopen = boom
    first = updater.check(manual=True)
    assert first['info'] is None
    assert 'limit' in first['message'].lower()
    assert first['next'] > time.time() + 100
    second = updater.check(manual=False)
    assert second['next'] == first['next']          # still blocked, no new request


@with_cache
def test_interval_and_manual_bypass(real):
    calls = {'n': 0}

    def ok(*a, **k):
        calls['n'] += 1
        return Resp(release(), {'ETag': 'e1'})
    updater.urllib.request.urlopen = ok
    first = updater.check(manual=True)
    assert first['info'] and first['info']['version'] == '9.9.9'
    auto = updater.check(manual=False)
    assert auto['info'] == first['info'] and calls['n'] == 1   # served from cache
    updater.check(manual=True)
    assert calls['n'] == 2                                     # manual goes out


@with_cache
def test_etag_304_uses_cache(real):
    def ok(*a, **k):
        return Resp(release(), {'ETag': 'e1'})
    updater.urllib.request.urlopen = ok
    updater.check(manual=True)

    def not_modified(*a, **k):
        raise urllib.error.HTTPError('u', 304, 'not modified', {}, None)
    updater.urllib.request.urlopen = not_modified
    again = updater.check(manual=True)
    assert again['info'] and again['info']['version'] == '9.9.9'


@with_cache
def test_offline_falls_back(real):
    def ok(*a, **k):
        return Resp(release(), {'ETag': 'e1'})
    updater.urllib.request.urlopen = ok
    updater.check(manual=True)

    def down(*a, **k):
        raise OSError('no network')
    updater.urllib.request.urlopen = down
    again = updater.check(manual=True)
    assert again['info'] and again['info']['version'] == '9.9.9'   # cached answer


@with_cache
def test_meta_avoids_the_api(real):
    def meta_only(url, *a, **k):
        target = getattr(url, 'full_url', str(url))
        if target.startswith('https://raw.githubusercontent.com'):
            return Resp({'version': '9.9.9', 'url': 'http://x/y.exe', 'size': 5,
                         'name': 'Handyman-Setup-9.9.9.exe', 'digest': 'abc'})
        raise AssertionError('the GitHub API should not be called')
    updater.urllib.request.urlopen = meta_only
    result = updater.check(manual=True)
    assert result['info'] and result['info']['version'] == '9.9.9'


def test_version_compare_handles_two_digits():
    assert updater.is_newer('0.6.10', '0.6.9')
    assert not updater.is_newer('0.6.10', '0.6.10')


def test_stale_cache_is_never_offered():
    # After updating, a cached older release must not be offered again.
    assert updater._usable({'version': '0.0.1'}) is None
    assert updater._usable(None) is None


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
