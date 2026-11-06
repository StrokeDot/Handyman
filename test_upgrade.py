"""Upgrade test: a 0.6.17 user with an existing template and saved project.

Verifies that updating ships the Leather Journal as the only bundled book, moves the old
bundled books aside without deleting them, and leaves the user's own books and projects alone.
"""
import json
import shutil
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

import paths  # noqa: E402
import templates  # noqa: E402


def setup_user_dir(tmp):
    """Pretend we are a 0.6.17 install: user folder has the OLD leather-journal only."""
    books = Path(tmp) / 'books'
    books.mkdir(parents=True)
    legacy = books / 'leather-journal'
    legacy.mkdir()
    # the old, pre-calibration template the user already had
    (legacy / 'book.json').write_text(json.dumps({
        'name': 'Leather journal', 'page_aspect': 1.4, 'page_count': 50,
        'title': 'My old book', 'bundle_version': '0.6.17',
    }), encoding='utf-8')
    # an existing saved project referencing it
    (Path(tmp) / 'project.json').write_text(json.dumps({
        'book': str(legacy), 'page_count': 50, 'pages': ['old1.png', 'old2.png'],
    }), encoding='utf-8')
    return books, legacy


def test_upgrade_ships_leather_journal_and_keeps_old_books_safe():
    with tempfile.TemporaryDirectory() as tmp:
        books, legacy = setup_user_dir(tmp)
        old_json = (legacy / 'book.json').read_text(encoding='utf-8')
        old_project = (Path(tmp) / 'project.json').read_text(encoding='utf-8')

        paths.books_dir = lambda: books
        templates.ensure_starter_books()

        # 1. the Leather Journal (real pages) is now the bundled book
        new = json.loads((books / 'leather-journal' / 'book.json').read_text(encoding='utf-8'))
        assert new['name'] == 'Leather Journal' and new['engine'] == 'journal', new
        # 2. the old template was moved aside, byte-identical, not deleted
        kept = books / '_retired' / 'leather-journal' / 'book.json'
        assert kept.read_text(encoding='utf-8') == old_json
        # 3. the saved project is untouched
        assert (Path(tmp) / 'project.json').read_text(encoding='utf-8') == old_project


def test_leather_journal_is_the_only_book():
    with tempfile.TemporaryDirectory() as tmp:
        books, _ = setup_user_dir(tmp)
        for name in ('leather-book', 'real-pages-journal'):       # 0.6.x and 0.7.0 leftovers
            (books / name).mkdir()
            (books / name / 'book.json').write_text(json.dumps({'name': name}), encoding='utf-8')
        paths.books_dir = lambda: books
        listed = templates.list_books()
        assert [b['name'] for b in listed] == ['Leather Journal'], [b['name'] for b in listed]


def test_users_own_books_stay_listed():
    with tempfile.TemporaryDirectory() as tmp:
        books = Path(tmp) / 'books'
        books.mkdir(parents=True)
        mine = books / 'my-bible'
        mine.mkdir()
        (mine / 'book.json').write_text(json.dumps({'name': 'My Bible', 'engine': 'journal',
                                                    'user_modified': True}), encoding='utf-8')
        before = (mine / 'book.json').read_text(encoding='utf-8')
        paths.books_dir = lambda: books
        names = [b['name'] for b in templates.list_books()]
        assert 'My Bible' in names and 'Leather Journal' in names, names
        assert (mine / 'book.json').read_text(encoding='utf-8') == before


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
        print(f'ok {t.__name__}')
    print(f'ALL {len(tests)} UPGRADE TESTS PASSED')


if __name__ == '__main__':
    main()



def test_untouched_journal_gets_new_images_on_update():
    with tempfile.TemporaryDirectory() as tmp:
        books = Path(tmp) / 'books'
        src = REPO / 'resources' / 'books' / 'leather-journal'
        dest = books / 'leather-journal'
        shutil.copytree(src, dest)
        old = json.loads((dest / 'book.json').read_text(encoding='utf-8'))
        old['bundle_version'] = '0.7.1'
        old.pop('image_sizes', None)
        (dest / 'book.json').write_text(json.dumps(old), encoding='utf-8')
        (dest / 'front_ext.png').write_bytes(b'old')
        paths.books_dir = lambda: books
        templates.ensure_starter_books()
        new = json.loads((dest / 'book.json').read_text(encoding='utf-8'))
        assert new['image_sizes']['page'] == [982, 1406]
        assert (dest / 'front_ext.png').read_bytes() == (src / 'front_ext.png').read_bytes()


def test_edited_journal_keeps_its_images_but_learns_the_size_rules():
    with tempfile.TemporaryDirectory() as tmp:
        books = Path(tmp) / 'books'
        src = REPO / 'resources' / 'books' / 'leather-journal'
        dest = books / 'leather-journal'
        shutil.copytree(src, dest)
        old = json.loads((dest / 'book.json').read_text(encoding='utf-8'))
        old.update(bundle_version='0.7.1', user_modified=True)
        old.pop('image_sizes', None)
        (dest / 'book.json').write_text(json.dumps(old), encoding='utf-8')
        (dest / 'front_ext.png').write_bytes(b'mine')
        paths.books_dir = lambda: books
        templates.ensure_starter_books()
        new = json.loads((dest / 'book.json').read_text(encoding='utf-8'))
        assert new['image_sizes']['page'] == [982, 1406]
        assert (dest / 'front_ext.png').read_bytes() == b'mine'
