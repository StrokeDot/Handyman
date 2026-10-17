"""Handyman: 3D book page-turn overlays with transparent backgrounds.

Pick a book template and your page images, adjust the timing, press Render.
Blender does the 3D work in the background; you never need to open it.
"""
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QProgressDialog, QPushButton, QScrollArea, QSlider, QSplitter,
    QVBoxLayout, QWidget,
)

import blender_bridge as bb
import encode
import paths
import templates
import updater
from book_dialog import BookDialog
from page_curl import Timeline, layout_pages
from version import APP_NAME, APP_VERSION

RESOLUTIONS = {'1920 × 1080 (Full HD)': (1920, 1080), '2560 × 1440 (2K)': (2560, 1440),
               '3840 × 2160 (4K)': (3840, 2160)}
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class RenderWorker(QThread):
    """Runs Blender, then (optionally) FFmpeg. Emits plain progress for the UI."""
    progress = Signal(int, int, float)   # done, total, seconds per frame
    message = Signal(str)
    finished_ok = Signal(str)            # folder
    failed = Signal(str)

    def __init__(self, blender, job, encode_opts=None):
        super().__init__()
        self.blender, self.job, self.encode_opts = blender, job, encode_opts
        self.proc = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def run(self):
        out = Path(self.job['out_dir'])
        out.mkdir(parents=True, exist_ok=True)
        job_path = out / 'job.json'
        job_path.write_text(json.dumps(self.job, indent=2), encoding='utf-8')
        error, tail, started = None, [], time.time()
        try:
            self.proc = subprocess.Popen(bb.command(self.blender, job_path), stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                         errors='replace', creationflags=NO_WINDOW)
            for line in self.proc.stdout:
                kind, *rest = bb.parse_line(line)
                if kind == 'progress':
                    done, total = rest
                    self.progress.emit(done, total, (time.time() - started) / max(1, done))
                elif kind == 'error':
                    error = rest[0]
                elif kind == 'log' and line.strip():
                    tail = (tail + [line.rstrip()])[-40:]
                    if line.startswith(('INFO', 'WARNING')):
                        self.message.emit(line.strip())
            self.proc.wait()
        except OSError as exc:
            self.failed.emit(f'Could not start Blender: {exc}')
            return
        if self.cancelled:
            self.failed.emit('Cancelled. Frames already rendered are in:\n' + str(out))
            return
        if self.proc.returncode or error:
            self.failed.emit((error or 'Blender stopped unexpectedly.') + '\n\nLast Blender output:\n' + '\n'.join(tail))
            return
        if self.encode_opts:
            try:
                self._encode(out)
            except Exception as exc:  # frames stay on disk
                self.failed.emit(str(exc))
                return
        self.finished_ok.emit(str(out))

    def _encode(self, out):
        opts, fps = self.encode_opts, self.job['fps']
        made = []
        if opts['mov']:
            self.message.emit('Encoding ProRes 4444 MOV…')
            made.append(encode.encode_mov(out, fps))
        if opts['webm']:
            self.message.emit('Encoding transparent WebM…')
            made.append(encode.encode_webm(out, fps))
        if made and not opts['keep_png']:
            encode.delete_frames(out)


class UpdateCheck(QThread):
    found = Signal(dict)
    none = Signal(str)

    def run(self):
        try:
            info = updater.check()
        except Exception as exc:
            self.none.emit(f'Could not check for updates ({exc}).')
            return
        if info:
            self.found.emit(info)
        else:
            self.none.emit(f'You have the latest version ({APP_VERSION}).')


class UpdateDownload(QThread):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, info):
        super().__init__()
        self.info = info

    def run(self):
        try:
            path = updater.download(self.info, lambda d, t: self.progress.emit(d, t))
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.done.emit(str(path))


