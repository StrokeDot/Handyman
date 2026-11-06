"""Adjust an image to the exact size a book slot needs: crop and position it, fit it inside,
or stretch it - then save a copy at exactly that size. The original file is never changed."""
import hashlib
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QSlider,
                               QVBoxLayout, QWidget)

import paths

MODES = {
    'Crop to fill (drag to position)': 'fill',
    'Fit inside (edges filled with its colour)': 'fit',
    'Stretch to the size': 'stretch',
}


def average_colour(img):
    small = img.scaled(16, 16, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    r = g = b = 0
    for y in range(16):
        for x in range(16):
            c = small.pixelColor(x, y)
            r, g, b = r + c.red(), g + c.green(), b + c.blue()
    return QColor(r // 256, g // 256, b // 256)


def image_rect(img_w, img_h, out_w, out_h, mode, zoom=1.0, off=(0.0, 0.0)):
    """Where the source image goes inside an out_w x out_h frame (QRectF in frame pixels).
    off: (-1..1, -1..1) moves a cropped image so other parts of it show."""
    if mode == 'stretch':
        return QRectF(0, 0, out_w, out_h)
    if mode == 'fit':
        s = min(out_w / img_w, out_h / img_h)
    else:
        s = max(out_w / img_w, out_h / img_h) * max(1.0, zoom)
    w, h = img_w * s, img_h * s
    spare_x, spare_y = max(0.0, w - out_w), max(0.0, h - out_h)
    x = (out_w - w) / 2 - off[0] * spare_x / 2 if mode == 'fill' else (out_w - w) / 2
    y = (out_h - h) / 2 - off[1] * spare_y / 2 if mode == 'fill' else (out_h - h) / 2
    return QRectF(x, y, w, h)


def render(img, size, mode, zoom=1.0, off=(0.0, 0.0)):
    out_w, out_h = size
    out = QImage(out_w, out_h, QImage.Format.Format_ARGB32)
    out.fill(average_colour(img) if mode == 'fit' else QColor(0, 0, 0, 0))
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.drawImage(image_rect(img.width(), img.height(), out_w, out_h, mode, zoom, off), img)
    p.end()
    return out


def save_adjusted(img, size, mode, zoom=1.0, off=(0.0, 0.0), name='image'):
    """Write the adjusted image to the app's cache and return its path."""
    out = render(img, size, mode, zoom, off)
    tag = hashlib.sha1(f'{name}{time.time()}'.encode()).hexdigest()[:8]
    path = paths.cache_dir('adjusted') / f'{Path(name).stem}_{size[0]}x{size[1]}_{tag}.png'
    out.save(str(path))
    return str(path)


def auto_adjust(path, size):
    """Crop to fill, centred: the quick choice for many page images at once."""
    img = QImage(str(path))
    return save_adjusted(img, size, 'fill', name=Path(path).name)


class _Canvas(QWidget):
    moved = Signal()

    def __init__(self, img, size):
        super().__init__()
        self.img, self.size_px = img, size
        self.mode, self.zoom, self.off = 'fill', 1.0, [0.0, 0.0]
        self._drag = None
        self.setMinimumSize(420, 420)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def frame_rect(self):
        out_w, out_h = self.size_px
        s = min((self.width() - 40) / out_w, (self.height() - 40) / out_h)
        w, h = out_w * s, out_h * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), s

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#1b1b20'))
        frame, s = self.frame_rect()
        r = image_rect(self.img.width(), self.img.height(), *self.size_px, self.mode, self.zoom, tuple(self.off))
        if self.mode == 'fit':
            p.fillRect(frame, average_colour(self.img))
        target = QRectF(frame.x() + r.x() * s, frame.y() + r.y() * s, r.width() * s, r.height() * s)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setOpacity(0.35)                 # the parts that will be cut off, dimmed
        p.drawImage(target, self.img)
        p.setOpacity(1.0)
        p.setClipRect(frame)
        p.drawImage(target, self.img)
        p.setClipping(False)
        p.setPen(QPen(QColor('#e8c58a'), 2))
        p.drawRect(frame)
        p.setPen(QColor('#cfcfd6'))
        p.drawText(QRectF(0, frame.bottom() + 4, self.width(), 18), Qt.AlignmentFlag.AlignCenter,
                   f'{self.size_px[0]} × {self.size_px[1]} px')

    def mousePressEvent(self, e):
        if self.mode == 'fill':
            self._drag = (QPointF(e.position()), list(self.off))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        start, off0 = self._drag
        frame, s = self.frame_rect()
        r = image_rect(self.img.width(), self.img.height(), *self.size_px, 'fill', self.zoom, (0, 0))
        spare_x = max(1e-6, (r.width() - self.size_px[0]) * s / 2)
        spare_y = max(1e-6, (r.height() - self.size_px[1]) * s / 2)
        d = e.position() - start
        self.off = [max(-1.0, min(1.0, off0[0] - d.x() / spare_x)),
                    max(-1.0, min(1.0, off0[1] - d.y() / spare_y))]
        self.update()

    def mouseReleaseEvent(self, _):
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, e):
        if self.mode == 'fill':
            self.zoom = max(1.0, min(4.0, self.zoom * (1.1 if e.angleDelta().y() > 0 else 1 / 1.1)))
            self.moved.emit()
            self.update()


class ImageFitDialog(QDialog):
    """Shows the image inside a frame of the exact size needed; OK saves an adjusted copy."""

    def __init__(self, path, size, caption='', parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Adjust image - {caption}' if caption else 'Adjust image')
        self.path, self.size_px = str(path), (int(size[0]), int(size[1]))
        self.img = QImage(self.path)
        self.result_path = None
        lay = QVBoxLayout(self)
        info = QLabel(f'<b>{Path(path).name}</b> is {self.img.width()} × {self.img.height()} px. '
                      f'It needs to be <b>{size[0]} × {size[1]} px</b>. Choose how to make it fit - '
                      'the gold frame is what will be used.')
        info.setWordWrap(True)
        lay.addWidget(info)
        row = QHBoxLayout()
        row.addWidget(QLabel('How'))
        self.mode = QComboBox()
        self.mode.addItems(list(MODES))
        self.mode.currentTextChanged.connect(self._mode_changed)
        row.addWidget(self.mode, 1)
        row.addWidget(QLabel('Zoom'))
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(100, 400)
        self.zoom.setValue(100)
        self.zoom.valueChanged.connect(self._zoom_changed)
        row.addWidget(self.zoom, 1)
        lay.addLayout(row)
        self.canvas = _Canvas(self.img, self.size_px)
        self.canvas.moved.connect(lambda: self.zoom.setValue(round(self.canvas.zoom * 100)))
        lay.addWidget(self.canvas, 1)
        tip = QLabel('Drag the picture to choose which part shows; the mouse wheel zooms. '
                     'Your original file is not changed.')
        tip.setObjectName('hint')
        tip.setWordWrap(True)
        lay.addWidget(tip)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Use this')
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.resize(640, 720)

    def _mode_changed(self, text):
        self.canvas.mode = MODES[text]
        self.zoom.setEnabled(self.canvas.mode == 'fill')
        self.canvas.update()

    def _zoom_changed(self, v):
        self.canvas.zoom = v / 100
        self.canvas.update()

    def _accept(self):
        c = self.canvas
        self.result_path = save_adjusted(self.img, self.size_px, c.mode, c.zoom, tuple(c.off), Path(self.path).name)
        self.accept()
