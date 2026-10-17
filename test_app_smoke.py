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
    for name in app.cf.PRESETS:
        w.shot.setCurrentText(name)
        assert w._cam()['tilt'] == round(app.cf.PRESETS[name]['tilt'])
        assert not w.framing.grab().isNull()          # the live outline draws without errors
    w.turn.setValue(25)
    w.zoom.setValue(180)
    w.move.setCurrentText('Slow push-in')
    assert w._cam()['move'] == 'push' and w._cam()['turn'] == 25
    w._apply_state(dict(w._state(), cam=dict(tilt=40, turn=-10, roll=5, lens=28, zoom=1.3, move='drift')))
    assert w._cam()['tilt'] == 40 and w._cam()['move'] == 'drift'
    job = w._job(w._values(), tempfile.mkdtemp())
    assert job['cam']['lens'] == 28
    d = BookDialog(w._book(), w)
    b = d.result_book()
    assert b['name'] and b['emblem_style'] in ('medallion', 'deboss')
    w.close()
    qt.quit()
    print('ok app smoke')


if __name__ == '__main__':
    main()