def checker_pixmap(pix):
    """Draw a frame over a checkerboard so transparency is visible (never exported)."""
    bg = QPixmap(pix.size())
    p = QPainter(bg)
    s = 16
    for y in range(0, pix.height(), s):
        for x in range(0, pix.width(), s):
            p.fillRect(x, y, s, s, QColor(70, 70, 76) if (x // s + y // s) % 2 else QColor(52, 52, 58))
    p.drawPixmap(0, 0, pix)
    p.end()
    return bg


class Studio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'{APP_NAME} {APP_VERSION}')
        icon = paths.resource_dir() / 'assets' / 'icon.png'
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.settings = QSettings('StrokeDot', APP_NAME)
        self.worker = None
        self.update_thread = None
        self.preview_frames, self.preview_index = [], 0
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self._next_preview_frame)
        self.blender = bb.find_blender(self.settings.value('blender'))
        self.books = []
        self._build()
        self._reload_books(self.settings.value('book', ''))
        self._load_settings()
        self._update_summary()
        self._update_blender_label()
        if self.settings.value('auto_update', 'true') == 'true':
            QTimer.singleShot(2500, lambda: self._check_updates(quiet=True))

    # ---------------------------------------------------------------- layout
    def _build(self):
        root = QSplitter()
        self.setCentralWidget(root)

        # Pages
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel('<b>Pages</b> (in reading order)'))
        self.pages = QListWidget()
        self.pages.setIconSize(QPixmap(64, 64).size())
        self.pages.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.pages.model().rowsMoved.connect(self._pages_changed)
        lv.addWidget(self.pages, 1)
        row = QHBoxLayout()
        for text, fn in (('Add images…', self._add_images), ('Add blank page', self._add_blank),
                         ('Remove', self._remove_page)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        lv.addLayout(row)
        row = QHBoxLayout()
        for text, step in (('Move up', -1), ('Move down', 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=step: self._move_page(s))
            row.addWidget(b)
        lv.addLayout(row)
        self.layout_hint = QLabel()
        self.layout_hint.setWordWrap(True)
        lv.addWidget(self.layout_hint)
        row = QHBoxLayout()
        b = QPushButton('Open project…')
        b.clicked.connect(self._open_project)
        row.addWidget(b)
        b = QPushButton('Save project…')
        b.clicked.connect(self._save_project)
        row.addWidget(b)
        lv.addLayout(row)
        root.addWidget(left)

        # Preview
        mid = QWidget()
        mv = QVBoxLayout(mid)
        self.preview = QLabel('Press "Preview still" to see your book.\nThe checkerboard means transparent.')
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(640, 360)
        self.preview.setStyleSheet('background:#26262b;color:#aaa;border-radius:6px')
        mv.addWidget(self.preview, 1)
        row = QHBoxLayout()
        self.still_btn = QPushButton('Preview still')
        self.still_btn.clicked.connect(self._preview_still)
        self.anim_btn = QPushButton('Preview animation (draft)')
        self.anim_btn.clicked.connect(self._preview_anim)
        row.addWidget(self.still_btn)
        row.addWidget(self.anim_btn)
        mv.addLayout(row)
        self.summary = QLabel()
        mv.addWidget(self.summary)
        self.progress = QProgressBar()
        mv.addWidget(self.progress)
        self.status = QLabel('Ready.')
        self.status.setWordWrap(True)
        mv.addWidget(self.status)
        row = QHBoxLayout()
        self.render_btn = QPushButton('Render video')
        self.render_btn.setStyleSheet('font-weight:bold;padding:8px 18px')
        self.render_btn.clicked.connect(self._render)
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        self.open_btn = QPushButton('Open output folder')
        self.open_btn.clicked.connect(lambda: self._open_output())
        row.addWidget(self.render_btn)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.open_btn)
        mv.addLayout(row)
        root.addWidget(mid)

        # Settings (scrollable, so it fits on smaller screens)
        right = QWidget()
        rv = QVBoxLayout(right)

        bookbox = QGroupBox('Book')
        f = QFormLayout(bookbox)
        self.book_combo = QComboBox()
        self.book_combo.currentIndexChanged.connect(self._update_summary)
        f.addRow('Template', self.book_combo)
        row = QHBoxLayout()
        for text, fn in (('Edit…', self._edit_book), ('Make a copy…', self._copy_book),
                         ('Open folder', self._open_books_folder)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        f.addRow(row)
        self.blend = self._combo(bb.BLEND)
        f.addRow('Page images', self.blend)
        self.camera = self._combo(bb.CAMERAS)
        f.addRow('Camera', self.camera)
        self.zoom = self._slider(60, 160, 100)
        f.addRow('Book size in frame', self.zoom)
        rv.addWidget(bookbox)

        timing = QGroupBox('Timing (seconds)')
        f = QFormLayout(timing)
        self.start_closed = QCheckBox('Start closed, then open the cover')
        self.start_closed.setChecked(True)
        self.start_closed.toggled.connect(self._update_summary)
        f.addRow(self.start_closed)
        self.open_s = self._spin(0.5, 6, 1.6)
        self.turn_s = self._spin(0.3, 6, 1.4)
        self.pause_s = self._spin(0, 10, 0.8)
        self.start_s = self._spin(0, 10, 0.8)
        self.end_s = self._spin(0, 10, 1.5)
        f.addRow('Cover opening', self.open_s)
        f.addRow('Each page turn', self.turn_s)
        f.addRow('Pause between', self.pause_s)
        f.addRow('Hold at start', self.start_s)
        f.addRow('Hold at end', self.end_s)
        self.curl = self._slider(0, 150, 90)
        f.addRow('Page curl', self.curl)
        rv.addWidget(timing)

        out = QGroupBox('Export')
        f = QFormLayout(out)
        self.resolution = self._combo(RESOLUTIONS)
        self.fps = QComboBox()
        self.fps.addItems(['24', '30', '60'])
        self.fps.setCurrentText('30')
        self.fps.currentTextChanged.connect(self._update_summary)
        self.quality = self._combo(bb.QUALITY)
        self.quality.setCurrentIndex(1)
        f.addRow('Resolution', self.resolution)
        f.addRow('Frame rate', self.fps)
        f.addRow('Quality', self.quality)
        self.mov = QCheckBox('MOV ProRes 4444 (best for Filmora)')
        self.mov.setChecked(True)
        self.webm = QCheckBox('WebM VP9 (small file)')
        self.keep_png = QCheckBox('Keep PNG frames')
        for w in (self.mov, self.webm, self.keep_png):
            f.addRow(w)
        row = QHBoxLayout()
        self.out_label = QLabel()
        self.out_label.setWordWrap(True)
        b = QPushButton('Change…')
        b.clicked.connect(self._choose_output)
        row.addWidget(self.out_label, 1)
        row.addWidget(b)
        f.addRow('Save to', row)
        rv.addWidget(out)

        eng = QGroupBox('3D engine and updates')
        ev = QVBoxLayout(eng)
        self.blender_label = QLabel()
        self.blender_label.setWordWrap(True)
        ev.addWidget(self.blender_label)
        row = QHBoxLayout()
        b = QPushButton('Find blender.exe…')
        b.clicked.connect(self._browse_blender)
        t = QPushButton('Test')
        t.clicked.connect(self._test_blender)
        row.addWidget(b)
        row.addWidget(t)
        ev.addLayout(row)
        row = QHBoxLayout()
        u = QPushButton('Check for updates')
        u.clicked.connect(lambda: self._check_updates(quiet=False))
        row.addWidget(u)
        self.auto_update = QCheckBox('Check at startup')
        self.auto_update.setChecked(self.settings.value('auto_update', 'true') == 'true')
        self.auto_update.toggled.connect(lambda on: self.settings.setValue('auto_update', 'true' if on else 'false'))
        row.addWidget(self.auto_update)
        ev.addLayout(row)
        ev.addWidget(QLabel(f'Version {APP_VERSION}'))
        rv.addWidget(eng)
        rv.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(right)
        scroll.setMinimumWidth(360)
        root.addWidget(scroll)
        root.setSizes([260, 760, 380])

        for w in (self.turn_s, self.pause_s, self.start_s, self.end_s, self.open_s):
            w.valueChanged.connect(self._update_summary)

    def _combo(self, mapping):
        c = QComboBox()
        c.addItems(list(mapping))
        return c

    def _slider(self, lo, hi, val):
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        return s

    def _spin(self, lo, hi, val):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(0.1)
        s.setDecimals(1)
        s.setValue(val)
        return s

    # ---------------------------------------------------------------- books
    def _reload_books(self, select_folder=''):
        self.books = templates.list_books()
        self.book_combo.blockSignals(True)
        self.book_combo.clear()
        index = 0
        for i, b in enumerate(self.books):
            self.book_combo.addItem(b['name'])
            if select_folder and b.get('folder') == select_folder:
                index = i
        self.book_combo.setCurrentIndex(index)
        self.book_combo.blockSignals(False)

    def _book(self):
        i = self.book_combo.currentIndex()
        return self.books[i] if 0 <= i < len(self.books) else self.books[0]

    def _edit_book(self):
        dlg = BookDialog(self._book(), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            saved = templates.save(dlg.result_book(), dlg.new_image)
            self._reload_books(saved['folder'])
            self.status.setText(f'Saved book "{saved["name"]}". Press "Preview still" to see it.')

    def _copy_book(self):
        name, ok = QInputDialog.getText(self, 'Make a copy', 'Name for the new book:',
                                        text=self._book()['name'] + ' copy')
        if ok and name.strip():
            copy = templates.duplicate(self._book(), name.strip())
            self._reload_books(copy['folder'])
            self._edit_book()

    def _open_books_folder(self):
        self._open_output(paths.books_dir())

    # ---------------------------------------------------------------- pages
    def _page_paths(self):
        return [self.pages.item(i).data(Qt.ItemDataRole.UserRole) or None for i in range(self.pages.count())]

    def _add_page_item(self, path):
        if path:
            item = QListWidgetItem(QIcon(QPixmap(path).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                                              Qt.TransformationMode.SmoothTransformation)), '')
        else:
            item = QListWidgetItem('')
        item.setData(Qt.ItemDataRole.UserRole, path or '')
        self.pages.addItem(item)

    def _add_images(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Choose page images', self.settings.value('img_dir', ''),
                                                'Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)')
        for path in files:
            self._add_page_item(path)
        if files:
            self.settings.setValue('img_dir', str(Path(files[0]).parent))
        self._pages_changed()

    def _add_blank(self):
        self._add_page_item(None)
        self._pages_changed()

    def _remove_page(self):
        for item in self.pages.selectedItems():
            self.pages.takeItem(self.pages.row(item))
        self._pages_changed()

    def _move_page(self, step):
        row = self.pages.currentRow()
        new = row + step
        if row < 0 or not 0 <= new < self.pages.count():
            return
        item = self.pages.takeItem(row)
        self.pages.insertItem(new, item)
        self.pages.setCurrentRow(new)
        self._pages_changed()

    def _pages_changed(self, *_):
        n = self.pages.count()
        for i in range(n):
            item = self.pages.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            name = Path(path).name if path else '(blank paper)'
            side = 'left' if i % 2 == 0 else 'right'
            item.setText(f'{i + 1}. {name}  —  {side}')
        turns = layout_pages(n)[0]
        self.layout_hint.setText(
            f'The book opens on pages 1 (left) and 2 (right). Each turn reveals the next two. '
            f'{n} page(s) → {turns} page turn(s). Drag to reorder.')
        self._update_summary()

    def _set_pages(self, pages):
        self.pages.clear()
        missing = 0
        for p in pages:
            if not p or Path(p).exists():
                self._add_page_item(p)
            else:
                missing += 1
        self._pages_changed()
        return missing

    # ------------------------------------------------------------- settings
    def _values(self):
        w, h = RESOLUTIONS[self.resolution.currentText()]
        return dict(width=w, height=h, fps=int(self.fps.currentText()),
                    start_hold=self.start_s.value(), turn_seconds=self.turn_s.value(),
                    pause=self.pause_s.value(), end_hold=self.end_s.value(),
                    start_closed=self.start_closed.isChecked(), open_seconds=self.open_s.value(),
                    curl=self.curl.value() / 100, camera=self.camera.currentText(),
                    zoom=self.zoom.value() / 100, quality=self.quality.currentText(),
                    blend=self.blend.currentText())

    def _state(self):
        v = self._values()
        v.update(resolution=self.resolution.currentText(), mov=self.mov.isChecked(), webm=self.webm.isChecked(),
                 keep_png=self.keep_png.isChecked(), book=self._book().get('folder') or '',
                 pages=self._page_paths())
        return v

    def _apply_state(self, v):
        combos = dict(camera=self.camera, quality=self.quality, blend=self.blend, resolution=self.resolution)
        for key, combo in combos.items():
            if v.get(key) and combo.findText(v[key]) >= 0:
                combo.setCurrentText(v[key])
        if v.get('fps'):
            self.fps.setCurrentText(str(v['fps']))
        for key, spin in (('start_hold', self.start_s), ('turn_seconds', self.turn_s), ('pause', self.pause_s),
                          ('end_hold', self.end_s), ('open_seconds', self.open_s)):
            if key in v:
                spin.setValue(float(v[key]))
        for key, s in (('curl', self.curl), ('zoom', self.zoom)):
            if key in v:
                s.setValue(round(float(v[key]) * 100))
        for key, box in (('mov', self.mov), ('webm', self.webm), ('keep_png', self.keep_png),
                         ('start_closed', self.start_closed)):
            if key in v:
                box.setChecked(bool(v[key]))
        if v.get('book'):
            self._reload_books(v['book'])
        return self._set_pages(v.get('pages', []))

    def _save_settings(self):
        self.settings.setValue('state', json.dumps(self._state()))
        self.settings.setValue('book', self._book().get('folder') or '')

    def _load_settings(self):
        self.output_dir = Path(self.settings.value('out_dir', str(Path.home() / 'Videos' / APP_NAME)))
        self.out_label.setText(str(self.output_dir))
        try:
            v = json.loads(self.settings.value('state', '{}'))
        except ValueError:
            v = {}
        self._apply_state(v)

    def _save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save project', self.settings.value('proj_dir', ''),
                                              'Handyman project (*.hmproj)')
        if path:
            Path(path).write_text(json.dumps(self._state(), indent=2), encoding='utf-8')
            self.settings.setValue('proj_dir', str(Path(path).parent))
            self.status.setText(f'Project saved: {path}')

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open project', self.settings.value('proj_dir', ''),
                                              'Handyman project (*.hmproj)')
        if not path:
            return
        try:
            missing = self._apply_state(json.loads(Path(path).read_text(encoding='utf-8')))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, APP_NAME, f'Could not open that project: {exc}')
            return
        self.status.setText(f'Opened {Path(path).name}' + (f' — {missing} image(s) not found and skipped.' if missing else ''))

    def closeEvent(self, event):
        self._save_settings()
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        super().closeEvent(event)

    def _timeline(self, v, turns=None):
        turns = turns or layout_pages(self.pages.count())[0]
        return Timeline(turns, v['fps'], v['start_hold'], v['turn_seconds'], v['pause'], v['end_hold'],
                        v['open_seconds'] if v['start_closed'] else 0.0)

    def _update_summary(self, *_):
        if not hasattr(self, 'summary'):
            return
        v = self._values()
        tl = self._timeline(v)
        self.summary.setText(f'Video length: {tl.frames / v["fps"]:.1f} s  ·  {tl.frames} frames  ·  {tl.turns} turn(s)')

    # --------------------------------------------------------------- blender
    def _update_blender_label(self):
        if self.blender:
            self.blender_label.setText(f'Blender: {self.blender}')
        else:
            self.blender_label.setText('<b>Blender not found.</b> Install it free from blender.org '
                                       '(the normal Windows installer), then restart this app, '
                                       'or click "Find blender.exe…".')

    def _browse_blender(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Find blender.exe', r'C:\Program Files\Blender Foundation',
                                              'Blender (blender.exe)')
        if path:
            self.blender = path
            self.settings.setValue('blender', path)
            self._update_blender_label()

    def _test_blender(self):
        if not self._need_blender():
            return
        ver = bb.blender_version(self.blender)
        if ver:
            QMessageBox.information(self, APP_NAME, f'Blender {ver} is working. Now try "Preview still".')
        else:
            QMessageBox.warning(self, APP_NAME, 'That Blender did not respond. Try reinstalling it from blender.org.')

    def _need_blender(self):
        if self.blender and Path(self.blender).exists():
            return True
        QMessageBox.warning(self, APP_NAME, 'Blender is needed for the 3D work.\n\n'
                            'Download the free Windows installer from https://www.blender.org/download/ , '
                            'install it, then restart this app.')
        return False

    # -------------------------------------------------------------- running
    def _busy(self, busy):
        for w in (self.render_btn, self.still_btn, self.anim_btn):
            w.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)

    def _start(self, job, on_done, encode_opts=None):
        if not self._need_blender():
            return
        self._save_settings()
        self.play_timer.stop()
        self.progress.setValue(0)
        self._busy(True)
        self.status.setText('Starting Blender… (the first frame is slower while materials compile)')
        self.worker = RenderWorker(self.blender, job, encode_opts)
        self.worker.progress.connect(self._on_progress)
        self.worker.message.connect(self.status.setText)
        self.worker.finished_ok.connect(on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_progress(self, done, total, per_frame):
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        left = per_frame * (total - done)
        self.status.setText(f'Rendering frame {done} of {total}  ·  {per_frame:.2f} s per frame  ·  '
                            f'about {int(left // 60)} min {int(left % 60)} s left')

    def _on_failed(self, msg):
        self._busy(False)
        self.status.setText('Stopped.')
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(msg.split('\n')[0])
        box.setDetailedText(msg)
        box.exec()

    def _cancel(self):
        if self.worker:
            self.worker.cancel()

    def _scratch(self, name):
        d = paths.cache_dir(name)
        shutil.rmtree(d, ignore_errors=True)
        return d

    def _job(self, v, out, **kw):
        return bb.make_job(v, self._book(), self._page_paths(), out, **kw)

    def _preview_still(self):
        v = self._values()
        tl = self._timeline(v)
        mid = tl.turn_start(0) + int(tl.turn * 0.5)
        job = self._job(v, self._scratch('still'), frames=[mid], width=960, height=540)
        self._start(job, self._show_still)

    def _show_still(self, folder):
        self._busy(False)
        self.status.setText('Preview ready: the first page mid-turn.')
        self.preview_frames = [str(Path(folder) / 'frame_000000.png')]
        self.preview_index = 0
        self._next_preview_frame()

    def _preview_anim(self):
        v = self._values()
        v.update(fps=15, start_hold=0.3, end_hold=0.5)
        turns = layout_pages(self.pages.count())[0]
        # Only the first two turns, to keep the draft quick.
        short = self._timeline(v, min(turns, 2))
        job = self._job(v, self._scratch('anim'), frames=list(range(short.frames)),
                        width=640, height=360, quality='draft')
        self._start(job, self._show_anim)

    def _show_anim(self, folder):
        self._busy(False)
        self.status.setText('Draft preview (15 fps, low quality). The final render is smoother and sharper.')
        self.preview_frames = sorted(str(p) for p in Path(folder).glob('frame_*.png'))
        self.preview_index = 0
        self.play_timer.start(1000 // 15)

    def _next_preview_frame(self):
        if not self.preview_frames:
            return
        pix = QPixmap(self.preview_frames[self.preview_index % len(self.preview_frames)])
        self.preview_index += 1
        if not pix.isNull():
            pix = pix.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            self.preview.setPixmap(checker_pixmap(pix))

    def _render(self):
        if self.pages.count() == 0:
            QMessageBox.information(self, APP_NAME, 'Add at least one page image first (or a blank page).')
            return
        if not (self.mov.isChecked() or self.webm.isChecked() or self.keep_png.isChecked()):
            self.keep_png.setChecked(True)
        if (self.mov.isChecked() or self.webm.isChecked()) and not encode.find_ffmpeg():
            QMessageBox.warning(self, APP_NAME, 'FFmpeg was not found, so only PNG frames will be made.\n'
                                'It is the same FFmpeg StrokeScribe uses; put its bin folder on PATH.')
            self.mov.setChecked(False)
            self.webm.setChecked(False)
            self.keep_png.setChecked(True)
        folder = self.output_dir / datetime.now().strftime('Render_%Y-%m-%d_%H-%M-%S')
        job = self._job(self._values(), folder)
        opts = dict(mov=self.mov.isChecked(), webm=self.webm.isChecked(), keep_png=self.keep_png.isChecked())
        self._start(job, self._render_done, opts)

    def _render_done(self, folder):
        self._busy(False)
        self.last_output = folder
        self.status.setText(f'Done! Saved in {folder}')
        self._open_output(folder)

    def _choose_output(self):
        d = QFileDialog.getExistingDirectory(self, 'Save videos to', str(self.output_dir))
        if d:
            self.output_dir = Path(d)
            self.settings.setValue('out_dir', d)
            self.out_label.setText(d)

    def _open_output(self, folder=None):
        target = Path(folder or getattr(self, 'last_output', None) or self.output_dir)
        target.mkdir(parents=True, exist_ok=True)
        if sys.platform == 'win32':
            subprocess.Popen(['explorer', str(target)])

    # -------------------------------------------------------------- updates
    def _check_updates(self, quiet):
        if self.update_thread and self.update_thread.isRunning():
            return
        self.update_thread = UpdateCheck()
        self.update_thread.found.connect(self._offer_update)
        if not quiet:
            self.update_thread.none.connect(lambda msg: QMessageBox.information(self, APP_NAME, msg))
        self.update_thread.start()

    def _offer_update(self, info):
        notes = info['notes'].strip()
        text = f'Version {info["version"]} is available (you have {APP_VERSION}).'
        if not paths.is_installed():
            QMessageBox.information(self, APP_NAME, text + '\n\nYou are running from the source folder; '
                                    'get the new installer from the GitHub releases page.')
            return
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(text + '\n\nInstall it now? The app will close and reopen by itself.')
        if notes:
            box.setDetailedText(notes)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, APP_NAME, 'Please wait for the current render to finish first.')
            return
        self.dl_dialog = QProgressDialog('Downloading update…', 'Cancel', 0, 100, self)
        self.dl_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.dl_dialog.setAutoClose(False)
        self.dl_thread = UpdateDownload(info)
        self.dl_thread.progress.connect(lambda d, t: self.dl_dialog.setValue(int(100 * d / t) if t else 0))
        self.dl_thread.done.connect(self._install_update)
        self.dl_thread.failed.connect(lambda msg: (self.dl_dialog.close(),
                                                   QMessageBox.warning(self, APP_NAME, f'Update failed: {msg}')))
        self.dl_thread.start()
        self.dl_dialog.show()

    def _install_update(self, path):
        if self.dl_dialog.wasCanceled():
            return
        self.dl_dialog.close()
        self._save_settings()
        updater.run_installer(path)
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle('Fusion')
    check = (paths.resource_dir() / 'assets' / 'check.svg').as_posix()
    app.setStyleSheet(
        'QCheckBox::indicator{width:15px;height:15px;border:1px solid #8a8a92;border-radius:3px;background:#2a2a30}'
        'QCheckBox::indicator:hover{border-color:#c0c0c8}'
        f'QCheckBox::indicator:checked{{background:#2f7de1;border-color:#2f7de1;image:url("{check}")}}')
    w = Studio()
    w.resize(1440, 860)
    w.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
