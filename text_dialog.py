"""Write text for a page: the words, a font (StrokeScribe's fonts), size, colour and alignment,
with a preview on the book's paper."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

import fonts

DOWNLOAD = '  (download)'


class _Preview(QWidget):
    def __init__(self, paper_path):
        super().__init__()
        self.paper = QImage(str(paper_path)) if paper_path else QImage()
        self.text_img = QImage()
        self.width_share = 0.84
        self.setMinimumSize(320, 300)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#1b1b20'))
        aspect = (self.paper.height() / self.paper.width()) if not self.paper.isNull() else 1.43
        h = self.height() - 16
        w = h / aspect
        if w > self.width() - 16:
            w = self.width() - 16
            h = w * aspect
        x, y = (self.width() - w) / 2, (self.height() - h) / 2
        if not self.paper.isNull():
            p.drawImage(int(x), int(y), self.paper.scaled(int(w), int(h), Qt.AspectRatioMode.IgnoreAspectRatio,
                                                          Qt.TransformationMode.SmoothTransformation))
        else:
            p.fillRect(int(x), int(y), int(w), int(h), QColor('#e8dcc4'))
        if not self.text_img.isNull():
            s = w * self.width_share / self.text_img.width()
            tw, th = self.text_img.width() * s, self.text_img.height() * s
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(int(x + (w - tw) / 2), int(y + 0.08 * w), self.text_img.scaled(
                max(1, int(tw)), max(1, int(th)), Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation))


class TextDialog(QDialog):
    """Returns text settings (fonts.TEXT_DEFAULTS keys) with result_text()."""

    def __init__(self, text=None, paper_path=None, page_px=982, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Text on the page')
        self.page_px = page_px
        t = dict(fonts.TEXT_DEFAULTS)
        t.update(text or {})
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        lay.addLayout(left, 3)
        left.addWidget(QLabel('Type the text:'))
        self.edit = QPlainTextEdit(t['text'])
        self.edit.setPlaceholderText('Dear diary…')
        self.edit.textChanged.connect(self._later)
        left.addWidget(self.edit, 1)
        f = QFormLayout()
        frow = QHBoxLayout()
        self.font = QComboBox()
        self.font.setMaxVisibleItems(25)
        self._fill_fonts(t['font'])
        self.font.currentIndexChanged.connect(self._font_chosen)
        frow.addWidget(self.font, 1)
        imp = QPushButton('Use my own font file…')
        imp.setToolTip('A .ttf or .otf file from your computer')
        imp.clicked.connect(self._import)
        frow.addWidget(imp)
        f.addRow('Font', frow)
        self.size = QDoubleSpinBox()
        self.size.setRange(5, 200)
        self.size.setDecimals(0)
        self.size.setSuffix(' pt')
        self.size.setValue(float(t['size']))
        self.size.setToolTip('12 pt reads like a printed book; 24 pt and up for titles')
        self.size.valueChanged.connect(self._later)
        f.addRow('Size', self.size)
        self.colour = QComboBox()
        self.colour.addItems(list(fonts.TEXT_COLOURS))
        self.colour.setCurrentText(t['colour'] if isinstance(t['colour'], str) else 'Dark grey (like printed text)')
        self.colour.currentTextChanged.connect(self._later)
        f.addRow('Colour', self.colour)
        self.align = QComboBox()
        for label, v in (('Left', 'left'), ('Centred', 'centre'), ('Right', 'right')):
            self.align.addItem(label, v)
        self.align.setCurrentIndex(max(0, self.align.findData(t['align'])))
        self.align.currentIndexChanged.connect(self._later)
        f.addRow('Alignment', self.align)
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(0.8, 3.0)
        self.spacing.setSingleStep(0.05)
        self.spacing.setValue(float(t['spacing']))
        self.spacing.valueChanged.connect(self._later)
        f.addRow('Line spacing', self.spacing)
        left.addLayout(f)
        self.note = QLabel('Fonts come from StrokeScribe\'s list (Google Fonts, free to use). One marked '
                           '"download" is fetched once, with its licence, and then works in both apps.')
        self.note.setObjectName('hint')
        self.note.setWordWrap(True)
        left.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Put on the page')
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        left.addWidget(buttons)
        self.preview = _Preview(paper_path)
        lay.addWidget(self.preview, 2)
        self._timer = QTimer(self, singleShot=True, interval=150)
        self._timer.timeout.connect(self._render)
        self._last_font = self._font_name()
        self.resize(1000, 620)
        self._render()

    # ---------------------------------------------------------------- fonts
    def _fill_fonts(self, current):
        model = QStandardItemModel()
        self.font.setModel(model)

        def header(text):
            it = QStandardItem(text)
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            f = it.font()
            f.setBold(True)
            it.setFont(f)
            model.appendRow(it)

        def add(name):
            have = fonts.installed_font(name) is not None
            it = QStandardItem(name + ('' if have else DOWNLOAD))
            it.setData(name, Qt.ItemDataRole.UserRole)
            model.appendRow(it)
        header('Ready to use')
        add(fonts.BUILT_IN)
        for name in fonts.ALL_FONTS:
            if fonts.installed_font(name):
                add(name)
        for name in fonts.imported_fonts():
            add(name)
        for group, names in fonts.FONT_GROUPS.items():
            rest = [n for n in names if not fonts.installed_font(n)]
            if rest:
                header(f'{group} - download once')
                for name in rest:
                    add(name)
        for i in range(model.rowCount()):
            if model.item(i).data(Qt.ItemDataRole.UserRole) == current:
                self.font.setCurrentIndex(i)
                return
        self.font.setCurrentIndex(1)

    def _font_name(self):
        return self.font.currentData(Qt.ItemDataRole.UserRole) or fonts.BUILT_IN

    def _font_chosen(self, *_):
        name = self._font_name()
        if fonts.installed_font(name) is None:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                fonts.download_google_font(name)
            except Exception as exc:
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(self, 'Font', f'{name} could not be downloaded:\n{exc}')
                self._fill_fonts(self._last_font)
                return
            QApplication.restoreOverrideCursor()
            self.font.blockSignals(True)
            self._fill_fonts(name)
            self.font.blockSignals(False)
        self._last_font = name
        self._later()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Your font file', '', 'Fonts (*.ttf *.otf)')
        if not path:
            return
        try:
            name = fonts.import_font(path)
        except Exception as exc:
            QMessageBox.warning(self, 'Font', str(exc))
            return
        self.font.blockSignals(True)
        self._fill_fonts(name)
        self.font.blockSignals(False)
        self._last_font = name
        self._render()

    # ---------------------------------------------------------------- preview / result
    def result_text(self):
        return dict(fonts.TEXT_DEFAULTS, text=self.edit.toPlainText(), font=self._font_name(),
                    size=self.size.value(), colour=self.colour.currentText(), align=self.align.currentData(),
                    spacing=self.spacing.value())

    def _later(self, *_):
        self._timer.start()

    def _render(self):
        img = fonts.render_text(self.result_text(), self.page_px)
        data = img.tobytes('raw', 'RGBA')
        self.preview.text_img = QImage(data, img.width, img.height, img.width * 4,
                                       QImage.Format.Format_RGBA8888).copy()
        self.preview.width_share = fonts.TEXT_DEFAULTS['width']
        self.preview.update()

    def _ok(self):
        if not self.edit.toPlainText().strip():
            QMessageBox.information(self, 'Text', 'Type some text first.')
            return
        self.accept()
