"""Window for designing a book template: leather, paper, emblem, title, stitching."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QSpinBox,
    QVBoxLayout,
)

import templates


class ColorButton(QPushButton):
    def __init__(self, value):
        super().__init__()
        self.setFixedWidth(90)
        self.clicked.connect(self._pick)
        self.set_value(value)

    def set_value(self, value):
        self.value = value
        text = '#222' if QColor(value).lightness() > 128 else '#eee'
        self.setStyleSheet(f'background:{value};color:{text}')
        self.setText(value)

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.value), self, 'Choose colour')
        if c.isValid():
            self.set_value(c.name())


def slider(lo, hi, value):
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(round(value))
    return s


class BookDialog(QDialog):
    def __init__(self, book, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Book design')
        self.book = dict(book)
        self.new_image = None
        lay = QVBoxLayout(self)

        g = QGroupBox('Book')
        f = QFormLayout(g)
        self.name = QLineEdit(book['name'])
        f.addRow('Template name', self.name)
        self.leather = ColorButton(book['leather_color'])
        f.addRow('Leather colour', self.leather)
        self.back_own = QCheckBox('Back cover has its own colour')
        self.back_cover = ColorButton(book.get('back_cover_color') or book['leather_color'])
        self.back_own.setChecked(bool(book.get('back_cover_color')))
        self.back_own.toggled.connect(self.back_cover.setEnabled)
        self.back_cover.setEnabled(self.back_own.isChecked())
        row = QHBoxLayout()
        row.addWidget(self.back_own)
        row.addWidget(self.back_cover)
        f.addRow(row)
        self.inside_own = QCheckBox('Inside cover has its own colour')
        self.inside_cover = ColorButton(book.get('inside_cover_color') or book['paper_color'])
        self.inside_own.setChecked(bool(book.get('inside_cover_color')))
        self.inside_own.toggled.connect(self.inside_cover.setEnabled)
        self.inside_cover.setEnabled(self.inside_own.isChecked())
        row = QHBoxLayout()
        row.addWidget(self.inside_own)
        row.addWidget(self.inside_cover)
        f.addRow(row)
        self.stitching = QCheckBox('Stitching around the cover')
        self.stitching.setChecked(bool(book['stitching']))
        self.thread = ColorButton(book['thread_color'])
        row = QHBoxLayout()
        row.addWidget(self.stitching)
        row.addWidget(self.thread)
        f.addRow(row)
        self.bands = QSpinBox()
        self.bands.setRange(0, 6)
        self.bands.setValue(int(book['spine_bands']))
        f.addRow('Raised bands on spine', self.bands)
        self.aspect = QDoubleSpinBox()
        self.aspect.setRange(1.0, 1.8)
        self.aspect.setSingleStep(0.05)
        self.aspect.setValue(float(book['page_aspect']))
        f.addRow('Page shape (height ÷ width)', self.aspect)
        lay.addWidget(g)

        g = QGroupBox('Paper')
        f = QFormLayout(g)
        self.paper = ColorButton(book['paper_color'])
        f.addRow('Paper colour', self.paper)
        self.age = slider(0, 100, book['paper_age'] * 100)
        f.addRow('Age / stains', self.age)
        self.burn = slider(0, 100, book['burn'] * 100)
        f.addRow('Burnt edges', self.burn)
        lay.addWidget(g)

        g = QGroupBox('Emblem on the cover')
        f = QFormLayout(g)
        self.preview = QLabel('(none)')
        self.preview.setFixedSize(96, 96)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._show_emblem(self._emblem_path())
        row = QHBoxLayout()
        row.addWidget(self.preview)
        b = QPushButton('Choose image…')
        b.clicked.connect(self._choose)
        r = QPushButton('Remove')
        r.clicked.connect(self._remove)
        row.addWidget(b)
        row.addWidget(r)
        f.addRow(row)
        self.em_style = QComboBox()
        self.em_style.addItems(list(templates.EMBLEM_STYLES))
        self.em_style.setCurrentText(_label(templates.EMBLEM_STYLES, book['emblem_style']))
        f.addRow('Style', self.em_style)
        self.em_size = slider(10, 90, book['emblem_size'] * 100)
        f.addRow('Size', self.em_size)
        self.em_y = slider(-45, 45, book['emblem_y'] * 100)
        f.addRow('Up / down', self.em_y)
        lay.addWidget(g)

        g = QGroupBox('Title on the cover')
        f = QFormLayout(g)
        self.title = QLineEdit(book.get('title', ''))
        self.title.setPlaceholderText('Leave empty for no title')
        f.addRow('Text', self.title)
        self.t_style = QComboBox()
        self.t_style.addItems(list(templates.TITLE_STYLES))
        self.t_style.setCurrentText(_label(templates.TITLE_STYLES, book['title_style']))
        f.addRow('Style', self.t_style)
        self.t_size = slider(3, 15, book['title_size'] * 100)
        f.addRow('Size', self.t_size)
        self.t_y = slider(-45, 45, book['title_y'] * 100)
        f.addRow('Up / down', self.t_y)
        lay.addWidget(g)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _emblem_path(self):
        if self.new_image:
            return self.new_image
        if self.book.get('emblem') and self.book.get('folder'):
            p = Path(self.book['folder']) / self.book['emblem']
            return str(p) if p.exists() else None
        return None

    def _show_emblem(self, path):
        if path:
            self.preview.setPixmap(QPixmap(path).scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                                                        Qt.TransformationMode.SmoothTransformation))
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText('(none)')

    def _choose(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Emblem image (a PNG with transparency works best)', '',
                                              'Images (*.png *.jpg *.jpeg *.webp)')
        if path:
            self.new_image = path
            self._show_emblem(path)

    def _remove(self):
        self.new_image = None
        self.book['emblem'] = None
        self._show_emblem(None)

    def result_book(self):
        b = dict(self.book)
        b.update(name=self.name.text().strip() or 'Book', leather_color=self.leather.value,
                 back_cover_color=self.back_cover.value if self.back_own.isChecked() else None,
                 inside_cover_color=self.inside_cover.value if self.inside_own.isChecked() else None,
                 stitching=self.stitching.isChecked(), thread_color=self.thread.value,
                 spine_bands=self.bands.value(), page_aspect=round(self.aspect.value(), 2),
                 paper_color=self.paper.value, paper_age=self.age.value() / 100, burn=self.burn.value() / 100,
                 emblem_style=templates.EMBLEM_STYLES[self.em_style.currentText()],
                 emblem_size=self.em_size.value() / 100, emblem_y=self.em_y.value() / 100,
                 title=self.title.text(), title_style=templates.TITLE_STYLES[self.t_style.currentText()],
                 title_size=self.t_size.value() / 100, title_y=self.t_y.value() / 100)
        return b


def _label(mapping, value):
    for k, v in mapping.items():
        if v == value:
            return k
    return next(iter(mapping))
