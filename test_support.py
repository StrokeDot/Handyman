"""Templates and updater checks (no Blender, no Qt)."""
import json
import os
import tempfile

os.environ['APPDATA'] = tempfile.mkdtemp()

import templates  # noqa: E402
import updater  # noqa: E402


def test_versions():
    assert updater.is_newer('0.2.1', '0.2.0')
    assert updater.is_newer('v1.0', '0.9.9')
    assert not updater.is_newer('0.2.0', '0.2.0')
    assert not updater.is_newer('0.1.9', '0.2.0')


def test_pick_installer():
    rel = {'assets': [{'name': 'notes.txt'}, {'name': 'Handyman-Setup-0.3.0.exe', 'browser_download_url': 'u'}]}
    assert updater.pick_installer(rel)['name'].endswith('.exe')
    assert updater.pick_installer({'assets': []}) is None


def test_templates_roundtrip():
    books = templates.list_books()
    assert books and books[0]['name']
    with tempfile.TemporaryDirectory() as tmp:
        img = os.path.join(tmp, 'logo.png')
        open(img, 'wb').write(b'x')
        b = templates.save(dict(books[0], name='My Journal', folder=None, title='Hi'), new_image=img)
        assert b['emblem'] == 'emblem.png' and b['title'] == 'Hi'
        scene = templates.for_scene(b)
        assert scene['emblem'].endswith('emblem.png')
        assert all(0 <= c <= 1 for c in scene['leather_color'])
        copy = templates.duplicate(b, 'My Journal')
        assert copy['folder'] != b['folder'] and copy['emblem'] == 'emblem.png'
        json.loads(open(os.path.join(copy['folder'], 'book.json')).read())


def test_hex_to_linear():
    assert templates.hex_to_linear('#ffffff') == (1.0, 1.0, 1.0)
    assert templates.hex_to_linear('#000000') == (0.0, 0.0, 0.0)


def test_cover_colors_fallback():
    b = dict(templates.DEFAULTS)
    s = templates.for_scene(b)
    assert s['back_cover_color'] == s['leather_color']      # None -> same as front cover
    assert s['inside_cover_color'] == s['paper_color']      # None -> paper endpaper
    b2 = dict(b, back_cover_color='#000000', inside_cover_color='#ffffff')
    s2 = templates.for_scene(b2)
    assert s2['back_cover_color'] == (0.0, 0.0, 0.0)
    assert s2['inside_cover_color'] == (1.0, 1.0, 1.0)


def test_sha256_and_asset_digest():
    import updater
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, 'x.bin')
        with open(p, 'wb') as fh:
            fh.write(b'hello updater')
        digest = updater.sha256_file(p)
        assert len(digest) == 64 and all(c in '0123456789abcdef' for c in digest)
        assert updater._asset_digest({'digest': 'sha256:' + digest}) == digest
        assert updater._asset_digest({}) == ''


def test_0_6_0_release_is_detected():
    """The installed 0.5.0 updater must see a 0.6.0 release as newer and pick its installer."""
    import updater
    assert updater.is_newer('0.6.0', '0.5.0')
    assert updater.is_newer('v0.6.0', '0.5.0')
    asset = {'name': 'Handyman-Setup-0.6.0.exe', 'browser_download_url': 'u',
             'size': 123, 'digest': 'sha256:abc'}
    release = {'tag_name': 'v0.6.0', 'assets': [{'name': 'notes.txt'}, asset]}
    assert updater.pick_installer(release) is asset


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
