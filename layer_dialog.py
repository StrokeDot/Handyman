"""Pictures on a page: place pictures on one page like layers in After Effects, with
"Ink on the page" so they merge with the paper.

The big view shows the page as the book will show it (the book's paper, the page's own
picture or text, then the layers). Drag a picture to move it, use the mouse wheel to make
it bigger or smaller, Shift + wheel to turn it. The panel on the right holds every setting.
"""
import copy
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

import page_layers as PL

PREVIEW_SIDE = 1100          # the preview works on pictures at most this big (speed)


def pil_to_qimage(img):
    img = img.convert('RGBA')
    data = img.tobytes('raw', 'RGBA')
    return QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888).copy()


class _PageCanvas(QWidget):
    """The page with its layers; the selected layer can be dragged, scaled and turned."""
    changed = Signal()          # the selected layer moved / resized / turned

    def __init__(self, page_size, parts):
        """page_size: the canvas in pixels (one page, or two side by side for a spread).
        parts: [(paper, page picture)] for each page shown, left to right."""
        super().__init__()
        self.page_size = page_size
        self.parts = [(QImage(str(pp)) if pp else QImage(),
                       QImage(str(bp)) if bp and Path(bp).exists() else QImage()) for pp, bp in parts]
        self.page_w = page_size[0] / len(self.parts)
        self.margin = 0.08
        self.show_margins = True
        self.layers, self.current = [], -1
        self._pics = {}           # layer look -> (PIL picture, QImage) so dragging stays smooth
        self._drag = None
        self.setMinimumSize(460, 560)
        self.setMouseTracking(True)

    # --------------------------------------------------------------- geometry
    def page_rect(self):
        pw, ph = self.page_size
        s = min((self.width() - 24) / pw, (self.height() - 44) / ph)
        return QRectF((self.width() - pw * s) / 2, 12 + (self.height() - 44 - ph * s) / 2, pw * s, ph * s), s

    def picture(self, layer):
        """(PIL, QImage) of the layer with its look; cached by everything but its place."""
        look = tuple(sorted((k, str(v)) for k, v in layer.items() if k not in ('x', 'y', 'w', 'rot')))
        if look not in self._pics:
            try:
                pil = PL.layer_picture(layer, max_side=PREVIEW_SIDE)
            except Exception:  # an unreadable file: show nothing for it
                pil = Image.new('RGBA', (8, 8), (0, 0, 0, 0))
            self._pics[look] = (pil, pil_to_qimage(pil))
            if len(self._pics) > 40:
                self._pics.pop(next(iter(self._pics)))
        return self._pics[look]

    def corners(self, layer):
        pil, _ = self.picture(layer)
        frame, s = self.page_rect()
        return [QPointF(frame.x() + x * s, frame.y() + y * s)
                for x, y in PL.layer_corners(layer, pil.size, self.page_size)]

    def hit(self, pos):
        for i in range(len(self.layers) - 1, -1, -1):
            if QPolygonF(self.corners(self.layers[i])).containsPoint(pos, Qt.FillRule.OddEvenFill):
                return i
        return -1

    # --------------------------------------------------------------- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#1b1b20'))
        frame, s = self.page_rect()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self.parts)
        for i, (paper, base) in enumerate(self.parts):
            sub = QRectF(frame.x() + i * frame.width() / n, frame.y(), frame.width() / n, frame.height())
            if not paper.isNull():
                p.drawImage(sub, paper)
            else:
                p.fillRect(sub, QColor('#e8cf9f'))
            if not base.isNull():
                p.drawImage(sub, base)
        p.save()
        p.setClipRect(frame)
        for layer in self.layers:
            if not PL.layer_get(layer, 'image'):
                continue
            pil, q = self.picture(layer)
            w, h = PL.placed_size(layer, pil.size, self.page_size)
            p.save()
            p.translate(frame.x() + float(layer['x']) * frame.width(), frame.y() + float(layer['y']) * frame.height())
            p.rotate(float(PL.layer_get(layer, 'rot')))
            p.drawImage(QRectF(-w * s / 2, -h * s / 2, w * s, h * s), q)
            p.restore()
        p.restore()
        if n == 2:                                   # the spine: each half turns with its own page
            p.setPen(QPen(QColor(90, 60, 30, 170), 2))
            p.drawLine(QPointF(frame.center().x(), frame.top()), QPointF(frame.center().x(), frame.bottom()))
        if self.show_margins and self.margin > 0:
            m = self.margin * self.page_w * s
            p.setPen(QPen(QColor(70, 130, 220, 200), 1, Qt.PenStyle.DashLine))
            p.drawRect(frame.adjusted(m, m, -m, -m))
        if 0 <= self.current < len(self.layers):
            c = self.corners(self.layers[self.current])
            p.setPen(QPen(QColor(0, 0, 0, 150), 3))
            p.drawPolygon(QPolygonF(c))
            p.setPen(QPen(QColor('#f0b94a'), 1.5, Qt.PenStyle.DashLine))
            p.drawPolygon(QPolygonF(c))
            p.setBrush(QColor('#f0b94a'))
            p.setPen(QPen(QColor(0, 0, 0, 180), 1))
            for pt in c:
                p.drawRect(QRectF(pt.x() - 4, pt.y() - 4, 8, 8))
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QColor('#9a9aa6'))
        p.drawText(QRectF(0, frame.bottom() + 4, self.width(), 18), Qt.AlignmentFlag.AlignCenter,
                   'Drag to move  ·  wheel = size  ·  Shift + wheel = turn')

    # --------------------------------------------------------------- mouse
    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        i = self.hit(e.position())
        if i >= 0 and i != self.current:
            self.current = i
            self.changed.emit()
        if 0 <= self.current < len(self.layers):
            layer = self.layers[self.current]
            self._drag = (QPointF(e.position()), float(layer['x']), float(layer['y']))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if not self._drag:
            self.setCursor(Qt.CursorShape.OpenHandCursor if self.hit(e.position()) >= 0
                           else Qt.CursorShape.ArrowCursor)
            return
        start, x0, y0 = self._drag
        frame, _ = self.page_rect()
        d = e.position() - start
        layer = self.layers[self.current]
        layer['x'] = round(min(1.2, max(-0.2, x0 + d.x() / frame.width())), 4)
        layer['y'] = round(min(1.2, max(-0.2, y0 + d.y() / frame.height())), 4)
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, _):
        self._drag = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, e):
        if not 0 <= self.current < len(self.layers):
            return
        layer = self.layers[self.current]
        up = e.angleDelta().y() > 0
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            layer['rot'] = round(((float(layer['rot']) + (2 if up else -2) + 180) % 360) - 180, 2)
        else:
            layer['w'] = round(min(3.0, max(0.03, float(layer['w']) * (1.05 if up else 1 / 1.05))), 4)
        self.update()
        self.changed.emit()


