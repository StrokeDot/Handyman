"""Compare the book as it is now with the new size and shape, side by side, in the same 3D
view the video uses (camera, pages and animation), both playing in step."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget)

try:
    from live_view import LiveView
except Exception:  # no OpenGL: the dialog says so instead
    LiveView = None


def size_text(book):
    cm = book.get('page_size_cm')
    if cm:
        return f'{float(cm[0]):g} × {float(cm[1]):g} cm page'
    return 'Leather Journal size'


class CompareDialog(QDialog):
    def __init__(self, old_book, new_book, images, values, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Compare: the book now and the new size')
        self.views = []
        lay = QVBoxLayout(self)
        tip = QLabel('Both books as the video shows them, with your camera and pages. '
                     'A smaller book looks smaller in the picture.')
        tip.setWordWrap(True)
        lay.addWidget(tip)
        row = QHBoxLayout()
        lay.addLayout(row, 1)
        for title, book in (('Now', old_book), ('New size', new_book)):
            col = QVBoxLayout()
            col.addWidget(QLabel(f'<b>{title}</b> - {size_text(book)}'))
            if LiveView is None:
                col.addWidget(QLabel('The 3D view is not available on this computer.'))
            else:
                v = LiveView()
                v.setMinimumSize(420, 240)
                v.failed.connect(lambda msg, c=col: c.addWidget(QLabel(f'3D view problem: {msg}')))
                v.set_content(book, images, values)
                self.views.append(v)
                col.addWidget(v, 1)
            row.addLayout(col, 1)

        bar = QHBoxLayout()
        self.play = QPushButton('Pause')
        self.play.clicked.connect(self._toggle)
        bar.addWidget(self.play)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        total = max([v.timeline.frames for v in self.views] or [1])
        self.slider.setRange(0, max(0, total - 1))
        self.slider.valueChanged.connect(self._seek)
        bar.addWidget(self.slider, 1)
        close = QPushButton('Close')
        close.clicked.connect(self.accept)
        bar.addWidget(close)
        lay.addLayout(bar)

        self.fps = float(values.get('fps', 30) or 30)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._step)
        self.timer.start(int(1000 / min(self.fps, 30)))
        self.resize(1300, 560)

    def _toggle(self):
        if self.timer.isActive():
            self.timer.stop()
            self.play.setText('Play')
        else:
            self.timer.start(int(1000 / min(self.fps, 30)))
            self.play.setText('Pause')

    def _step(self):
        step = max(1, round(self.fps / min(self.fps, 30)))
        v = self.slider.value() + step
        self.slider.setValue(0 if v > self.slider.maximum() else v)

    def _seek(self, frame):
        for v in self.views:
            v.seek(frame)

    def done(self, r):
        self.timer.stop()
        super().done(r)
