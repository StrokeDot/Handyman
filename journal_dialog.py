"""Journal design: swap every image of a journal-engine book (covers, spine, paper).

Each image must have the exact pixel size the template asks for, so a new cover always lands
on the book the same way the original did. Wrong sizes are refused with the size needed.
"""
import shutil
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

import paths
import templates
from image_fit import ImageFitDialog, render as fit_render, save_adjusted

# field, caption, file name in the bundled template, what to know when making it
SLOTS = [
    ('front_exterior_image', 'Front cover · outside', 'front_ext.png',
     'What you see on the closed book. Left edge = spine side.'),
    ('back_exterior_image', 'Back cover · outside', 'back_ext.png',
     'Seen when the book is turned over. Right edge = spine side.'),
    ('front_interior_image', 'Front cover · inside', 'front_in.png',
     'Left side of the first spread. Right edge = spine side.'),
    ('back_interior_image', 'Back cover · inside', 'back_in.png',
     'Under the last page. Left edge = spine side.'),
    ('spine_exterior_image', 'Spine', 'spine.png',
     'Drawn wide; it is wrapped around the rounded spine. Top of image = top of book.'),
    ('leather_image', 'Leather (cover edges, inside of spine)', 'leather.png',
     'A plain leather texture.'),
    ('joint_image', 'Hinge strip', 'joint.png',
     'The thin strip between the open cover and the first page.'),
    ('paper_odd_image', 'Paper · right-hand pages', 'paper_odd.png',
     'Blank paper under page 1, 3, 5… Square corners on the LEFT (spine) edge.'),
    ('paper_even_image', 'Paper · left-hand pages', 'paper_even.png',
     'Blank paper under page 2, 4, 6… Square corners on the RIGHT (spine) edge.'),
]
THUMB = 56

# Page size presets (width x height of a page, cm). Only the shape matters on screen: the
# camera frames the whole book either way.
SIZE_PRESETS = [('Leather Journal (as shipped)', 15.0, 21.48), ('A5 notebook', 14.8, 21.0),
                ('Pocket notebook', 9.0, 14.0), ('Tall and narrow', 11.0, 21.0), ('Square', 18.0, 18.0),
                ('Wide (landscape)', 21.0, 15.0)]
RESHAPE = {'Stretch them to the new shape': 'stretch',
           'Crop them to fill (centred)': 'fill',
           'Let me adjust each one': 'each'}
COVER_EXTRA = 0.17          # a cover is this much taller than its page (page width = 1), see journal_geom
COVER_W = 1.08
PAGE_FIELDS = ('page', 'paper_odd_image', 'paper_even_image', 'paper_image', 'joint_image')


COVER_FIELDS = ('front_exterior_image', 'back_exterior_image', 'front_interior_image', 'back_interior_image')
PAGE_X = 0.03               # the pages start this far from the spine edge of a board (journal_geom.XB)


def _shape(v):
    """(page aspect, board width, board height) in page widths; a bare aspect = the default cover."""
    if isinstance(v, (int, float)):
        return float(v), COVER_W, float(v) + COVER_EXTRA
    return tuple(float(x) for x in v)


def sizes_for(sizes, old, new):
    """Pixel sizes for every image of a journal whose shape changes from old to new (each a page
    aspect, or (aspect, board width, board height) in page widths). Page-high images follow the
    page; covers follow the board's width and height; spine and leather follow its height."""
    (oa, ow, oh), (na, nw, nh) = _shape(old), _shape(new)
    out = {}
    for field, (w, h) in (sizes or {}).items():
        if field in PAGE_FIELDS:
            w2, h2 = w, h * na / oa
        elif field in COVER_FIELDS:
            w2, h2 = w * nw / ow, h * nh / oh
        else:
            w2, h2 = w, h * nh / oh
        out[field] = [max(8, int(round(w2))), max(8, int(round(h2)))]
    return out


def journal_cover(book):
    """(board width, board height) in page widths for a book (its own cover or the default)."""
    import journal_geom as G
    c = G.cover_of(book)
    a = float(book.get('page_aspect', 1.4318))
    return c if c else (COVER_W, a + COVER_EXTRA)


def image_size(path):
    img = QImage(str(path)) if path else QImage()
    return None if img.isNull() else (img.width(), img.height())