class LayerDialog(QDialog):
    """Edit the pictures on one page side. `layers` is a list of page_layers dicts."""

    def __init__(self, title, page_size, paper_path, base_path, layers, parent=None, start_dir='',
                 spread=None, margin=0.08):
        """spread: ((left paper, left page picture), (right paper, right page picture)) to place a
        picture across both pages; page_size is still one page."""
        super().__init__(parent)
        self.setWindowTitle(f'Pictures on {title}')
        self.start_dir = start_dir
        self.spread = spread is not None
        self.layers = copy.deepcopy(layers or [])
        self._loading = False
        self.one_page = (int(page_size[0]), int(page_size[1]))
        lay = QHBoxLayout(self)

        if self.spread:
            size, parts = (2 * self.one_page[0], self.one_page[1]), list(spread)
        else:
            size, parts = self.one_page, [(paper_path, base_path)]
        self.canvas = _PageCanvas(size, parts)
        self.canvas.margin = margin
        self.canvas.layers = self.layers
        self.canvas.changed.connect(self._canvas_changed)
        lay.addWidget(self.canvas, 3)

        side = QVBoxLayout()
        lay.addLayout(side, 2)
        where = ('across these two pages. The left half stays on the left page and the right half on the '
                 'right page, so each half turns with its own page, like a printed double page'
                 if self.spread else 'on this page')
        intro = QLabel(f'Put pictures {where}. <b>Ink on the page</b> makes a picture look printed on the '
                       'paper: its own background disappears and its lines become ink.')
        intro.setWordWrap(True)
        side.addWidget(intro)
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel('Margins'))
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0, 30)
        self.margin.setSuffix(' %')
        self.margin.setDecimals(0)
        self.margin.setValue(round(margin * 100))
        self.margin.setToolTip('Space kept clear around the pictures, as a share of the page width (blue dashed line)')
        self.margin.valueChanged.connect(self._margin_changed)
        mrow.addWidget(self.margin)
        self.show_margins = QCheckBox('Show')
        self.show_margins.setChecked(True)
        self.show_margins.toggled.connect(self._margin_changed)
        mrow.addWidget(self.show_margins)
        mrow.addStretch(1)
        side.addLayout(mrow)
        self.best = QLabel()
        self.best.setObjectName('hint')
        self.best.setWordWrap(True)
        side.addWidget(self.best)

        self.list = QListWidget()
        self.list.setIconSize(QPixmap(40, 40).size())
        self.list.setMaximumHeight(150)
        self.list.currentRowChanged.connect(self._select)
        side.addWidget(self.list)
        row = QHBoxLayout()
        for text, slot, tip in (('Add picture…', self._add, 'Add one or more pictures to this page'),
                                ('Copy', self._duplicate, 'Make a copy of the selected picture'),
                                ('Remove', self._remove, 'Take the selected picture off the page'),
                                ('▲', lambda: self._move(1), 'Bring forward (on top of the others)'),
                                ('▼', lambda: self._move(-1), 'Send backward')):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            row.addWidget(b)
        side.addLayout(row)

        self.edit = QWidget()
        ed = QVBoxLayout(self.edit)
        ed.setContentsMargins(0, 0, 0, 0)

        g = QGroupBox('Place')
        f = QFormLayout(g)
        self.size = self._slider(3, 300, 60)
        f.addRow('Size (% of page width)', self.size)
        self.rot = QDoubleSpinBox()
        self.rot.setRange(-180, 180)
        self.rot.setSingleStep(1)
        self.rot.setSuffix(' °')
        self.rot.valueChanged.connect(self._controls_changed)
        f.addRow('Turn', self.rot)
        self.opacity = self._slider(0, 100, 100)
        f.addRow('Opacity', self.opacity)
        self.flip = QCheckBox('Mirror the picture')
        self.flip.toggled.connect(self._controls_changed)
        f.addRow('', self.flip)
        quick = QHBoxLayout()
        for text, slot in (('Fit inside the margins', self._fit_margins), ('Centre', self._centre),
                           ('Straight', self._straight)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            quick.addWidget(b)
        f.addRow(quick)
        ed.addWidget(g)

        self.ink_box = QGroupBox('Ink on the page')
        self.ink_box.setCheckable(True)
        self.ink_box.toggled.connect(self._controls_changed)
        f = QFormLayout(self.ink_box)
        self.ink_colour = QComboBox()
        self.ink_colour.addItems(list(PL.INK_COLOURS))
        self.ink_colour.currentTextChanged.connect(self._controls_changed)
        f.addRow('Ink colour', self.ink_colour)
        self.removal = self._slider(0, 100, 50)
        self.removal.setToolTip('How much of the picture counts as paper and disappears')
        f.addRow('Paper removal', self.removal)
        self.strength = self._slider(0, 100, 100)
        self.strength.setToolTip('How dark the ink is')
        f.addRow('Ink strength', self.strength)
        ed.addWidget(self.ink_box)

        g = QGroupBox('Edges')
        f = QFormLayout(g)
        self.edges = QComboBox()
        self.edges.addItems(list(PL.EDGES))
        self.edges.currentTextChanged.connect(self._controls_changed)
        f.addRow('Fade', self.edges)
        self.edge_size = self._slider(0, 50, 15)
        f.addRow('Edge size', self.edge_size)
        ed.addWidget(g)
        side.addWidget(self.edit)
        side.addStretch(1)

        self.empty = QLabel('No pictures on this page yet. Press <b>Add picture…</b>')
        self.empty.setWordWrap(True)
        side.addWidget(self.empty)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Use on this page')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        side.addWidget(buttons)

        self._timer = QTimer(self, singleShot=True, interval=60)   # slider drags redraw a little later
        self._timer.timeout.connect(self.canvas.update)
        self._fill_list()
        self.list.setCurrentRow(len(self.layers) - 1)
        self._select(self.list.currentRow())
        self._margin_changed()
        self.resize(1400 if self.spread else 1100, 760)

    # --------------------------------------------------------------- helpers
    def _slider(self, lo, hi, val):
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        s.valueChanged.connect(self._controls_changed)
        return s

    def _fill_list(self):
        self._loading = True
        cur = self.list.currentRow()
        self.list.clear()
        for i, layer in enumerate(self.layers):
            pix = QPixmap(str(layer['image']))
            icon = QIcon(pix.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)) if not pix.isNull() else QIcon()
            ink = ' · ink' if PL.layer_get(layer, 'ink_on') else ''
            self.list.addItem(QListWidgetItem(icon, f'{i + 1}. {Path(layer["image"]).name}{ink}'))
        self._loading = False
        if self.layers:
            self.list.setCurrentRow(max(0, min(cur, len(self.layers) - 1)))
        has = bool(self.layers)
        self.edit.setVisible(has)
        self.empty.setVisible(not has)

    def _layer(self):
        i = self.list.currentRow()
        return self.layers[i] if 0 <= i < len(self.layers) else None

    def _select(self, row):
        if self._loading:
            return
        self.canvas.current = row
        layer = self._layer()
        if layer:
            self._loading = True
            self.size.setValue(round(float(layer['w']) * 100))
            self.rot.setValue(float(PL.layer_get(layer, 'rot')))
            self.opacity.setValue(round(float(PL.layer_get(layer, 'opacity'))))
            self.flip.setChecked(bool(PL.layer_get(layer, 'flip')))
            self.ink_box.setChecked(bool(PL.layer_get(layer, 'ink_on')))
            self.ink_colour.setCurrentText(PL.layer_get(layer, 'ink_colour'))
            self.removal.setValue(round(float(PL.layer_get(layer, 'ink_removal'))))
            self.strength.setValue(round(float(PL.layer_get(layer, 'ink_strength'))))
            self.edges.setCurrentText(PL.layer_get(layer, 'ink_edges'))
            self.edge_size.setValue(round(float(PL.layer_get(layer, 'ink_edge_size'))))
            self.edge_size.setEnabled(self.edges.currentText() != 'No fading')
            self._loading = False
        self.canvas.update()

    def _controls_changed(self, *_):
        layer = self._layer()
        if self._loading or not layer:
            return
        was_ink = PL.layer_get(layer, 'ink_on')
        layer.update(w=self.size.value() / 100, rot=self.rot.value(), opacity=float(self.opacity.value()),
                     flip=self.flip.isChecked(), ink_on=self.ink_box.isChecked(),
                     ink_colour=self.ink_colour.currentText(), ink_removal=float(self.removal.value()),
                     ink_strength=float(self.strength.value()), ink_edges=self.edges.currentText(),
                     ink_edge_size=float(self.edge_size.value()))
        self.edge_size.setEnabled(self.edges.currentText() != 'No fading')
        if was_ink != layer['ink_on']:
            self._fill_list()
        self._timer.start()

    def margin_value(self):
        return self.margin.value() / 100

    def _box(self):
        """Pixel size of the area inside the margins (for one page or the whole spread)."""
        cw, ch = self.canvas.page_size
        m = self.margin_value() * self.one_page[0]
        return round(cw - 2 * m), round(ch - 2 * m)

    def _margin_changed(self, *_):
        self.canvas.margin = self.margin_value()
        self.canvas.show_margins = self.show_margins.isChecked()
        bw, bh = self._box()
        self.best.setText(f'To draw a picture that fills the area inside the margins, make it <b>{bw} × {bh} px</b> '
                          '(or the same shape, bigger).')
        self.canvas.update()

    def _fit_margins(self):
        layer = self._layer()
        if layer:
            pil, _ = self.canvas.picture(layer)
            PL.fit_in_margins(layer, pil.size, self.canvas.page_size, self.one_page[0], self.margin_value())
            self._select(self.list.currentRow())

    def _canvas_changed(self):
        if self.canvas.current != self.list.currentRow():
            self.list.setCurrentRow(self.canvas.current)
        else:
            self._select(self.canvas.current)

    # --------------------------------------------------------------- actions
    def _add(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Pictures to put on this page', self.start_dir,
                                                'Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)')
        for k, path in enumerate(files):
            layer = PL.new_layer(path, spread=True) if self.spread else PL.new_layer(path)
            try:
                with Image.open(path) as im:
                    PL.fit_in_margins(layer, im.size, self.canvas.page_size, self.one_page[0], self.margin_value())
            except Exception:  # unreadable: keep the default place, it shows as empty
                pass
            off = 0.03 * k
            layer['x'], layer['y'] = layer['x'] + off, layer['y'] + off
            self.layers.append(layer)
        if files:
            self.start_dir = str(Path(files[0]).parent)
            self._fill_list()
            self.list.setCurrentRow(len(self.layers) - 1)

    def _duplicate(self):
        layer = self._layer()
        if layer:
            c = copy.deepcopy(layer)
            c['x'], c['y'] = float(c['x']) + 0.04, float(c['y']) + 0.04
            self.layers.append(c)
            self._fill_list()
            self.list.setCurrentRow(len(self.layers) - 1)

    def _remove(self):
        i = self.list.currentRow()
        if 0 <= i < len(self.layers):
            del self.layers[i]
            self._fill_list()
            self._select(self.list.currentRow())

    def _move(self, step):
        i = self.list.currentRow()
        j = i + step
        if 0 <= i < len(self.layers) and 0 <= j < len(self.layers):
            self.layers[i], self.layers[j] = self.layers[j], self.layers[i]
            self._fill_list()
            self.list.setCurrentRow(j)

    def _centre(self):
        layer = self._layer()
        if layer:
            layer['x'], layer['y'] = 0.5, 0.5
            self.canvas.update()

    def _straight(self):
        layer = self._layer()
        if layer:
            layer['rot'] = 0.0
            self._select(self.list.currentRow())

    def result_layers(self):
        return [dict(l) for l in self.layers if l.get('image')]
