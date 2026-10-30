"""Handyman: 3D book page-turn overlays with transparent backgrounds.

Pick a book template and your page images, adjust the timing, press Render.
Blender does the 3D work in the background; you never need to open it.
"""
import json
import shutil
import subprocess
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QProgressDialog, QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
)

import blender_bridge as bb
import book_model
import camera_fit as cf
import encode
import paths
import templates
import updater
from book_dialog import BookDialog

# Check for Qt WebEngine WITHOUT importing it: importing it early reconfigures Qt's OpenGL
# setup and can leave the Live 3D view (a QOpenGLWidget) black.
try:
    import importlib.util as _ilu
    HAVE_WEBENGINE = _ilu.find_spec('PySide6.QtWebEngineWidgets') is not None
except Exception:
    HAVE_WEBENGINE = False
from framing_view import FramingView
try:
    from live_view import LiveView, GL_IMPORT_ERROR
except Exception as _exc:  # PySide6 without OpenGL widgets, or PyOpenGL missing
    LiveView, GL_IMPORT_ERROR = None, str(_exc)
from page_curl import Timeline, layout_pages
from timeline_panel import TimelinePanel
from clips import ClipTimeline, clip_to_dict
from version import APP_NAME, APP_VERSION

RESOLUTIONS = {'1920 × 1080 (Full HD)': (1920, 1080), '2560 × 1440 (2K)': (2560, 1440),
               '3840 × 2160 (4K)': (3840, 2160)}
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class GltfWorker(QThread):
    """Exports the current book to .glb for the interactive viewport."""
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, blender, job):
        super().__init__()
        self.blender, self.job = blender, job
        self.proc = None

    def run(self):
        out = Path(self.job['out_dir'])
        out.mkdir(parents=True, exist_ok=True)
        job_path = out / 'job.json'
        job_path.write_text(json.dumps(self.job, indent=2), encoding='utf-8')
        tail = []
        try:
            self.proc = subprocess.Popen(bb.command_gltf(self.blender, job_path),
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, encoding='utf-8', errors='replace',
                                         creationflags=NO_WINDOW)
            for line in self.proc.stdout:
                if line.strip():
                    tail = (tail + [line.rstrip()])[-30:]
            self.proc.wait()
        except OSError as exc:
            self.failed.emit(f'Could not start Blender: {exc}')
            return
        if self.proc.returncode:
            self.failed.emit('glTF export failed.\n\n' + '\n'.join(tail))
            return
        self.finished_ok.emit(self.job['glb_path'])


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

    def __init__(self, manual=False):
        super().__init__()
        self.manual = manual

    def run(self):
        try:
            result = updater.check(manual=self.manual)
        except Exception as exc:
            self.none.emit(f'Could not check for updates ({exc}).')
            return
        info = result.get('info')
        if info:
            self.found.emit(info)
        else:
            self.none.emit(result.get('message') or f'You have the latest version ({APP_VERSION}).')


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
        self.recorded_clips = []
        self.edited_clips = None
        self._build()
        self._reload_books(self.settings.value('book', ''))
        self._load_settings()
        self._init_timeline()
        self._update_summary()
        self._update_blender_label()
        self._camera_changed()
        self._show_view(0)
        self._check_recovery()
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
        for text, fn in (('Add images…', self._add_images), ('Add text page…', self._add_text),
                         ('Add blank page', self._add_blank), ('Remove', self._remove_page)):
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
        pgroup = QGroupBox('Page image framing (the selected page)')
        pf = QFormLayout(pgroup)
        row = QHBoxLayout()
        self.p_fit = QComboBox()
        self.p_fit.addItems(['Fit', 'Fill', 'Stretch'])
        row.addWidget(self.p_fit)
        self.p_scale = QDoubleSpinBox()
        self.p_scale.setRange(0.25, 4.0)
        self.p_scale.setSingleStep(0.1)
        self.p_scale.setValue(1.0)
        row.addWidget(self.p_scale)
        pf.addRow('Fit / scale', row)
        row = QHBoxLayout()
        self.p_x = QDoubleSpinBox()
        self.p_x.setRange(-1.0, 1.0)
        self.p_x.setSingleStep(0.05)
        self.p_y = QDoubleSpinBox()
        self.p_y.setRange(-1.0, 1.0)
        self.p_y.setSingleStep(0.05)
        row.addWidget(QLabel('X'))
        row.addWidget(self.p_x)
        row.addWidget(QLabel('Y'))
        row.addWidget(self.p_y)
        pf.addRow('Position', row)
        lv.addWidget(pgroup)
        self._fit_loading = False
        self.pages.currentRowChanged.connect(self._load_page_fit)
        self.p_fit.currentTextChanged.connect(self._apply_page_fit)
        self.p_scale.valueChanged.connect(self._apply_page_fit)
        self.p_x.valueChanged.connect(self._apply_page_fit)
        self.p_y.valueChanged.connect(self._apply_page_fit)
        row = QHBoxLayout()
        b = QPushButton('Open project…')
        b.clicked.connect(self._open_project)
        row.addWidget(b)
        b = QPushButton('Save project…')
        b.clicked.connect(self._save_project)
        row.addWidget(b)
        lv.addLayout(row)
        # Explicit, reliable way to start the calibrated leather book. It never opens or
        # overwrites a saved project - it only reconfigures the current session.
        b = QPushButton('New Leather Book')
        b.setToolTip('Start a fresh project with the calibrated leather book: '
                     '20 sheets, 1.424 page aspect, your validated cover/pastedown/spine artwork.')
        b.clicked.connect(self._new_leather_book)
        lv.addWidget(b)
        self.timeline_panel = TimelinePanel()
        self.timeline_panel.changed.connect(self._timeline_changed)
        lv.addWidget(self.timeline_panel, 1)
        root.addWidget(left)

        # Preview
        mid = QWidget()
        mv = QVBoxLayout(mid)
        self.preview = QLabel('Press "Preview still" to see your book.\nThe checkerboard means transparent.')
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(640, 360)
        self.preview.setStyleSheet('background:#26262b;color:#aaa;border-radius:6px')
        # Two views in the big area: the live camera outline (drag it) and the rendered preview.
        self.views = QStackedWidget()
        self.live = LiveView() if (LiveView is not None and GL_IMPORT_ERROR is None) else None
        self.framing = self.live or FramingView()
        self.views.addWidget(self.framing)
        self.views.addWidget(self.preview)
        # Created on first use: loading Qt WebEngine at startup disturbs the OpenGL view.
        self.gltf = None
        if self.gltf is not None:
            self.views.addWidget(self.gltf)
        row = QHBoxLayout()
        self.view_shot = QPushButton('Live 3D view (drag to move the camera)')
        self.view_render = QPushButton('Rendered preview')
        for b, i in ((self.view_shot, 0), (self.view_render, 1)):
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self._show_view(i))
            row.addWidget(b)
        # Hidden for now: Qt WebEngine repeatedly crashed the app when shown next to the
        # OpenGL viewport, even with a shared GL context. The export code stays for a future
        # standalone window, but the button is not offered until that is proven stable.
        self.view_gltf = QPushButton('glTF Viewport (Beta)')
        self.view_gltf.setCheckable(True)
        self.view_gltf.setVisible(False)
        self.view_gltf.clicked.connect(self._show_gltf)
        mv.addLayout(row)
        mv.addWidget(self.views, 1)
        # Playback for the live view: no rendering needed.
        self.playbar = QWidget()
        pb = QHBoxLayout(self.playbar)
        pb.setContentsMargins(0, 0, 0, 0)
        self.play_btn = QPushButton('▶ Play')
        self.play_btn.setFixedWidth(90)
        self.play_btn.clicked.connect(self._toggle_play)
        self.scrub = QSlider(Qt.Orientation.Horizontal)
        self.scrub.setRange(0, 1)
        self.scrub.valueChanged.connect(self._scrubbed)
        self.time_label = QLabel('0.0 s')
        self.time_label.setFixedWidth(90)
        self.speed = QComboBox()
        self.speed.addItems(['0.25×', '0.5×', '1×', '1.5×', '2×'])
        self.speed.setCurrentText('1×')
        self.speed.currentTextChanged.connect(self._speed_changed)
        self.loop = QCheckBox('Loop')
        self.loop.setChecked(True)
        self.loop.toggled.connect(lambda on: setattr(self.live, 'loop', on) if self.live else None)
        self.drag_pages = QCheckBox('Drag pages')
        self.drag_pages.setToolTip('Left-drag a page in the live view to turn it')
        self.drag_pages.toggled.connect(lambda on: setattr(self.live, 'drag_pages', on) if self.live else None)
        self.record = QCheckBox('Record')
        self.record.setToolTip('While on, each finished page drag is added to the timeline')
        for wdg in (self.play_btn, self.scrub, self.time_label, QLabel('Speed'), self.speed, self.loop,
                    self.drag_pages, self.record):
            pb.addWidget(wdg, 1 if wdg is self.scrub else 0)
        mv.addWidget(self.playbar)
        self.playbar.setVisible(self.live is not None)
        if self.live is not None:
            self.live.frameChanged.connect(self._live_frame)
            self.live.pageTurned.connect(self._on_page_turned)
            self.live.failed.connect(self._live_failed)
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self._refresh_live)
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
        self.book_combo.currentIndexChanged.connect(self._camera_changed)
        f.addRow('Template', self.book_combo)
        self.page_count = QSpinBox()
        self.page_count.setRange(2, 2000)
        self.page_count.setValue(20)   # calibrated journal default; template overrides on load
        self.page_count.valueChanged.connect(self._update_summary)
        f.addRow('Page count (sheets)', self.page_count)
        row = QHBoxLayout()
        for text, fn in (('Edit…', self._edit_book), ('Make a copy…', self._copy_book),
                         ('Open folder', self._open_books_folder)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        f.addRow(row)
        self.blend = self._combo(bb.BLEND)
        self.blend.currentTextChanged.connect(self._schedule_live)
        f.addRow('Page images', self.blend)
        rv.addWidget(bookbox)

        cambox = QGroupBox('Camera')
        f = QFormLayout(cambox)
        self.framing.orbit.connect(self._orbit)
        self.framing.pan.connect(self._pan)
        self.framing.zoomed.connect(lambda n: self.zoom.setValue(round(self.zoom.value() * 1.08 ** n)))
        self.framing.reset.connect(lambda: self._apply_preset(self.shot.currentText()))
        f.addRow(QLabel('<small>Or drag the big picture: left = look around, right = move, wheel = zoom, '
                        'double-click = reset</small>'))
        self.shot = self._combo(cf.PRESETS)
        self.shot.currentTextChanged.connect(self._apply_preset)
        f.addRow('Start from', self.shot)
        self.tilt = self._slider(-89, 89, 50)
        self.turn = self._slider(-180, 180, 0)
        self.roll = self._slider(-180, 180, -3)
        self.lens = self._slider(18, 100, 35)
        self.zoom = self._slider(50, 250, 100)
        self.shift_x = self._slider(-60, 60, 0)
        self.shift_y = self._slider(-60, 60, 0)
        for label, sl in (('Tilt (below ↔ above)', self.tilt), ('Turn around', self.turn), ('Tilt picture', self.roll),
                          ('Perspective (lens)', self.lens), ('Book size', self.zoom),
                          ('Left / right', self.shift_x), ('Down / up', self.shift_y)):
            sl.valueChanged.connect(self._camera_changed)
            f.addRow(label, sl)
        self.move = self._combo(cf.MOVES)
        self.move.currentTextChanged.connect(self._camera_changed)
        f.addRow('Camera move', self.move)
        b = QPushButton('Reset to the chosen start')
        b.clicked.connect(lambda: self._apply_preset(self.shot.currentText()))
        f.addRow(b)
        rv.addWidget(cambox)

        xform = QGroupBox('3D transform (the whole book)')
        f = QFormLayout(xform)

        def num(lo, hi, val, step):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setSingleStep(step)
            s.setDecimals(2)
            s.setValue(val)
            s.valueChanged.connect(self._schedule_live)
            return s

        row = QHBoxLayout()
        self.pos_x, self.pos_y, self.pos_z = num(-3, 3, 0, 0.1), num(-3, 3, 0, 0.1), num(-3, 3, 0, 0.1)
        for w in (self.pos_x, self.pos_y, self.pos_z):
            row.addWidget(w)
        f.addRow('Position X / Y / Z', row)

        row = QHBoxLayout()
        self.rot_x, self.rot_y, self.rot_z = num(-180, 180, 0, 5), num(-180, 180, 0, 5), num(-180, 180, 0, 5)
        for w in (self.rot_x, self.rot_y, self.rot_z):
            row.addWidget(w)
        f.addRow('Rotation X / Y / Z (°)', row)

        row = QHBoxLayout()
        self.scl_x, self.scl_y, self.scl_z = num(0.1, 5, 1, 0.1), num(0.1, 5, 1, 0.1), num(0.1, 5, 1, 0.1)
        for w in (self.scl_x, self.scl_y, self.scl_z):
            row.addWidget(w)
        f.addRow('Scale X / Y / Z', row)

        b = QPushButton('Reset transform')
        b.clicked.connect(self._reset_transform)
        f.addRow(b)
        rv.addWidget(xform)

        timing = QGroupBox('Timing (seconds)')
        f = QFormLayout(timing)
        self.start_closed = QCheckBox('Start closed, then open the cover')
        self.start_closed.setChecked(True)
        self.start_closed.toggled.connect(self._update_summary)
        f.addRow(self.start_closed)
        self.open_at = self._combo(book_model.OPEN_AT)
        self.open_at.currentTextChanged.connect(self._update_summary)
        f.addRow('Book opens at', self.open_at)
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
        self.curl.valueChanged.connect(self._schedule_live)
        f.addRow('Page curl', self.curl)
        self.smooth = self._slider(0, 100, 100)
        self.smooth.valueChanged.connect(self._schedule_live)
        f.addRow('Smoothness (0 = linear, 100 = gentle)', self.smooth)
        rv.addWidget(timing)

        out = QGroupBox('Export')
        f = QFormLayout(out)
        self.resolution = self._combo(RESOLUTIONS)
        self.resolution.currentTextChanged.connect(self._camera_changed)
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
        # new projects follow the selected template's own sheet count
        try:
            self.page_count.setValue(int(self.books[index].get('page_count') or 20))
        except Exception:
            pass

    def _book(self):
        i = self.book_combo.currentIndex()
        return self.books[i] if 0 <= i < len(self.books) else self.books[0]

    def _edit_book(self):
        dlg = BookDialog(self._book(), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            saved = templates.save(dlg.result_book(), dlg.new_image, dlg.art_images)
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
    TEXT_ROLE = Qt.ItemDataRole.UserRole + 1
    FIT_ROLE = Qt.ItemDataRole.UserRole + 2

    def _page_content(self):
        """Content sides in reading order: None (blank), or a {'kind': 'image'|'text', ...} dict."""
        out = []
        for i in range(self.pages.count()):
            item = self.pages.item(i)
            path = item.data(Qt.ItemDataRole.UserRole) or None
            text = item.data(self.TEXT_ROLE) or None
            if text:
                out.append({'kind': 'text', 'text': text})
            elif path:
                out.append({'kind': 'image', 'image': path})
            else:
                out.append(None)
        return out

    def _content_images(self):
        """Rasterise text sides to PNGs and return plain image paths for the renderers."""
        from page_text import sides_to_images
        return sides_to_images(self._page_content(), paths.cache_dir('pages'),
                               float(self._book().get('page_aspect', 1.4)))

    def _page_fits(self):
        """Per-side artwork framing: a dict per page side, or None for the default fit."""
        return [self.pages.item(i).data(self.FIT_ROLE) or None for i in range(self.pages.count())]

    def _load_page_fit(self, row):
        if row is None or row < 0 or row >= self.pages.count():
            return
        f = self.pages.item(row).data(self.FIT_ROLE) or {}
        self._fit_loading = True
        self.p_fit.setCurrentText({'fit': 'Fit', 'fill': 'Fill', 'stretch': 'Stretch'}.get(f.get('mode', 'fit'), 'Fit'))
        self.p_scale.setValue(float(f.get('scale', 1.0)))
        self.p_x.setValue(float(f.get('x', 0.0)))
        self.p_y.setValue(float(f.get('y', 0.0)))
        self._fit_loading = False

    def _apply_page_fit(self, *_):
        if getattr(self, '_fit_loading', False):
            return
        row = self.pages.currentRow()
        if row < 0:
            return
        self.pages.item(row).setData(self.FIT_ROLE, {
            'mode': {'Fit': 'fit', 'Fill': 'fill', 'Stretch': 'stretch'}[self.p_fit.currentText()],
            'scale': round(self.p_scale.value(), 3),
            'x': round(self.p_x.value(), 3),
            'y': round(self.p_y.value(), 3)})
        self._refresh_live()

    def _page_paths(self):
        return [self.pages.item(i).data(Qt.ItemDataRole.UserRole) or None for i in range(self.pages.count())]

    def _add_page_item(self, path, text=''):
        if path:
            item = QListWidgetItem(QIcon(QPixmap(path).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                                              Qt.TransformationMode.SmoothTransformation)), '')
        else:
            item = QListWidgetItem('')
        item.setData(Qt.ItemDataRole.UserRole, path or '')
        item.setData(self.TEXT_ROLE, text or '')
        item.setData(self.FIT_ROLE, {'mode': 'fit', 'scale': 1.0, 'x': 0.0, 'y': 0.0})
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

    def _add_text(self):
        text, ok = QInputDialog.getMultiLineText(self, 'Add text page', 'Type the text for this page:')
        if ok and text.strip():
            self._add_page_item(None, text.strip())
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
            text = item.data(self.TEXT_ROLE)
            if text:
                preview = ' '.join(text.split())
                name = f'“{preview[:36]}{"…" if len(preview) > 36 else ""}”'
            elif path:
                name = Path(path).name
            else:
                name = '(blank paper)'
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
            if p is None:
                self._add_page_item(None)
            elif isinstance(p, dict):
                self._add_page_item(p.get('image'), p.get('text', ''))
            elif not p or Path(p).exists():
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
                    open_at=book_model.OPEN_AT[self.open_at.currentText()], open_at_label=self.open_at.currentText(),
                    curl=self.curl.value() / 100, cam=self._cam(), quality=self.quality.currentText(),
                    blend=self.blend.currentText(), page_count=self.page_count.value(),
                    smoothness=self.smooth.value() / 100, recorded_clips=self.recorded_clips,
                    clip_list=self.edited_clips, transform=self._transform(),
                    page_fits=self._page_fits())

    def _state(self):
        v = self._values()
        v.update(resolution=self.resolution.currentText(), mov=self.mov.isChecked(), webm=self.webm.isChecked(),
                 keep_png=self.keep_png.isChecked(), book=self._book().get('folder') or '',
                 pages=self._page_content())
        return v

    def _apply_state(self, v):
        combos = dict(quality=self.quality, blend=self.blend, resolution=self.resolution, open_at_label=self.open_at)
        for key, combo in combos.items():
            if v.get(key) and combo.findText(v[key]) >= 0:
                combo.setCurrentText(v[key])
        if v.get('fps'):
            self.fps.setCurrentText(str(v['fps']))
        for key, spin in (('start_hold', self.start_s), ('turn_seconds', self.turn_s), ('pause', self.pause_s),
                          ('end_hold', self.end_s), ('open_seconds', self.open_s)):
            if key in v:
                spin.setValue(float(v[key]))
        if 'curl' in v:
            self.curl.setValue(round(float(v['curl']) * 100))
        if 'page_count' in v:
            self.page_count.setValue(int(v['page_count']))
        if isinstance(v.get('cam'), dict):
            self._set_cam(v['cam'])
        self._set_transform(v.get('transform'))
        for key, box in (('mov', self.mov), ('webm', self.webm), ('keep_png', self.keep_png),
                         ('start_closed', self.start_closed)):
            if key in v:
                box.setChecked(bool(v[key]))
        if v.get('book'):
            self._reload_books(v['book'])
        return self._set_pages(v.get('pages', []))

    # --------------------------------------------------------------- camera
    def _cam(self):
        return dict(tilt=float(self.tilt.value()), turn=float(self.turn.value()), roll=float(self.roll.value()),
                    lens=float(self.lens.value()), zoom=self.zoom.value() / 100,
                    shift_x=self.shift_x.value() / 100, shift_y=self.shift_y.value() / 100,
                    move=cf.MOVES[self.move.currentText()])

    def _set_cam(self, c):
        sliders = dict(tilt=self.tilt, turn=self.turn, roll=self.roll, lens=self.lens)
        for key, sl in sliders.items():
            if key in c:
                sl.blockSignals(True)
                sl.setValue(round(float(c[key])))
                sl.blockSignals(False)
        for key, sl in (('zoom', self.zoom), ('shift_x', self.shift_x), ('shift_y', self.shift_y)):
            if key in c:
                sl.blockSignals(True)
                sl.setValue(round(float(c[key]) * 100))
                sl.blockSignals(False)
        for label, value in cf.MOVES.items():
            if value == c.get('move'):
                self.move.setCurrentText(label)
        self._camera_changed()

    def _transform(self):
        return {'pos': [self.pos_x.value(), self.pos_y.value(), self.pos_z.value()],
                'rot': [self.rot_x.value(), self.rot_y.value(), self.rot_z.value()],
                'scale': [self.scl_x.value(), self.scl_y.value(), self.scl_z.value()]}

    def _reset_transform(self):
        for w in (self.pos_x, self.pos_y, self.pos_z):
            w.setValue(0)
        for w in (self.rot_x, self.rot_y, self.rot_z):
            w.setValue(0)
        for w in (self.scl_x, self.scl_y, self.scl_z):
            w.setValue(1)

    def _set_transform(self, t):
        if not isinstance(t, dict):
            return
        for key, boxes in (('pos', (self.pos_x, self.pos_y, self.pos_z)),
                           ('rot', (self.rot_x, self.rot_y, self.rot_z)),
                           ('scale', (self.scl_x, self.scl_y, self.scl_z))):
            for w, v in zip(boxes, t.get(key) or []):
                w.setValue(float(v))

    def _orbit(self, dx, dy):
        self.turn.setValue(round(self.turn.value() - dx * 0.35))
        self.tilt.setValue(round(self.tilt.value() + dy * 0.35))

    def _pan(self, dx, dy):
        k = 100 / max(1, self.framing.width()) / (self.zoom.value() / 100)
        self.shift_x.setValue(round(self.shift_x.value() - dx * k))
        self.shift_y.setValue(round(self.shift_y.value() + dy * k))

    def _apply_preset(self, name):
        if name in cf.PRESETS:
            self._set_cam(dict(cf.PRESETS[name], zoom=1.0, shift_x=0.0, shift_y=0.0))

    def _camera_changed(self, *_):
        if not hasattr(self, 'framing') or not hasattr(self, 'resolution'):
            return
        w, h = RESOLUTIONS[self.resolution.currentText()]
        aspect = float(self._book().get('page_aspect', 1.4)) if self.books else 1.4
        self.framing.set_view(self._cam(), aspect, w / h)
        self._schedule_live()
        if self.views.currentIndex() != 0:
            self.play_timer.stop()
            self._show_view(0)

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

    def _new_leather_book(self):
        """Configure this session for the calibrated leather book.

        Selects the Development Preview template, sets its own sheet count and aspect,
        and clears page artwork so the new project starts clean. Saved projects and the
        user's own templates are untouched - nothing is written to disk here.
        """
        def find():
            for i, b in enumerate(self.books):
                if Path(b.get('folder') or '').name == 'leather-book':
                    return i
            for i, b in enumerate(self.books):
                if 'Development Preview' in (b.get('name') or ''):
                    return i
            return None

        index = find()
        if index is None:
            templates.ensure_starter_books()
            self._reload_books()
            index = find()
        if index is None:
            QMessageBox.warning(
                self, APP_NAME,
                'The "Leather Book - Development Preview" template is not installed.\n'
                'Reinstall Handyman, or check your books folder.')
            return

        # Never discard unsaved work silently.
        if self.pages.count():
            answer = QMessageBox.question(
                self, APP_NAME,
                'Start a new leather book?\n\n'
                'This clears the current page list and any recorded or edited timeline '
                'clips in this session.\n'
                'Saved projects and your own templates are not touched.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.book_combo.setCurrentIndex(index)
        book = self.books[index]
        self.page_count.setValue(int(book.get('page_count') or 20))
        self.pages.clear()
        # a fresh project starts with an empty timeline, not the previous one's clips
        self.recorded_clips = []
        self.edited_clips = None
        # TimelinePanel.set_clips is the supported API; the editor is private to it.
        self.timeline_panel.set_clips([])
        # Refresh everything that depends on the page list and the book choice.
        self._update_summary()
        self._refresh_live()
        self.status.setText(
            f'New leather book ready - {self.page_count.value()} sheets, '
            '0 pages. Page art and timeline cleared. Press "Preview still" to see it.')

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
        self._schedule_live()

    # ------------------------------------------------------------ live view
    def _schedule_live(self, *_):
        if getattr(self, 'live', None) is not None and hasattr(self, '_live_timer'):
            self._live_timer.start(80)

    def _refresh_live(self):
        if self.live is None or not self.books:
            return
        try:
            self.live.set_content(self._book(), self._content_images(), self._values())
        except Exception as exc:
            self.status.setText(f'Live view could not update: {exc}')

    def _on_page_turned(self, start, duration, smoothness):
        """Record mode: a finished drag becomes a turn clip on the timeline."""
        if not self.record.isChecked():
            return
        self.recorded_clips.append({'start': int(start), 'duration': int(duration),
                                    'smoothness': float(smoothness)})
        self._refresh_live()
        self.status.setText(f'Recorded a page turn ({len(self.recorded_clips)} clip(s)).')

    # ----------------------------------------------------------- timeline
    def _init_timeline(self):
        """Fill the timeline editor from the current settings (the editable source of truth)."""
        if not self.books:
            return
        v = self._values()
        turns = layout_pages(self.pages.count())[0]
        open_sec = v['open_seconds'] if v['start_closed'] else 0.0
        tl = ClipTimeline(turns, v['fps'], v['start_hold'], v['turn_seconds'], v['pause'],
                          v['end_hold'], open_sec, smoothness=v['smoothness'])
        self.timeline_panel.base_frames = max(2, round(v['turn_seconds'] * v['fps']))
        self.edited_clips = [clip_to_dict(c) for c in tl.clips]
        self.timeline_panel.set_clips(tl.clips)

    def _timeline_changed(self):
        self.edited_clips = [clip_to_dict(c) for c in self.timeline_panel.editor.clips()]
        self._refresh_live()

    def _toggle_play(self):
        if self.gltf is not None and self.views.currentIndex() == 2:
            self._gltf_playing = not getattr(self, '_gltf_playing', False)
            self.gltf.play() if self._gltf_playing else self.gltf.pause()
            self.play_btn.setText('❚❚ Pause' if self._gltf_playing else '▶ Play')
            return
        if self.live is None:
            return
        self._show_view(0)
        self.live.play(not self.live.playing)
        self.play_btn.setText('❚❚ Pause' if self.live.playing else '▶ Play')

    def _scrubbed(self, value):
        if self.gltf is not None and self.views.currentIndex() == 2:
            fps = max(1, int(self._values()['fps']))
            self.gltf.set_time(value / fps)
            return
        if self.live is not None and int(self.live.frame) != value:
            self.live.seek(value)

    def _speed_changed(self, text):
        if self.live is not None:
            self.live.speed = float(text.rstrip('×'))

    def _live_frame(self, frame, total):
        self.scrub.blockSignals(True)
        self.scrub.setRange(0, max(0, total - 1))
        self.scrub.setValue(frame)
        self.scrub.blockSignals(False)
        fps = self.live.timeline.fps
        self.time_label.setText(f'{frame / fps:4.1f} / {(total - 1) / fps:.1f} s')
        if not self.live.playing:
            self.play_btn.setText('▶ Play')

    def _live_failed(self, reason):
        """No usable OpenGL on this PC: fall back to the outline view."""
        if self.live is None:
            return
        old = self.live
        self.live = None
        self.framing = FramingView()
        self.views.insertWidget(0, self.framing)
        self.views.removeWidget(old)
        old.deleteLater()
        self.framing.orbit.connect(self._orbit)
        self.framing.pan.connect(self._pan)
        self.framing.zoomed.connect(lambda n: self.zoom.setValue(round(self.zoom.value() * 1.08 ** n)))
        self.framing.reset.connect(lambda: self._apply_preset(self.shot.currentText()))
        self.playbar.setVisible(False)
        self._show_view(0)
        self._camera_changed()
        self.status.setText(f'The live 3D view is not available on this PC ({reason[:120]}); showing the outline instead.')

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
        return bb.make_job(v, self._book(), self._content_images(), out, **kw)

    def _preview_still(self):
        v = self._values()
        tl = self._timeline(v)
        # Show the book open at its first spread rather than part-way through a page turn,
        # which is what makes the cover, pastedown and page artwork all readable at once.
        first_spread = int(getattr(tl, 'first_turn', 0))
        mid = min(max(first_spread, 0), max(tl.frames - 1, 0))
        job = self._job(v, self._scratch('still'), frames=[mid], width=960, height=540)
        self._start(job, self._show_still)

    def _show_view(self, i):
        if self.gltf is not None and i != 2:
            try:
                self.gltf.pause()
            except Exception:
                pass
        self.views.setCurrentIndex(i)
        self.view_shot.setChecked(i == 0)
        self.view_render.setChecked(i == 1)
        self.view_gltf.setChecked(bool(self.gltf) and i == 2)

    def _show_gltf(self):
        """Export the current book to .glb, then show it in the beta viewport."""
        if self.gltf is None:
            if not HAVE_WEBENGINE:
                self.status.setText('The glTF viewport needs Qt WebEngine, which is not installed.')
                return
            try:
                from gltf_view import GltfView
                self.gltf = GltfView()
                self.views.addWidget(self.gltf)
            except Exception as exc:
                self.status.setText(f'The glTF viewport is unavailable ({exc}).')
                return
        blender = bb.find_blender(self.settings.value('blender'))
        if not blender:
            self.status.setText('Blender was not found — the glTF viewport needs it to export.')
            return
        job = self._job(self._values(), self._scratch('gltf'), quality='draft')
        job['glb_path'] = str(paths.cache_dir('gltf') / 'book.glb')
        self._gltf_worker = GltfWorker(blender, job)
        self._gltf_worker.finished_ok.connect(self._gltf_ready)
        self._gltf_worker.failed.connect(lambda m: self.status.setText(m))
        self._gltf_worker.start()
        self.status.setText('Exporting the glTF preview…')

    def _gltf_ready(self, glb):
        try:
            self.gltf.load_book(glb)
            self._show_view(2)
            self.status.setText('glTF viewport (beta) — orbit, zoom and scrub. The OpenGL view is still available.')
        except Exception as exc:
            self.status.setText(f'glTF viewport failed ({exc}); the OpenGL view is still available.')
            self._show_view(0)

    def _show_still(self, folder):
        self._busy(False)
        self.status.setText('Preview ready: the book at its first spread (Blender render).')
        self.preview_frames = [str(Path(folder) / 'frame_000000.png')]
        self.preview_index = 0
        self._show_view(1)
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
        self._show_view(1)
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
        self.update_thread = UpdateCheck(manual=not quiet)
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
        self._pending_version = info['version']
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
        self._write_update_marker(self._pending_version)
        updater.run_installer(path)
        QApplication.quit()

    # -------------------------------------------------- update recovery
    def _marker_path(self):
        return paths.user_dir() / 'update.json'

    def _write_update_marker(self, to_version):
        self._marker_path().write_text(json.dumps({'from': APP_VERSION, 'to': to_version}),
                                       encoding='utf-8')

    def _check_recovery(self):
        """On startup, detect a half-finished update and offer to recover."""
        marker = self._marker_path()
        if not marker.exists():
            return
        try:
            info = json.loads(marker.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            marker.unlink(missing_ok=True)
            return
        if info.get('to') == APP_VERSION:
            marker.unlink(missing_ok=True)          # the update finished successfully
            return
        QTimer.singleShot(1500, lambda: self._offer_recovery(info))

    def _offer_recovery(self, info):
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(f'The update to version {info.get("to", "?")} did not finish.\n'
                    f'You are still on version {APP_VERSION}.')
        box.setInformativeText('You can try the update again, or keep this version.')
        retry = box.addButton('Try again', QMessageBox.ButtonRole.AcceptRole)
        keep = box.addButton('Keep this version', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is retry:
            self._check_updates(quiet=False)
        else:
            self._marker_path().unlink(missing_ok=True)


def main():
    # WebEngine and the OpenGL viewport can only coexist when they share GL contexts,
    # and this attribute must be set before the QApplication exists.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    # Software rendering keeps Chromium's GPU process from fighting the OpenGL viewport.
    os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
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



