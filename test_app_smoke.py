"""Opens the main window off-screen and pokes the main controls (runs on the Windows build machine)."""
import os
import sys
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['APPDATA'] = tempfile.mkdtemp()

from PySide6.QtWidgets import QApplication  # noqa: E402

import app  # noqa: E402
from book_dialog import BookDialog  # noqa: E402


def main():
    qt = QApplication(sys.argv)
    w = app.Studio()
    w.show()
    w._add_blank()
    w._add_blank()
    w._add_blank()
    assert w.pages.count() == 3
    w._move_page(-1)
    assert 'turn' in w.summary.text()
    state = w._state()
    assert w._apply_state(state) == 0
    job = w._job(w._values(), tempfile.mkdtemp())
    assert job['book']['leather_color'] and job['open_seconds'] > 0
    d = BookDialog(w._book(), w)
    b = d.result_book()
    assert b['name'] and b['emblem_style'] in ('medallion', 'deboss')
    w.close()
    qt.quit()
    print('ok app smoke')


if __name__ == '__main__':
    main()
