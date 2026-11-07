"""Journal design: swap every image of a journal-engine book (covers, spine, paper).

Each image must have the exact pixel size the template asks for, so a new cover always lands
on the book the same way the original did. Wrong sizes are refused with the size needed.
"""
import shutil
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
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


def sizes_for(sizes, old_aspect, new_aspect):
    """Pixel sizes for every image of a journal whose page shape changes from old to new aspect
    (height / width). Widths stay; page-high images follow the page, the rest follow the cover."""
    out = {}
    for field, (w, h) in (sizes or {}).items():
        if field in PAGE_FIELDS:
            r = new_aspect / old_aspect
        else:
            r = (new_aspect + COVER_EXTRA) / (old_aspect + COVER_EXTRA)
        out[field] = [int(w), max(8, int(round(h * r)))]
    return out


def image_size(path):
    img = QImage(str(path)) if path else QImage()
    return None if img.isNull() else (img.width(), img.height())


class ShapePreview(QWidget):
    """The closed book and the open spread drawn to scale with the new shape; the dashed gold
    outline is the shape the book has now."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(250)
        self.old_aspect = self.new_aspect = 1.4318
        self.mode = 'stretch'
        self.images = {}            # field -> QImage
        self._cache = {}

    def set_state(self, images, old_aspect, new_aspect, mode):
        self.images, self.old_aspect, self.new_aspect = images, old_aspect, new_aspect
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
        hc_new, hc_old = self.new_aspect + COVER_EXTRA, self.old_aspect + COVER_EXTRA
        gap = 0.25
        total_w = COVER_W + gap + 2 * COVER_W + 0.06
        total_h = max(hc_new, hc_old)
        s = min((self.width() - 30) / total_w, (self.height() - 40) / total_h)
        x0 = (self.width() - total_w * s) / 2
        base = (self.height() - 30 + total_h * s) / 2     # the line both books stand on

        def cover_rect(x, hc):
            return QRectF(x0 + x * s, base - hc * s, COVER_W * s, hc * s)
        self._draw(p, 'front_exterior_image', cover_rect(0, hc_new), '#5a3018')        # closed book
        xl = COVER_W + gap                                # open book: inside covers + first page
        left = cover_rect(xl, hc_new)
        right = cover_rect(xl + COVER_W + 0.06, hc_new)
        self._draw(p, 'front_interior_image', left, '#5a3018')
        self._draw(p, 'back_interior_image', right, '#5a3018')
        page_h = self.new_aspect * s
        page = QRectF(right.x() + 0.02 * s, right.y() + (right.height() - page_h) / 2, 1.0 * s, page_h)
        self._draw(p, 'paper_odd_image', page, '#e8cf9f')
        p.setPen(QPen(QColor('#f0b94a'), 1.5, Qt.PenStyle.DashLine))
        for x in (0, xl, xl + COVER_W + 0.06):
            p.drawRect(cover_rect(x, hc_old))
        p.setPen(QColor('#cfcfd6'))
        p.drawText(QRectF(0, self.height() - 22, self.width(), 18), Qt.AlignmentFlag.AlignCenter,
                   'Dashed gold line = the shape the book has now')


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
        for spin, val in ((self.page_w, cm[0]), (self.page_h, cm[1])):
            spin.setRange(5.0, 60.0)
            spin.setDecimals(1)
            spin.setSingleStep(0.5)
            spin.setSuffix(' cm')
            spin.setValue(float(val))
            spin.valueChanged.connect(self._size_changed)
        form.addRow('Page width', self.page_w)
        form.addRow('Page height', self.page_h)
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

    def shape_changed(self):
        return abs(self.new_aspect() - self.orig_aspect) > 1e-3

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
        aspect = self.new_aspect()
        self.book['page_aspect'] = aspect
        self.book['page_size_cm'] = [round(self.page_w.value(), 2), round(self.page_h.value(), 2)]
        if self.orig_sizes:
            self.book['image_sizes'] = sizes_for(self.orig_sizes, self.orig_aspect, aspect)
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
        self.preview.set_state(images, self.orig_aspect, aspect, RESHAPE[self.reshape.currentText()])

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
        new_book = dict(self.book)
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
        return b
