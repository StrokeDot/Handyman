"""Instant outline of the book as the camera will see it. No Blender needed, updates while dragging."""
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

import camera_fit as cf
from page_curl import sheet_vertices

PAGE_W, MARGIN, TOP = 1.0, 0.05, 0.105


class FramingView(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = None
        self.page_aspect = 1.4
        self.aspect = 16 / 9
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def heightForWidth(self, w):
        return int(w / self.aspect)

    def hasHeightForWidth(self):
        return True

    def set_view(self, settings, page_aspect, aspect):
        self.settings, self.page_aspect, self.aspect = dict(settings), page_aspect, aspect
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = min(self.height(), int(w / self.aspect))
        w = int(h * self.aspect)
        ox, oy = (self.width() - w) / 2, (self.height() - h) / 2
        p.fillRect(int(ox), int(oy), w, h, QColor(38, 38, 44))
        if self.settings:
            try:
                self._draw_book(p, ox, oy, w, h)
            except (ValueError, FloatingPointError, ZeroDivisionError):
                pass
        p.setPen(QPen(QColor(120, 120, 130), 1))
        p.drawRect(int(ox), int(oy), w - 1, h - 1)
        p.end()

    def _draw_book(self, p, ox, oy, w, h):
        ph = PAGE_W * self.page_aspect
        pts = cf.book_points(PAGE_W, ph, MARGIN, TOP)
        book_w, book_h = 2 * (PAGE_W + MARGIN), ph + 2 * MARGIN
        cam, r, u, f, lens = cf.shot(self.settings, 0.0, (0, 0, TOP), book_w, book_h, pts, self.aspect)

        def poly(points):
            x, y, depth = cf.project(np.asarray(points, float), cam, r, u, f, lens, self.aspect)
            if depth.min() <= 0.01:
                return None
            return QPolygonF([QPointF(ox + w / 2 + a * w / 2, oy + h / 2 - b * h / 2) for a, b in zip(x, y)])

        hx, hy = PAGE_W + MARGIN, ph / 2 + MARGIN
        shapes = [
            ([(-hx, -hy, 0), (hx, -hy, 0), (hx, hy, 0), (-hx, hy, 0)], QColor(112, 62, 34)),
            ([(-hx, -hy, 0.035), (hx, -hy, 0.035), (hx, hy, 0.035), (-hx, hy, 0.035)], QColor(128, 72, 40)),
            ([(0, -ph / 2, TOP), (-PAGE_W, -ph / 2, TOP), (-PAGE_W, ph / 2, TOP), (0, ph / 2, TOP)], QColor(222, 204, 165)),
            ([(0, -ph / 2, TOP), (PAGE_W, -ph / 2, TOP), (PAGE_W, ph / 2, TOP), (0, ph / 2, TOP)], QColor(214, 196, 158)),
        ]
        v = sheet_vertices(0.58, PAGE_W, ph, 16, 8, TOP + 0.002, TOP + 0.002).reshape(8, 16, 3)
        outline = list(v[0]) + list(v[:, -1]) + list(v[-1][::-1]) + list(v[::-1, 0])
        shapes.append((outline, QColor(240, 228, 196)))
        p.setClipRect(int(ox), int(oy), w, h)
        for points, colour in shapes:
            q = poly(points)
            if q is not None:
                p.setPen(QPen(colour.darker(160), 1))
                p.setBrush(colour)
                p.drawPolygon(q)
        spine = poly([(0, -ph / 2, TOP), (0, ph / 2, TOP)])
        if spine is not None:
            p.setPen(QPen(QColor(90, 60, 40), 2))
            p.drawLine(spine[0], spine[1])
        p.setClipping(False)
        p.setPen(Qt.PenStyle.NoPen)
