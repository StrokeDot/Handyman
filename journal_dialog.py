"""Journal design: swap every image of a journal-engine book (covers, spine, paper).

Each image must have the exact pixel size the template asks for, so a new cover always lands
on the book the same way the original did. Wrong sizes are refused with the size needed.
"""
import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QVBoxLayout)

import paths
import templates
from image_fit import ImageFitDialog

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
    def __init__(self, book, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Change book design')
        self.setMinimumWidth(900)
        self.book = dict(book)
        self.new_images = {}            # field -> source path chosen in this dialog
        self._thumbs, self._names = {}, {}
        lay = QVBoxLayout(self)

        g = QGroupBox('Book')
        f = QFormLayout(g)
        self.name = QLineEdit(book['name'])
        f.addRow('Template name', self.name)
        page = required_size(book, 'page')
        if page:
            f.addRow('Page images you add', QLabel(f'<b>{page[0]} × {page[1]} px</b> '
                                                   '(full page; transparent areas show the paper)'))
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
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    # ------------------------------------------------------------------ helpers
    def current_path(self, field):
        if field in self.new_images:
            return Path(self.new_images[field])
        p = templates._texture_path(self.book, self.book.get(field))
        return Path(p) if p else None

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