class ShapePreview(QWidget):
    """The closed book and the open spread drawn to scale with the new shape; the dashed gold
    outline is the shape the book has now."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(250)
        self.old = self.new = _shape(1.4318)
        self.mode = 'stretch'
        self.images = {}            # field -> QImage
        self._cache = {}

    def set_state(self, images, old, new, mode):
        self.images, self.old, self.new = images, _shape(old), _shape(new)
        self.mode = 'stretch' if mode == 'each' else mode
        self.update()

    def _fitted(self, field, w, h):
        img = self.images.get(field)
        if img is None or img.isNull() or w < 2 or h < 2:
            return None
        key = (field, img.cacheKey(), int(w), int(h), self.mode)
        if key not in self._cache:
            if len(self._cache) > 30:
                self._cache.clear()
            self._cache[key] = fit_render(img, (int(w), int(h)), self.mode)
        return self._cache[key]

    def _draw(self, p, field, rect, fallback):
        img = self._fitted(field, rect.width(), rect.height())
        if img is not None:
            p.drawImage(rect, img)
        else:
            p.fillRect(rect, QColor(fallback))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#1b1b20'))
        (na, nw, nh), (oa, ow, oh) = self.new, self.old
        cw, gap, mid = max(nw, ow), 0.25, 0.06
        total_w = cw + gap + 2 * cw + mid
        total_h = max(nh, oh)
        s = min((self.width() - 30) / total_w, (self.height() - 40) / total_h)
        x0 = (self.width() - total_w * s) / 2
        cy = (self.height() - 30) / 2 + 4                 # books centred on one line, like on the table

        def board(x, w, h, spine_right=False):
            left = x + (cw - w) if spine_right else x     # boards grow away from the spine
            return QRectF(x0 + left * s, cy - h * s / 2, w * s, h * s)

        def page_on(rect, aspect, spine_right=False):
            ph = aspect * s
            x = rect.right() - PAGE_X * s - s if spine_right else rect.x() + PAGE_X * s
            return QRectF(x, rect.center().y() - ph / 2, s, ph)
        closed = board(0, nw, nh)                         # closed book (spine on its left)
        self._draw(p, 'front_exterior_image', closed, '#5a3018')
        xl, xr = cw + gap, cw + gap + cw + mid            # open book: spine in the middle
        left, right = board(xl, nw, nh, True), board(xr, nw, nh)
        self._draw(p, 'front_interior_image', left, '#5a3018')
        self._draw(p, 'back_interior_image', right, '#5a3018')
        self._draw(p, 'paper_odd_image', page_on(right, na), '#e8cf9f')
        p.setPen(QPen(QColor(255, 255, 255, 90), 1, Qt.PenStyle.DotLine))
        p.drawRect(page_on(closed, na))                   # where the pages sit under the cover
        p.setPen(QPen(QColor('#f0b94a'), 1.5, Qt.PenStyle.DashLine))
        for r in (board(0, ow, oh), board(xl, ow, oh, True), board(xr, ow, oh)):
            p.drawRect(r)
        p.setPen(QColor('#cfcfd6'))
        p.drawText(QRectF(0, self.height() - 22, self.width(), 18), Qt.AlignmentFlag.AlignCenter,
                   'Dashed gold line = the book now  ·  dotted line = where the pages sit')


def required_size(book, field):
    sizes = book.get('image_sizes') or {}
    s = sizes.get(field)
    return (int(s[0]), int(s[1])) if s else None


def check_size(book, field, path):
    """None if the image fits the slot, else a message saying what size is needed."""
    img = QImage(str(path))
    if img.isNull():
        return f'{Path(path).name} could not be opened as an image.'
    need = required_size(book, field)
    if need and (img.width(), img.height()) != need:
        return (f'{Path(path).name} is {img.width()} × {img.height()} px.\n'
                f'This image must be exactly {need[0]} × {need[1]} px.')
    return None


def bundled_original(field):
    name = next((f for fl, _, f, _ in SLOTS if fl == field), None)
    p = paths.resource_dir() / 'resources' / 'books' / 'leather-journal' / name if name else None
    return p if p and p.exists() else None


class JournalDialog(QDialog):
    def __init__(self, book, parent=None, preview=None):
        super().__init__(parent)
        self.orig_book = dict(book)
        self.preview_content = preview          # (page images, app values) for the 3D comparison
        self.setWindowTitle('Change book design')
        self.setMinimumWidth(900)
        self.book = dict(book)
        self.new_images = {}            # field -> source path chosen in this dialog
        self._thumbs, self._names = {}, {}
        lay = QVBoxLayout(self)

        self.orig_aspect = float(book.get('page_aspect', 1.4318))
        self.orig_cover = journal_cover(book)
        self.orig_sizes = dict(book.get('image_sizes') or {})
        self._sizes = {}

        body = QWidget()
        lay_outer = lay
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        lay_outer.addWidget(scroll, 1)

        g = QGroupBox('Book')
        f = QFormLayout(g)
        self.name = QLineEdit(book['name'])
        f.addRow('Template name', self.name)
        self.page_label = QLabel()
        if required_size(book, 'page'):
            f.addRow('Page images you add', self.page_label)
        lay.addWidget(g)

        g = QGroupBox('Size and shape')
        row = QHBoxLayout(g)
        form = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItems([n for n, _, _ in SIZE_PRESETS] + ['Custom'])
        self.preset.currentTextChanged.connect(self._preset_chosen)
        form.addRow('Shape', self.preset)
        cm = book.get('page_size_cm') or [15.0, round(15.0 * self.orig_aspect, 2)]
        self.page_w, self.page_h = QDoubleSpinBox(), QDoubleSpinBox()
        self.cover_w, self.cover_h = QDoubleSpinBox(), QDoubleSpinBox()
        cover = [self.orig_cover[0] * cm[0], self.orig_cover[1] * cm[0]]
        for spin, val in ((self.page_w, cm[0]), (self.page_h, cm[1]), (self.cover_w, cover[0]),
                          (self.cover_h, cover[1])):
            spin.setRange(3.0, 80.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.5)
            spin.setSuffix(' cm')
            spin.setValue(round(float(val), 2))
            spin.valueChanged.connect(self._size_changed)
        form.addRow('Page width', self.page_w)
        form.addRow('Page height', self.page_h)
        self.follow = QCheckBox('Cover follows the pages')
        self.follow.setToolTip('On: the cover is always a little bigger than the pages.\n'
                               'Off: set the cover size yourself (it can never be smaller than the pages).')
        self.follow.setChecked(not book.get('cover_size_cm'))
        self.follow.toggled.connect(self._size_changed)
        form.addRow('', self.follow)
        form.addRow('Cover width', self.cover_w)
        form.addRow('Cover height', self.cover_h)
        self.reshape = QComboBox()
        self.reshape.addItems(list(RESHAPE))
        self.reshape.setToolTip('What happens to the cover, spine and paper images when the shape changes')
        self.reshape.currentTextChanged.connect(self._size_changed)
        form.addRow('My images', self.reshape)
        self.shape_note = QLabel()
        self.shape_note.setWordWrap(True)
        self.shape_note.setObjectName('hint')
        form.addRow(self.shape_note)
        self.compare_btn = QPushButton('Compare in the video view…')
        self.compare_btn.setObjectName('accent')
        self.compare_btn.setToolTip('See the book now and the new size side by side, animated, '
                                    'exactly as the video shows them')
        self.compare_btn.clicked.connect(self._compare)
        self.compare_btn.setEnabled(preview is not None)
        form.addRow(self.compare_btn)
        row.addLayout(form, 2)
        self.preview = ShapePreview()
        row.addWidget(self.preview, 3)
        lay.addWidget(g)

        g = QGroupBox('Thickness and edges')
        f = QFormLayout(g)
        self.board_mm = QDoubleSpinBox()
        self.board_mm.setRange(1.0, 10.0)
        self.board_mm.setSingleStep(0.2)
        self.board_mm.setDecimals(1)
        self.board_mm.setSuffix(' mm')
        self.board_mm.setValue(float(book.get('board_mm') or 4.2))
        self.board_mm.setToolTip('How thick each cover board is (the Leather Journal: 4.2 mm)')
        f.addRow('Cover thickness', self.board_mm)
        self.paper_mm = QDoubleSpinBox()
        self.paper_mm.setRange(0.15, 1.0)
        self.paper_mm.setSingleStep(0.05)
        self.paper_mm.setDecimals(2)
        self.paper_mm.setSuffix(' mm')
        self.paper_mm.setValue(float(book.get('paper_mm') or 0.45))
        self.paper_mm.setToolTip('How thick one sheet of paper is (the Leather Journal: 0.45 mm). '
                                 'Thicker paper makes a thicker book with the same number of pages.')
        f.addRow('Paper thickness (one sheet)', self.paper_mm)
        note = QLabel('The number of pages ("Pages in the book" in the main window) also changes how thick '
                      'the book is: pages x paper thickness. A very thick book is limited so that the turning '
                      'pages never touch.')
        note.setObjectName('hint')
        note.setWordWrap(True)
        f.addRow(note)
        self.edge_mode = QComboBox()
        self.edge_mode.addItem('Match the cover picture', 'match')
        self.edge_mode.addItem('Use the leather image as it is', 'leather')
        self.edge_mode.setToolTip('The colour of the cover boards\' edges (the thickness of the cover) and of '
                                  'the inside of the spine. "Match" takes the colour from the edge of your cover '
                                  'picture, so a blue cover gets blue edges.')
        i = self.edge_mode.findData(book.get('edge_mode') or 'match')
        self.edge_mode.setCurrentIndex(max(0, i))
        f.addRow('Cover edges', self.edge_mode)
        lay.addWidget(g)

        g = QGroupBox('Images (each must be exactly the size shown)')
        grid = QGridLayout(g)
        for r, (field, caption, _, hint) in enumerate(SLOTS):
            thumb = QLabel()
            thumb.setFixedSize(THUMB, THUMB)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._thumbs[field] = thumb
            need = required_size(book, field)
            title = QLabel(f'<b>{caption}</b><br><span style="color:gray">{hint}</span>')
            title.setWordWrap(True)
            title.setMinimumHeight(THUMB)
            size = QLabel(f'{need[0]} × {need[1]} px' if need else 'any size')
            self._sizes[field] = size
            name = QLabel()
            self._names[field] = name
            choose = QPushButton('Choose…')
            choose.clicked.connect(lambda _=False, fl=field, cp=caption: self._choose(fl, cp))
            restore = QPushButton('Original')
            restore.setToolTip('Put back the image the Leather Journal shipped with')
            restore.clicked.connect(lambda _=False, fl=field: self._restore(fl))
            restore.setEnabled(bundled_original(field) is not None)
            grid.addWidget(thumb, r, 0)
            grid.addWidget(title, r, 1)
            grid.addWidget(size, r, 2)
            grid.addWidget(name, r, 3)
            grid.addWidget(choose, r, 4)
            grid.addWidget(restore, r, 5)
            self._show(field)
        grid.setColumnStretch(1, 1)
        lay.addWidget(g)

        row = QHBoxLayout()
        guide = QPushButton('Save size guides…')
        guide.setToolTip('Save the current images, named with their required size, to paint over')
        guide.clicked.connect(self._save_guides)
        row.addWidget(guide)
        row.addStretch(1)
        lay.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay_outer.addWidget(buttons)
        self.resize(1000, 860)
        self._size_changed()

    # ------------------------------------------------------------------ helpers
    def current_path(self, field):
        if field in self.new_images:
            return Path(self.new_images[field])
        p = templates._texture_path(self.book, self.book.get(field))
        return Path(p) if p else None

    # ------------------------------------------------------------------ size and shape
    def new_aspect(self):
        return round(self.page_h.value() / max(0.1, self.page_w.value()), 4)

    def new_shape(self):
        """(page aspect, board width, board height) in page widths, as now set."""
        pw = max(0.1, self.page_w.value())
        return self.new_aspect(), self.cover_w.value() / pw, self.cover_h.value() / pw

    def orig_shape(self):
        return (self.orig_aspect,) + tuple(self.orig_cover)

    def shape_changed(self):
        return any(abs(a - b) > 3e-3 for a, b in zip(self.new_shape(), self.orig_shape()))

    def _fix_cover(self):
        """Cover follows the pages, or at least covers them (the smallest board allowed)."""
        import journal_geom as G
        pw, aspect = self.page_w.value(), self.new_aspect()
        if self.follow.isChecked():
            w, h = pw * COVER_W, pw * (aspect + COVER_EXTRA)
        else:
            lo = G.min_cover(aspect)
            w, h = max(self.cover_w.value(), pw * lo[0]), max(self.cover_h.value(), pw * lo[1])
        for spin, v in ((self.cover_w, w), (self.cover_h, h)):
            spin.blockSignals(True)
            spin.setValue(round(v, 2))
            spin.setEnabled(not self.follow.isChecked())
            spin.blockSignals(False)

    def _match_preset(self):
        w, h = self.page_w.value(), self.page_h.value()
        name = next((n for n, pw, ph in SIZE_PRESETS if abs(pw - w) < 0.06 and abs(ph - h) < 0.06), 'Custom')
        self.preset.blockSignals(True)
        self.preset.setCurrentText(name)
        self.preset.blockSignals(False)

    def _preset_chosen(self, name):
        for n, w, h in SIZE_PRESETS:
            if n == name:
                for spin, v in ((self.page_w, w), (self.page_h, h)):
                    spin.blockSignals(True)
                    spin.setValue(v)
                    spin.blockSignals(False)
                self._size_changed()

    def _size_changed(self, *_):
        self._match_preset()
        self._fix_cover()
        aspect = self.new_aspect()
        self.book['page_aspect'] = aspect
        self.book['page_size_cm'] = [round(self.page_w.value(), 2), round(self.page_h.value(), 2)]
        self.book['cover_size_cm'] = (None if self.follow.isChecked() else
                                      [round(self.cover_w.value(), 2), round(self.cover_h.value(), 2)])
        if not self.shape_changed():          # unchanged (or only rounded): keep everything exactly as it was
            for key in ('page_aspect', 'page_size_cm', 'cover_size_cm'):
                self.book[key] = self.orig_book.get(key)
            self.book['page_aspect'] = self.orig_aspect
            if self.orig_sizes:
                self.book['image_sizes'] = dict(self.orig_sizes)
        elif self.orig_sizes:
            self.book['image_sizes'] = sizes_for(self.orig_sizes, self.orig_shape(), self.new_shape())
        for field, label in self._sizes.items():
            need = required_size(self.book, field)
            label.setText(f'{need[0]} × {need[1]} px' if need else 'any size')
        page = required_size(self.book, 'page')
        if page:
            self.page_label.setText(f'<b>{page[0]} × {page[1]} px</b> (full page; transparent areas show the paper)')
        self.reshape.setEnabled(self.shape_changed())
        if self.shape_changed():
            self.shape_note.setText('The preview shows the new shape. When you press Save, every image that is '
                                    'not the new size is made to fit as chosen above. Your original files '
                                    'are not changed.')
        else:
            self.shape_note.setText('Change the width or height to make the book taller, shorter, wider or '
                                    'narrower. The preview shows the result before anything is saved.')
        images = {field: self._qimage(self.current_path(field)) for field, *_ in SLOTS}
        self.preview.set_state(images, self.orig_shape(), self.new_shape(), RESHAPE[self.reshape.currentText()])

    def _qimage(self, path):
        """A small copy of the image for the 2D preview (full-size images made it lag)."""
        if not path or not Path(path).exists():
            return None
        cache = self.__dict__.setdefault('_qimages', {})
        key = (str(path), Path(path).stat().st_mtime_ns)
        if key not in cache:
            img = QImage(str(path))
            if not img.isNull() and max(img.width(), img.height()) > 420:
                img = img.scaled(420, 420, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            cache[key] = img
        return cache[key]

    def _compare(self):
        """Open the side-by-side 3D comparison of the book now and with the new size."""
        from PySide6.QtWidgets import QApplication
        from compare_view import CompareDialog
        images, values = self.preview_content
        new_book = self.result_book()
        mode = RESHAPE[self.reshape.currentText()]
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for field, *_ in SLOTS:
                p = self.current_path(field)
                if p and p.exists():
                    new_book[field] = str(p)
                    need = required_size(new_book, field)
                    if mode == 'fill' and need and image_size(p) != tuple(need):
                        new_book[field] = self._cropped(p, need)
        finally:
            QApplication.restoreOverrideCursor()
        CompareDialog(self.orig_book, new_book, images, values, self).exec()

    def _cropped(self, path, need):
        cache = self.__dict__.setdefault('_crops', {})
        key = (str(path), tuple(need))
        if key not in cache:
            cache[key] = save_adjusted(QImage(str(path)), need, 'fill', name=Path(path).name)
        return cache[key]

    def _save(self):
        """Fit every image that does not have its (possibly new) required size, then accept."""
        mode = RESHAPE[self.reshape.currentText()]
        captions = {fl: cp for fl, cp, _, _ in SLOTS}
        for field in [fl for fl in self.book.get('image_sizes') or {} if fl != 'page']:
            need = required_size(self.book, field)
            src = self.current_path(field)
            have = image_size(src) if src and src.exists() else None
            if not need or not have or tuple(have) == tuple(need):
                continue
            if mode == 'each' and field in captions:
                fit = ImageFitDialog(str(src), need, captions[field], self)
                if fit.exec() == QDialog.DialogCode.Accepted and fit.result_path:
                    self.new_images[field] = fit.result_path
                    continue
            self.new_images[field] = save_adjusted(QImage(str(src)), need, 'fill' if mode == 'fill' else 'stretch',
                                                   name=f'{field}.png')
        self.accept()

    def _show(self, field):
        p = self.current_path(field)
        pix = QPixmap(str(p)) if p and p.exists() else QPixmap()
        thumb = self._thumbs[field]
        if pix.isNull():
            thumb.setPixmap(QPixmap())
            thumb.setText('—')
        else:
            thumb.setPixmap(pix.scaled(THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))
        mark = '  (new)' if field in self.new_images else ''
        self._names[field].setText((p.name if p else '(none)') + mark)
        if hasattr(self, 'preview'):
            self._size_changed()

    def _choose(self, field, caption):
        need = required_size(self.book, field)
        hint = f' — must be {need[0]} × {need[1]} px' if need else ''
        path, _ = QFileDialog.getOpenFileName(self, f'{caption}{hint}', '',
                                              'Images (*.png *.jpg *.jpeg *.webp)')
        if not path:
            return
        problem = check_size(self.book, field, path)
        if problem:
            if QImage(path).isNull() or not need:
                QMessageBox.warning(self, 'Wrong image size', f'{caption}\n\n{problem}')
                return
            ask = QMessageBox.question(self, 'Different size',
                                       f'{caption}\n\n{problem}\n\nAdjust it for you? You choose what part '
                                       'shows; your original file is not changed.',
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ask != QMessageBox.StandardButton.Yes:
                return
            fit = ImageFitDialog(path, need, caption, self)
            if fit.exec() != QDialog.DialogCode.Accepted or not fit.result_path:
                return
            path = fit.result_path
        self.new_images[field] = path
        self._show(field)

    def _restore(self, field):
        p = bundled_original(field)
        if p:
            self.new_images[field] = str(p)
            self._show(field)

    def _save_guides(self):
        folder = QFileDialog.getExistingDirectory(self, 'Save size guides to')
        if not folder:
            return
        saved = 0
        for field, caption, _, _ in SLOTS:
            p = self.current_path(field)
            need = required_size(self.book, field)
            if not p or not p.exists():
                continue
            tag = f' ({need[0]}x{need[1]})' if need else ''
            safe = caption.replace('·', '-').replace('/', '-').replace('(', '').replace(')', '')
            shutil.copyfile(p, Path(folder) / f'{safe}{tag}{p.suffix.lower()}')
            saved += 1
        QMessageBox.information(self, 'Size guides', f'Saved {saved} images to\n{folder}\n\n'
                                'Paint over them and keep the size exactly the same.')

    def result_book(self):
        b = dict(self.book)
        b['name'] = self.name.text().strip() or 'Journal'
        b['board_mm'] = None if abs(self.board_mm.value() - 4.2) < 1e-6 else round(self.board_mm.value(), 2)
        b['paper_mm'] = None if abs(self.paper_mm.value() - 0.45) < 1e-6 else round(self.paper_mm.value(), 3)
        b['edge_mode'] = self.edge_mode.currentData()
        return b
