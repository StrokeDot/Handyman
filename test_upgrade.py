"""Upgrade test: a 0.6.17 user with an existing template and saved project.

Verifies that updating ships the calibrated leather book, leaves the user's own
template and saved project untouched, and defaults new projects to 20 sheets.
"""
import json
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


def test_upgrade_ships_calibrated_book_and_preserves_user():
    with tempfile.TemporaryDirectory() as tmp:
        books, legacy = setup_user_dir(tmp)
        old_json = (legacy / 'book.json').read_text(encoding='utf-8')
        old_project = (Path(tmp) / 'project.json').read_text(encoding='utf-8')

        paths.books_dir = lambda: books
        templates.ensure_starter_books()

        # 1. the calibrated book is now available
        new = books / 'leather-book'
        assert new.is_dir(), 'calibrated template missing after upgrade'
        dev = json.loads((new / 'book.json').read_text(encoding='utf-8'))
        assert dev['page_count'] == 20, dev['page_count']
        assert abs(dev['page_aspect'] - 1.424) < 1e-9, dev['page_aspect']
        assert 'Development Preview' in dev['name'], dev['name']

        # 2. the user's existing template is byte-identical
        assert (legacy / 'book.json').read_text(encoding='utf-8') == old_json

        # 3. the saved project is untouched
        assert (Path(tmp) / 'project.json').read_text(encoding='utf-8') == old_project


def test_calibrated_book_is_the_default():
    with tempfile.TemporaryDirectory() as tmp:
        books, legacy = setup_user_dir(tmp)
        paths.books_dir = lambda: books
        templates.ensure_starter_books()
        listed = templates.list_books()
        names = [b['name'] for b in listed]
        assert any('Development Preview' in n for n in names), names
        # sorted by folder name: leather-book sorts before leather-journal
        folders = [Path(b['folder']).name for b in listed]
        assert folders[0] == 'leather-book', folders


def test_user_modified_template_is_never_overwritten():
    with tempfile.TemporaryDirectory() as tmp:
        books = Path(tmp) / 'books'
        books.mkdir(parents=True)
        mine = books / 'leather-book'
        mine.mkdir()
        (mine / 'book.json').write_text(json.dumps({
            'name': 'My customised book', 'page_count': 7,
            'bundle_version': '0.6.1', 'user_modified': True,
        }), encoding='utf-8')
        before = (mine / 'book.json').read_text(encoding='utf-8')
        paths.books_dir = lambda: books
        templates.ensure_starter_books()
        assert (mine / 'book.json').read_text(encoding='utf-8') == before


def test_stale_bundle_fields_are_upgraded_when_not_customised():
    with tempfile.TemporaryDirectory() as tmp:
        books = Path(tmp) / 'books'
        books.mkdir(parents=True)
        stale = books / 'leather-book'
        stale.mkdir()
        (stale / 'book.json').write_text(json.dumps({
            'name': 'Leather Book', 'page_aspect': 1.4, 'page_count': 50,
            'bundle_version': '0.6.0',
        }), encoding='utf-8')
        paths.books_dir = lambda: books
        templates.ensure_starter_books()
        d = json.loads((stale / 'book.json').read_text(encoding='utf-8'))
        assert d['page_count'] == 20, d['page_count']
        assert abs(d['page_aspect'] - 1.424) < 1e-9


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
        print(f'ok {t.__name__}')
    print(f'ALL {len(tests)} UPGRADE TESTS PASSED')


if __name__ == '__main__':
    main()

