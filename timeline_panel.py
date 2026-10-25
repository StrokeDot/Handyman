"""Visual timeline panel (step 3): clips you can select, drag, trim and edit.

The panel is a thin Qt shell over `timeline_edit.TimelineEditor`: the list shows the clips,
dragging reorders them, the buttons and spin boxes call the editor, and `changed` tells the
app to refresh the scene.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDoubleSpinBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from timeline_edit import TimelineEditor


class TimelinePanel(QWidget):
    """Select / drag / trim clips; emits `changed` after every edit."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor = TimelineEditor()
        self.base_frames = 30
        self._updating = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(QLabel('<b>Timeline</b> — click a clip; drag to reorder'))

        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemSelectionChanged.connect(self._selection)
        self.list.model().rowsMoved.connect(self._moved)
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        for text, fn in (('Delete', self._delete), ('Duplicate', self._dup),
                         ('Undo', self._undo), ('Redo', self._redo)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel('Speed'))
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.25, 4.0)
        self.speed.setSingleStep(0.25)
        self.speed.setValue(1.0)
        self.speed.valueChanged.connect(self._set_speed)
        row.addWidget(self.speed)
        row.addWidget(QLabel('Smooth'))
        self.smooth = QSpinBox()
        self.smooth.setRange(0, 100)
        self.smooth.setValue(100)
        self.smooth.valueChanged.connect(self._set_smooth)
        row.addWidget(self.smooth)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel('Start'))
        self.trim_start = QSpinBox()
        self.trim_start.setRange(0, 1000000)
        row.addWidget(self.trim_start)
        row.addWidget(QLabel('Length'))
        self.trim_len = QSpinBox()
        self.trim_len.setRange(1, 1000000)
        row.addWidget(self.trim_len)
        b = QPushButton('Trim')
        b.clicked.connect(self._trim)
        row.addWidget(b)
        lay.addLayout(row)

    # -------------------------------------------------------------- data
    def set_clips(self, clips):
        self.editor = TimelineEditor(clips)
        self.refresh()

    def refresh(self):
        self._updating = True
        self.list.clear()
        for i, c in enumerate(self.editor.clips()):
            item = QListWidgetItem(
                f'{i + 1}. {c.kind}  ·  start {c.start}  ·  {c.duration}f  ·  smooth {round(c.smoothness * 100)}')
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.list.addItem(item)
        self._updating = False
        self._fields()

    def _fields(self):
        clips = self.editor.clips()
        sel = self.editor.selected
        clip = clips[sel] if sel is not None and sel < len(clips) else None
        for w in (self.speed, self.smooth, self.trim_start, self.trim_len):
            w.setEnabled(clip is not None)
        if clip is not None:
            self._updating = True
            self.smooth.setValue(round(clip.smoothness * 100))
            self.trim_start.setValue(clip.start)
            self.trim_len.setValue(clip.duration)
            self._updating = False

    # ---------------------------------------------------------- handlers
    def _selection(self):
        if self._updating:
            return
        self.editor.select(self.list.currentRow())
        self._fields()

    def _moved(self, *_):
        if self._updating:
            return
        order = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
        if self.editor.reorder(order):
            self.refresh()
            self.changed.emit()

    def _delete(self):
        if self.editor.selected is not None and self.editor.delete(self.editor.selected):
            self.refresh()
            self.changed.emit()

    def _dup(self):
        if self.editor.selected is not None and self.editor.duplicate(self.editor.selected):
            self.refresh()
            self.changed.emit()

    def _undo(self):
        if self.editor.undo():
            self.refresh()
            self.changed.emit()

    def _redo(self):
        if self.editor.redo():
            self.refresh()
            self.changed.emit()

    def _set_speed(self, v):
        if not self._updating and self.editor.selected is not None:
            self.editor.set_speed(self.editor.selected, v, self.base_frames)
            self.refresh()
            self.changed.emit()

    def _set_smooth(self, v):
        if not self._updating and self.editor.selected is not None:
            self.editor.set_smoothness(self.editor.selected, v / 100)
            self.refresh()
            self.changed.emit()

    def _trim(self):
        if not self._updating and self.editor.selected is not None:
            self.editor.trim(self.editor.selected, start=self.trim_start.value(),
                             duration=self.trim_len.value())
            self.refresh()
            self.changed.emit()
