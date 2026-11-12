"""MotionCraft: 3D book page-turn overlays with transparent backgrounds.

Pick a book template and your page images, adjust the timing, press Render.
Blender does the 3D work in the background; you never need to open it.
"""
import json
import shutil
import subprocess
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu,
    QGridLayout, QMessageBox, QProgressBar, QProgressDialog, QPushButton, QScrollArea, QSlider, QSpinBox,
    QSplitter, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

import blender_bridge as bb
import book_model
import camera_fit as cf
import encode
import paths
import templates
import updater
from book_dialog import BookDialog
from journal_dialog import JournalDialog, check_size, required_size
from image_fit import ImageFitDialog, auto_adjust

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
from clips import Clip, ClipTimeline, clip_from_dict, clip_to_dict
from version import APP_NAME, APP_VERSION, OLD_NAME

APP_STYLE = """
QGroupBox { font-weight: 600; font-size: 13px; border: 1px solid #3a3a42; border-radius: 8px;
            margin-top: 14px; padding: 10px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #e8c58a; }
QPushButton { padding: 6px 10px; border-radius: 6px; background: #34343c; border: 1px solid #4a4a54;
              color: #e8e8ee; }
QPushButton:hover { background: #3e3e48; border-color: #5c5c68; }
QPushButton:pressed { background: #2c2c33; }
QPushButton:disabled { color: #6c6c74; background: #2c2c32; border-color: #3a3a42; }
QPushButton#primary { background: #d08a2c; color: #1b1206; font-weight: 700; font-size: 14px;
                      padding: 8px 22px; border: none; }
QPushButton#primary:hover { background: #e39a38; }
QPushButton#primary:disabled { background: #5a4a33; color: #2a2015; }
QPushButton#accent { background: #3b3326; border: 1px solid #8a6a3a; color: #f0d7a8; font-weight: 600;
                     padding: 8px 10px; }
QPushButton#accent:hover { background: #4a3f2e; }
QPushButton#small { padding: 3px 8px; }
QPushButton#tab { padding: 6px 16px; }
QPushButton#tab:checked { background: #4a3f2e; border: 1px solid #8a6a3a; color: #f0d7a8; }
QLabel#hint { color: #9a9aa3; }
QLabel#summary { color: #cfcfd6; font-weight: 600; }
QTabWidget::pane { border: 1px solid #3a3a42; border-radius: 6px; }
QTabBar::tab { padding: 7px 14px; }
"""


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


class HandBakeWorker(QThread):
    """Blender works out the hands' movement for the live view (hand_bake.py; no rendering)."""
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, blender, job_path, out_path):
        super().__init__()
        self.blender, self.job_path, self.out_path = blender, job_path, out_path

    def run(self):
        tail = []
        try:
            proc = subprocess.Popen(bb.command_hand_bake(self.blender, self.job_path),
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
            for line in proc.stdout:
                if line.strip():
                    tail = (tail + [line.rstrip()])[-20:]
            proc.wait()
        except OSError as exc:
            self.failed.emit(f'Could not start Blender for the hands: {exc}')
            return
        if proc.returncode or not Path(self.out_path).exists():
            err = next((t[6:] for t in reversed(tail) if t.startswith('ERROR ')), tail[-1] if tail else '')
            self.failed.emit(f'The hands could not be shown in the live view: {err}')
            return
        self.finished_ok.emit(self.out_path)


class RenderWorker(QThread):
    """Runs Blender, then (optionally) FFmpeg. Emits plain progress for the UI."""
    progress = Signal(int, int, float)   # done, total, seconds per frame
    message = Signal(str)
    finished_ok = Signal(str)            # folder
    failed = Signal(str)

    def __init__(self, blender, job, encode_opts=None, workers=1):
        super().__init__()
        self.blender, self.job, self.encode_opts = blender, job, encode_opts
        self.workers = max(1, int(workers))
        self.proc = None
        self.procs = []
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        for p in self.procs or [self.proc]:
            if p and p.poll() is None:
                p.kill()

    def run(self):
        out = Path(self.job['out_dir'])
        out.mkdir(parents=True, exist_ok=True)
        # Journal books can be rendered by several Blenders side by side, each doing one part of
        # the video: one draws on the graphics card while another prepares or saves its frame.
        n = self.workers if (self.job['book'].get('engine') == 'journal' and not self.job.get('frames')) else 1
        jobs = []
        for k in range(n):
            job = dict(self.job, chunk=[k, n]) if n > 1 else self.job
            path = out / (f'job_{k}.json' if n > 1 else 'job.json')
            path.write_text(json.dumps(job, indent=2), encoding='utf-8')
            jobs.append(path)
        error, tail, started = None, [], time.time()
        done = [0] * n
        totals = [0] * n
        lock = threading.Lock()

        def pump(k, proc):
            nonlocal error, tail
            for line in proc.stdout:
                kind, *rest = bb.parse_line(line)
                with lock:
                    if kind == 'progress':
                        done[k], totals[k] = rest
                        d = sum(done)
                        if all(totals):
                            self.progress.emit(d, sum(totals), (time.time() - started) / max(1, d))
                    elif kind == 'error':
                        error = rest[0]
                    elif kind == 'log' and line.strip():
                        tail = (tail + [f'[{k + 1}] ' + line.rstrip() if n > 1 else line.rstrip()])[-40:]
                        if line.startswith(('INFO', 'WARNING')) and k == 0:
                            self.message.emit(line.strip() + (f'  ({n} Blenders side by side)' if n > 1 else ''))
        try:
            for path in jobs:
                p = subprocess.Popen(bb.command(self.blender, path), stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                     errors='replace', creationflags=NO_WINDOW)
                self.procs.append(p)
            self.proc = self.procs[0]
            readers = [threading.Thread(target=pump, args=(k, p), daemon=True) for k, p in enumerate(self.procs)]
            for t in readers:
                t.start()
            for p in self.procs:
                p.wait()
            for t in readers:
                t.join(timeout=5)
        except OSError as exc:
            self.cancel()
            self.failed.emit(f'Could not start Blender: {exc}')
            return
        if self.cancelled:
            self.failed.emit('Cancelled. Frames already rendered are in:\n' + str(out))
            return
        if any(p.returncode for p in self.procs) or error:
            self.cancel()
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
            made.append(encode.encode_mov(out, fps, size=opts.get('mov_size', 'small')))
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
        if not self.settings.allKeys():                # first start after the rename: keep the old settings
            old = QSettings('StrokeDot', OLD_NAME)
            for key in old.allKeys():
                self.settings.setValue(key, old.value(key))
        self.worker = None
        self.update_thread = None
        self.preview_frames, self.preview_index = [], 0
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self._next_preview_frame)
        self.blender = bb.find_blender(self.settings.value('blender'))
        self.books = []
        self.recorded_clips = []
        self.edited_clips = None
        self._timeline_hand_edited = False   # True once clips are edited by hand in the timeline
        self._build()
        self._reload_books(self.settings.value('book', ''))
        self._load_settings()
        self._init_timeline()
        self._update_summary()
        self._update_blender_label()
        self._update_engine_ui()
        self._camera_changed()
        self._show_view(0)
        self._check_recovery()
        if self.settings.value('auto_update', 'true') == 'true':
            QTimer.singleShot(2500, lambda: self._check_updates(quiet=True))

    # ---------------------------------------------------------------- layout
    def _build(self):
        """Main window, laid out in the order you work:
        top bar (new / open / save ... render) · left: 1 Book, 2 Pages · centre: preview ·
        right: tabs for Camera, Animation, Export, Settings."""
        central = QWidget()
        central.setObjectName('central')
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(8)
        self.setStyleSheet(APP_STYLE)

        # ---- top bar ------------------------------------------------------------------
        top = QHBoxLayout()
        b = QPushButton('New book')
        b.setToolTip('Start fresh with the Leather Journal (your pages list is cleared)')
        b.clicked.connect(self._new_leather_book)
        top.addWidget(b)
        b = QPushButton('Open project…')
        b.clicked.connect(self._open_project)
        top.addWidget(b)
        b = QPushButton('Save project…')
        b.clicked.connect(self._save_project)
        top.addWidget(b)
        top.addStretch(1)
        self.summary = QLabel()
        self.summary.setObjectName('summary')
        top.addWidget(self.summary)
        top.addSpacing(12)
        self.render_btn = QPushButton('Render video')
        self.render_btn.setObjectName('primary')
        self.render_btn.setToolTip('Make the final video with everything you set')
        self.render_btn.clicked.connect(self._render)
        top.addWidget(self.render_btn)
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        top.addWidget(self.cancel_btn)
        self.open_btn = QPushButton('Open video folder')
        self.open_btn.clicked.connect(lambda: self._open_output())
        top.addWidget(self.open_btn)
        outer.addLayout(top)

        root = QSplitter()
        outer.addWidget(root, 1)

        # ---- left: 1 Book, 2 Pages ----------------------------------------------------
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)

        bookbox = QGroupBox('1  Your book')
        bl = QVBoxLayout(bookbox)
        self.book_combo = QComboBox()
        self.book_combo.setToolTip('Which book design to use')
        self.book_combo.currentIndexChanged.connect(self._update_summary)
        self.book_combo.currentIndexChanged.connect(self._camera_changed)
        self.book_combo.currentIndexChanged.connect(self._update_engine_ui)
        self.book_combo.activated.connect(self._template_chosen)
        bl.addWidget(self.book_combo)
        design = QPushButton('Change book design…')
        design.setObjectName('accent')
        design.setToolTip('Change the covers (outside and inside), the spine and the paper')
        design.clicked.connect(self._edit_book)
        bl.addWidget(design)
        row = QHBoxLayout()
        row.addWidget(QLabel('Sheets of paper'))
        self.page_count = QSpinBox()
        self.page_count.setRange(2, 2000)
        self.page_count.setValue(20)   # sheets; template overrides on load
        self.page_count.setSuffix(' sheets')
        self.page_count.setToolTip('Each sheet is 2 pages (front and back). More sheets = a thicker book '
                                   'with more pages.')
        self.page_count.valueChanged.connect(lambda *_: self._pages_changed())
        row.addWidget(self.page_count)
        bl.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('Page shape'))
        self.page_shape = QComboBox()
        for label, key in (('Flat', 'flat'), ('Curved', 'curved'), ('Very curved', 'very curved')):
            self.page_shape.addItem(label, key)
        self.page_shape.setToolTip('Curved: the pages rise out of the spine in a soft arch, like a real open book')
        self.page_shape.currentIndexChanged.connect(self._schedule_live)
        row.addWidget(self.page_shape, 1)
        bl.addLayout(row)
        row = QHBoxLayout()
        for text, fn, tip in (('Make a copy…', self._copy_book, 'Save this design under a new name'),
                              ('Open books folder', self._open_books_folder, 'Where your book designs are kept')):
            b = QPushButton(text)
            b.setObjectName('small')
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        bl.addLayout(row)
        self.blend_row = QWidget()
        r = QHBoxLayout(self.blend_row)
        r.setContentsMargins(0, 0, 0, 0)
        r.addWidget(QLabel('Page images'))
        self.blend = self._combo(bb.BLEND)
        self.blend.currentTextChanged.connect(self._schedule_live)
        r.addWidget(self.blend, 1)
        bl.addWidget(self.blend_row)
        lv.addWidget(bookbox)

        pagebox = QGroupBox('2  Pages')
        pl = QVBoxLayout(pagebox)
        self.pages = QListWidget()          # the pages themselves (the data); shown below as open spreads
        self.pages.setVisible(False)
        self.pages.model().rowsMoved.connect(self._pages_changed)
        self.page_summary = QLabel()
        self.page_summary.setObjectName('summary')
        pl.addWidget(self.page_summary)
        self.spreads = QListWidget()
        self.spreads.setIconSize(QSize(136, 92))
        self.spreads.setSpacing(2)
        self.spreads.setWordWrap(True)
        self.spreads.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.spreads.setToolTip('The book as you see it when it is open, two pages at a time. '
                                'Double-click to put pictures or text on them.')
        self.spreads.currentRowChanged.connect(self._spread_selected)
        self.spreads.itemDoubleClicked.connect(lambda *_: self._edit_layers())
        self.spreads.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.spreads.customContextMenuRequested.connect(lambda pos: self._page_menu().exec(
            self.spreads.viewport().mapToGlobal(pos)))
        pl.addWidget(self.spreads, 1)
        self.layers_btn = QPushButton('Pictures and text on these pages…')
        self.layers_btn.setObjectName('accent')
        self.layers_btn.setToolTip('Put pictures and text on the selected open pages (or double-click them). '
                                   '"Ink on the page" makes a picture look printed on the paper.')
        self.layers_btn.clicked.connect(self._edit_layers)
        pl.addWidget(self.layers_btn)
        row = QHBoxLayout()
        add_btn = QPushButton('Add pages  ▾')
        add_btn.setToolTip('Make the book longer')
        add_menu = QMenu(add_btn)
        add_menu.addAction('2 blank pages (one more sheet of paper)', self._add_blank)
        add_menu.addAction('Pages from pictures (each picture fills a whole page)…', self._add_images)
        add_menu.addAction('A page of text…', self._add_text)
        add_btn.setMenu(add_menu)
        row.addWidget(add_btn)
        self.page_btn = QPushButton('This page  ▾')
        self.page_btn.setToolTip('Move, empty or remove one of the selected pages')
        self.page_btn.clicked.connect(lambda: self._page_menu().exec(
            self.page_btn.mapToGlobal(self.page_btn.rect().bottomLeft())))
        row.addWidget(self.page_btn)
        pl.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('Page turns in the video'))
        self.turn_limit = QSpinBox()
        self.turn_limit.setRange(0, 2000)
        self.turn_limit.setToolTip('How many times a page turns in the video. Each turn shows the next two pages. '
                                   'Fewer turns = a shorter video; the book keeps all its pages.')
        self.turn_limit.valueChanged.connect(self._turns_changed)
        row.addWidget(self.turn_limit)
        self.turn_of = QLabel()
        row.addWidget(self.turn_of)
        row.addStretch(1)
        pl.addLayout(row)
        self.layout_hint = QLabel()
        self.layout_hint.setObjectName('hint')
        self.layout_hint.setWordWrap(True)
        pl.addWidget(self.layout_hint)
        self.page_framing = QGroupBox('Fit the selected image on its page')
        pf = QFormLayout(self.page_framing)
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
        pl.addWidget(self.page_framing)
        self._fit_loading = False
        self.pages.currentRowChanged.connect(self._load_page_fit)
        self.p_fit.currentTextChanged.connect(self._apply_page_fit)
        self.p_scale.valueChanged.connect(self._apply_page_fit)
        self.p_x.valueChanged.connect(self._apply_page_fit)
        self.p_y.valueChanged.connect(self._apply_page_fit)
        lv.addWidget(pagebox, 1)
        root.addWidget(left)

        # ---- centre: preview ----------------------------------------------------------
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        self.preview = QLabel('Press "Render a still" to see your book as the final video will look.\n'
                              'The checkerboard means transparent.')
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(560, 320)
        self.preview.setStyleSheet('background:#26262b;color:#aaa;border-radius:6px')
        self.views = QStackedWidget()
        self.live = LiveView() if (LiveView is not None and GL_IMPORT_ERROR is None) else None
        self.framing = self.live or FramingView()
        self.views.addWidget(self.framing)
        self.views.addWidget(self.preview)
        self.gltf = None
        row = QHBoxLayout()
        self.view_shot = QPushButton('Live view')
        self.view_shot.setToolTip('Instant preview. Drag: left = look around, right = move, wheel = zoom, '
                                  'double-click = reset')
        self.view_render = QPushButton('Rendered picture')
        self.view_render.setToolTip('What Blender made when you pressed "Render a still" or "Quick test video"')
        for b, i in ((self.view_shot, 0), (self.view_render, 1)):
            b.setCheckable(True)
            b.setObjectName('tab')
            b.clicked.connect(lambda _=False, i=i: self._show_view(i))
            row.addWidget(b)
        self.true_btn = QPushButton('True shape')
        self.true_btn.setCheckable(True)
        self.true_btn.setToolTip('Look at the book flat from straight above, with no perspective: its real '
                                 'proportions. Only for checking the shape - the video still uses your camera.')
        self.true_btn.toggled.connect(self._true_shape)
        self.true_btn.setEnabled(self.live is not None)
        row.addWidget(self.true_btn)
        row.addStretch(1)
        self.still_btn = QPushButton('Render a still')
        self.still_btn.setToolTip('Blender renders one picture of the open book - the real look, in about a minute')
        self.still_btn.clicked.connect(self._preview_still)
        self.anim_btn = QPushButton('Quick test video')
        self.anim_btn.setToolTip('Blender renders a rough, low-quality video of the first two page turns')
        self.anim_btn.clicked.connect(self._preview_anim)
        row.addWidget(self.still_btn)
        row.addWidget(self.anim_btn)
        self.view_gltf = QPushButton('glTF Viewport (Beta)')
        self.view_gltf.setCheckable(True)
        self.view_gltf.setVisible(False)
        self.view_gltf.clicked.connect(self._show_gltf)
        mv.addLayout(row)
        mv.addWidget(self.views, 1)
        self.playbar = QWidget()
        pbv = QVBoxLayout(self.playbar)
        pbv.setContentsMargins(0, 0, 0, 0)
        pbv.setSpacing(4)
        pb = QHBoxLayout()
        pb2 = QHBoxLayout()
        pbv.addLayout(pb)
        pbv.addLayout(pb2)
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
        self.speed.setToolTip('Playback speed of the live view (the video is not affected)')
        self.speed.currentTextChanged.connect(self._speed_changed)
        self.loop = QCheckBox('Repeat')
        self.loop.setToolTip('Start again from the beginning when playback reaches the end')
        self.loop.setChecked(True)
        self.loop.toggled.connect(lambda on: setattr(self.live, 'loop', on) if self.live else None)
        self.drag_pages = QCheckBox('Turn pages by hand')
        self.drag_pages.setToolTip('Left-drag a page in the live view to turn it')
        self.drag_pages.toggled.connect(lambda on: setattr(self.live, 'drag_pages', on) if self.live else None)
        self.record = QCheckBox('Record turns')
        self.record.setToolTip('While on, each page you turn by hand is added to the animation')
        self.show_where = QCheckBox('Page numbers')
        self.show_where.setToolTip('Show which pages are open, in the corner of the live view (never in the video)')
        self.show_where.setChecked(True)
        self.show_where.toggled.connect(lambda on: self._update_where())
        # row 1: play and the timeline bar (drag it to move through the animation); row 2: options
        self.scrub.setMinimumWidth(240)
        self.scrub.setToolTip('Drag to move through the animation frame by frame')
        for wdg in (self.play_btn, self.scrub, self.time_label):
            pb.addWidget(wdg, 1 if wdg is self.scrub else 0)
        pb2.addWidget(QLabel('Speed'))
        for wdg in (self.speed, self.loop, self.drag_pages, self.record, self.show_where):
            pb2.addWidget(wdg)
        pb2.addStretch(1)
        mv.addWidget(self.playbar)
        self.playbar.setVisible(self.live is not None)
        if self.live is not None:
            self.live.frameChanged.connect(self._live_frame)
            self.live.pageTurned.connect(self._on_page_turned)
            self.live.failed.connect(self._live_failed)
            self.live.problem.connect(lambda m: self.status.setText(
                f'Live view skipped a frame ({m}). Details: {paths.user_dir() / "logs" / "live_view.log"}'))
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self._refresh_live)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        mv.addWidget(self.progress)
        self.status = QLabel('Ready.')
        self.status.setObjectName('hint')
        self.status.setWordWrap(True)
        mv.addWidget(self.status)
        root.addWidget(mid)

        # ---- right: tabs ------------------------------------------------------------------
        tabs = QTabWidget()
        self.side_tabs = tabs

        # Camera tab
        cam = QWidget()
        cv = QVBoxLayout(cam)
        self.framing.orbit.connect(self._orbit)
        self.framing.pan.connect(self._pan)
        self.framing.zoomed.connect(lambda n: self.zoom.setValue(round(self.zoom.value() * 1.08 ** n)))
        self.framing.reset.connect(lambda: self._apply_preset(self.shot.currentText()))
        straight = QPushButton('Straighten the book')
        straight.setObjectName('accent')
        straight.setToolTip('Level the picture: no sideways lean, book facing you squarely, no rotation')
        straight.clicked.connect(self._straighten)
        cv.addWidget(straight)
        g = QGroupBox('Camera')
        f = QFormLayout(g)
        self.shot = self._combo(cf.PRESETS)
        self._add_my_cameras()
        self.shot.currentTextChanged.connect(self._apply_preset)
        f.addRow('Start from', self.shot)
        mine = QHBoxLayout()
        b = QPushButton('Save my camera…')
        b.setToolTip('Keep this camera under a name of your own. It appears in "Start from" for every book, '
                     'so all your books can use the same shot.')
        b.clicked.connect(self._save_my_camera)
        mine.addWidget(b)
        self.del_cam = QPushButton('Delete')
        self.del_cam.setToolTip('Delete the selected camera of your own')
        self.del_cam.clicked.connect(self._delete_my_camera)
        mine.addWidget(self.del_cam)
        f.addRow('', mine)
        self.tilt = self._slider(-89, 89, 50)
        self.turn = self._slider(-180, 180, 0)
        self.roll = self._slider(-180, 180, 0)
        self.lens = self._slider(18, 100, 35)
        self.zoom = self._slider(50, 250, 100)
        self.shift_x = self._slider(-60, 60, 0)
        self.shift_y = self._slider(-60, 60, 0)
        for label, sl in (('Look from above ↕', self.tilt), ('Walk around ↔', self.turn),
                          ('Lean sideways', self.roll), ('Zoom', self.zoom),
                          ('Move left / right', self.shift_x), ('Move down / up', self.shift_y),
                          ('Perspective', self.lens)):
            sl.valueChanged.connect(self._camera_changed)
            f.addRow(label, sl)
        self.zoom_mode = QComboBox()
        self.zoom_mode.addItem('Lens (the book keeps its look)', 'lens')
        self.zoom_mode.addItem('Move the camera closer (stronger 3D)', 'closer')
        self.zoom_mode.setToolTip('How Zoom brings the book closer.\nLens: like a zoom lens, only the size changes.\n'
                                  'Move closer: the camera walks up to the book; the near end looks bigger '
                                  '(the look before version 0.10.2).')
        self.zoom_mode.currentIndexChanged.connect(self._camera_changed)
        f.addRow('Zoom by', self.zoom_mode)
        self.move = self._combo(cf.MOVES)
        self.move.currentTextChanged.connect(self._camera_changed)
        f.addRow('Camera motion', self.move)
        b = QPushButton('Reset camera')
        b.clicked.connect(lambda: self._apply_preset(self.shot.currentText()))
        f.addRow(b)
        cv.addWidget(g)
        hint = QLabel('Tip: drag the live view - left button looks around, right button moves, '
                      'mouse wheel zooms, double-click resets.')
        hint.setObjectName('hint')
        hint.setWordWrap(True)
        cv.addWidget(hint)

        xform = QGroupBox('Book position (advanced)')
        xform.setCheckable(True)
        xform.setChecked(False)
        self.xform_box = xform
        f = QFormLayout(xform)
        xform_body = QWidget()
        xf = QFormLayout(xform_body)
        xf.setContentsMargins(0, 0, 0, 0)

        def num(lo, hi, val, step):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setSingleStep(step)
            s.setDecimals(2)
            s.setValue(val)
            s.setMinimumWidth(56)
            s.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)   # type or scroll the wheel
            s.valueChanged.connect(self._schedule_live)
            return s

        row = QHBoxLayout()
        self.pos_x, self.pos_y, self.pos_z = num(-3, 3, 0, 0.1), num(-3, 3, 0, 0.1), num(-3, 3, 0, 0.1)
        for w in (self.pos_x, self.pos_y, self.pos_z):
            row.addWidget(w)
        xf.addRow('Move X / Y / Z', row)
        row = QHBoxLayout()
        self.rot_x, self.rot_y, self.rot_z = num(-180, 180, 0, 5), num(-180, 180, 0, 5), num(-180, 180, 0, 5)
        for w in (self.rot_x, self.rot_y, self.rot_z):
            row.addWidget(w)
        xf.addRow('Rotate X / Y / Z (°)', row)
        row = QHBoxLayout()
        self.scl_x, self.scl_y, self.scl_z = num(0.1, 5, 1, 0.1), num(0.1, 5, 1, 0.1), num(0.1, 5, 1, 0.1)
        for w in (self.scl_x, self.scl_y, self.scl_z):
            row.addWidget(w)
        xf.addRow('Scale X / Y / Z', row)
        b = QPushButton('Reset book position')
        b.clicked.connect(self._reset_transform)
        xf.addRow(b)
        f.addRow(xform_body)
        xform_body.setVisible(False)
        xform.toggled.connect(xform_body.setVisible)
        cv.addWidget(xform)
        cv.addStretch(1)
        tabs.addTab(self._scrolled(cam), 'Camera')

        # Animation tab
        anim = QWidget()
        av = QVBoxLayout(anim)
        timing = QGroupBox('Timing (seconds)')
        f = QFormLayout(timing)
        self.turn_style = QComboBox()
        for label, key in (('Natural (smooth arc)', 'natural'),
                           ('Corner peel (like After Effects)', 'corner peel'),
                           ('Quick and light', 'quick')):
            self.turn_style.addItem(label, key)
        self.turn_style.setToolTip('How each page moves as it turns')
        self.turn_style.currentIndexChanged.connect(self._schedule_live)
        f.addRow('Page turn style', self.turn_style)
        self.hand_turns = QCheckBox('Show a 3D hand turning the pages')
        self.hand_turns.setToolTip('A right hand reaches in, pinches each page by its edge and turns it.\n'
                                   'It shows in the live view a few seconds after you tick it (Blender works\n'
                                   'out its movement in the background), in "Preview still" and in the video.')
        f.addRow(self.hand_turns)
        self.hand_left = QCheckBox('…and the left hand holds the book')
        self.hand_left.setChecked(True)
        self.hand_left.setToolTip('Like Arthur Morgan: the left hand steadies the closed book, moves out of the\n'
                                  'cover\'s way while it opens, then holds the open book by its bottom-left corner.')
        self.hand_left.setEnabled(False)
        self.hand_turns.toggled.connect(self.hand_left.setEnabled)
        f.addRow(self.hand_left)
        self.hand_left_style = QComboBox()
        self.hand_left_style.addItem('On the book (holds its corner)', 'on')
        self.hand_left_style.addItem('Under the book (holds it up, like Arthur)', 'under')
        self.hand_left_style.setToolTip('On the book: the book lies on a table and the left hand holds it by the corner.\n'
                                        'Under the book: the left hand holds the book up from beneath, palm up, like\n'
                                        'Arthur Morgan reading his journal (no table under it).')
        self.hand_left_style.setEnabled(False)
        f.addRow('Left hand', self.hand_left_style)
        self.hand_size = QSpinBox()
        self.hand_size.setRange(60, 140)
        self.hand_size.setSingleStep(5)
        self.hand_size.setValue(100)
        self.hand_size.setSuffix(' %')
        self.hand_size.setToolTip('The hands\' size: 100 % is a real man\'s hand next to the book at its real size')
        self.hand_size.setEnabled(False)
        f.addRow('Hand size', self.hand_size)

        def _left_style_on(_=None):
            self.hand_left_style.setEnabled(self.hand_turns.isChecked() and self.hand_left.isChecked())
        self.hand_turns.toggled.connect(_left_style_on)
        self.hand_left.toggled.connect(_left_style_on)
        self.hand_turns.toggled.connect(self.hand_size.setEnabled)
        for sig in (self.hand_turns.toggled, self.hand_left.toggled, self.hand_left_style.currentIndexChanged,
                    self.hand_size.valueChanged):
            sig.connect(self._schedule_live)
        # the hand's look, swappable like the book's pictures
        self.hand_skin = QComboBox()
        self.hand_skin.addItem('Bare hand (from the photos)', '')
        self.hand_skin.addItem('Leather glove (the cover\'s leather)', 'book-leather')
        self.hand_skin.addItem('From a picture…', 'pick')
        self.hand_skin.setToolTip('What the hand looks like: bare skin, a leather glove like the book\'s cover,\n'
                                  'or any picture of leather, fabric or skin wrapped over the hand')
        self.hand_skin.activated.connect(lambda _i: self._hand_pick(self.hand_skin, 'Hand skin'))
        self.hand_skin.currentIndexChanged.connect(self._schedule_live)
        f.addRow('Hand skin', self.hand_skin)
        self.hand_sleeve = QComboBox()
        self.hand_sleeve.addItem('Brown suede', '')
        self.hand_sleeve.addItem('From a picture…', 'pick')
        self.hand_sleeve.setToolTip('The sleeve: brown suede, or any picture of a fabric (repeated over the sleeve)')
        self.hand_sleeve.activated.connect(lambda _i: self._hand_pick(self.hand_sleeve, 'Sleeve'))
        self.hand_sleeve.currentIndexChanged.connect(self._schedule_live)
        f.addRow('Sleeve', self.hand_sleeve)
        for w in (self.hand_skin, self.hand_sleeve):
            w.setEnabled(False)
            self.hand_turns.toggled.connect(w.setEnabled)
        flip = QPushButton('Add a fast flip…')
        flip.setToolTip('Flip through many pages quickly, like riffling them with your thumb')
        flip.clicked.connect(self._fast_flip)
        f.addRow(flip)
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
        f.addRow('Pause between turns', self.pause_s)
        f.addRow('Wait before starting', self.start_s)
        f.addRow('Wait at the end', self.end_s)
        self.smooth = self._slider(0, 100, 100)
        self.smooth.valueChanged.connect(self._schedule_live)
        f.addRow('Smoothness', self.smooth)
        self.curl_label = QLabel('Page curl')
        self.curl = self._slider(0, 150, 90)
        self.curl.valueChanged.connect(self._schedule_live)
        f.addRow(self.curl_label, self.curl)
        av.addWidget(timing)
        self.timeline_panel = TimelinePanel()
        self.timeline_panel.changed.connect(self._timeline_changed)
        av.addWidget(self.timeline_panel, 1)
        tabs.addTab(anim, 'Animation')

        # Export tab
        exp = QWidget()
        ev = QVBoxLayout(exp)
        out = QGroupBox('Video')
        f = QFormLayout(out)
        self.resolution = self._combo(RESOLUTIONS)
        self.resolution.currentTextChanged.connect(self._camera_changed)
        self.fps = QComboBox()
        self.fps.addItems(['24', '30', '60'])
        self.fps.setCurrentText('30')
        self.fps.currentTextChanged.connect(self._update_summary)
        self.quality = self._combo(bb.QUALITY)
        self.quality.setCurrentIndex(1)
        f.addRow('Size', self.resolution)
        f.addRow('Frames per second', self.fps)
        f.addRow('Quality', self.quality)
        self.mov = QCheckBox('MOV with transparency (best for Filmora)')
        self.mov.setChecked(True)
        self.mov_size = QComboBox()
        self.mov_size.addItem('Smaller file - looks the same (recommended)', 'small')
        self.mov_size.addItem('Maximum quality - very large file', 'max')
        self.mov_size.setToolTip('Smaller is about a quarter of the size with no visible difference')
        self.mov.toggled.connect(self.mov_size.setEnabled)
        self.webm = QCheckBox('WebM (small file)')
        self.keep_png = QCheckBox('Also keep the PNG frames')
        f.addRow(self.mov)
        f.addRow('MOV file size', self.mov_size)
        for w in (self.webm, self.keep_png):
            f.addRow(w)
        tip = QLabel('Tip: 30 frames per second is plenty for page turns and makes files half the size of 60.')
        tip.setObjectName('hint')
        tip.setWordWrap(True)
        f.addRow(tip)
        row = QHBoxLayout()
        self.out_label = QLabel()
        self.out_label.setWordWrap(True)
        b = QPushButton('Change…')
        b.clicked.connect(self._choose_output)
        row.addWidget(self.out_label, 1)
        row.addWidget(b)
        f.addRow('Save to', row)
        ev.addWidget(out)
        ev.addStretch(1)
        tabs.addTab(exp, 'Export')

        # Settings tab
        st = QWidget()
        sv = QVBoxLayout(st)
        eng = QGroupBox('Blender (the 3D engine)')
        el = QVBoxLayout(eng)
        self.blender_label = QLabel()
        self.blender_label.setWordWrap(True)
        el.addWidget(self.blender_label)
        row = QHBoxLayout()
        b = QPushButton('Find blender.exe…')
        b.clicked.connect(self._browse_blender)
        t = QPushButton('Test')
        t.clicked.connect(self._test_blender)
        row.addWidget(b)
        row.addWidget(t)
        el.addLayout(row)
        self.parallel = QCheckBox('Render with 2 Blenders at once (faster)')
        self.parallel.setToolTip('Each Blender renders half of the video at the same time, so the graphics card '
                                 'is kept busy. Turn off if your computer runs out of memory.')
        self.parallel.setChecked(self.settings.value('parallel', 'true') == 'true')
        self.parallel.toggled.connect(lambda on: self.settings.setValue('parallel', 'true' if on else 'false'))
        el.addWidget(self.parallel)
        sv.addWidget(eng)
        upd = QGroupBox('Updates')
        ul = QVBoxLayout(upd)
        row = QHBoxLayout()
        u = QPushButton('Check for updates')
        u.clicked.connect(lambda: self._check_updates(quiet=False))
        row.addWidget(u)
        self.auto_update = QCheckBox('Check at startup')
        self.auto_update.setChecked(self.settings.value('auto_update', 'true') == 'true')
        self.auto_update.toggled.connect(lambda on: self.settings.setValue('auto_update', 'true' if on else 'false'))
        row.addWidget(self.auto_update)
        ul.addLayout(row)
        ul.addWidget(QLabel(f'Version {APP_VERSION}'))
        sv.addWidget(upd)
        sv.addStretch(1)
        tabs.addTab(st, 'Settings')

        tabs.setMinimumWidth(360)
        root.addWidget(tabs)
        root.setSizes([290, 800, 380])
        root.setStretchFactor(1, 1)

        for w in (self.turn_s, self.pause_s, self.start_s, self.end_s, self.open_s):
            w.valueChanged.connect(self._update_summary)

    def _scrolled(self, widget):
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setFrameShape(QScrollArea.Shape.NoFrame)
        s.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        s.setWidget(widget)
        return s

    def _update_engine_ui(self, *_):
        """Hide controls the chosen book does not use, so only what matters is on screen."""
        if not hasattr(self, 'page_framing') or not self.books:
            return
        journal = self._book().get('engine') == 'journal'
        self.page_framing.setVisible(not journal)     # journal pages are always full-page images
        self.blend_row.setVisible(not journal)
        self.curl.setVisible(not journal)              # the journal has its own natural page bend
        self.curl_label.setVisible(not journal)

    def _straighten(self):
        """A level, square-on picture: no sideways lean or walk-around, no book rotation."""
        self.roll.setValue(0)
        self.turn.setValue(0)
        self.shift_x.setValue(0)
        for w in (self.rot_x, self.rot_y, self.rot_z):
            w.setValue(0)
        self.status.setText('Straightened: the book faces you squarely with no lean. '
                            'Use "Look from above" to change the angle.')

    def _fill_blank(self):
        """Add blank pages until the list has every page of the book (2 per sheet)."""
        target = self.page_count.value() * 2
        added = 0
        while self.pages.count() < target:
            self._add_page_item(None)
            added += 1
        self._pages_changed()
        self.status.setText(f'Added {added} blank page(s): all {target} pages now turn.' if added
                            else 'Every page of the book already has a page in the list.')

    def _hand_pick(self, combo, what):
        """'From a picture…' in a hand-look list: choose the picture and show it in the list."""
        if combo.currentData() != 'pick':
            return
        path, _ = QFileDialog.getOpenFileName(self, f'{what}: choose a picture', self.settings.value('img_dir', ''),
                                              'Pictures (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)')
        if not path:
            combo.setCurrentIndex(0)
            return
        self._hand_set(combo, path)

    @staticmethod
    def _hand_set(combo, value):
        """Select a hand-look value; a picture path gets its own entry (named after the file)."""
        i = combo.findData(value or '')
        if i < 0:
            combo.insertItem(combo.count() - 1, Path(value).name, value)
            i = combo.findData(value)
        combo.setCurrentIndex(i)

    def _fast_flip(self):
        """Add a burst of quick, overlapping page turns at the end of the animation."""
        from PySide6.QtWidgets import QInputDialog
        v = self._values()
        turned = layout_pages(self.pages.count())[0] if self.pages.count() else 0
        left = max(1, self.page_count.value() - turned)
        n, ok = QInputDialog.getInt(self, 'Fast flip', f'How many pages to flip? (up to {left} left in the book)',
                                    min(8, left), 2, max(2, left))
        if not ok:
            return
        secs, ok = QInputDialog.getDouble(self, 'Fast flip', f'Flip {n} pages in how many seconds?',
                                          max(0.8, round(n * 0.18, 1)), 0.3, 30.0, 1)
        if not ok:
            return
        fps = v['fps']
        # each page needs a page on both sides: add blank pages so the list covers the new turns
        need = (turned + n) * 2
        while self.pages.count() < need:
            self._add_page_item(None)
        self._timeline_hand_edited = True
        self._pages_changed()                       # adds n turn clips at the end
        clips = [clip_from_dict(d) for d in (self.edited_clips or [])]
        turns = [c for c in clips if c.kind == 'turn']
        burst = turns[-n:]
        total = max(2, round(secs * fps))
        each = max(4, round(total * 0.42))          # one page's own turn
        gap = max(1, round((total - each) / max(1, n - 1)))
        gap = max(gap, round(each * 0.2))           # pages stay a sheet apart in the air
        start = (burst[0].start if burst else 0)
        prev_end = max((c.start + c.duration for c in clips if not any(c is b for b in burst)), default=0)
        start = max(prev_end + round(v['pause'] * fps), 0)
        for k, c in enumerate(burst):
            c.start, c.duration = start + k * gap, each
        self.edited_clips = [clip_to_dict(c) for c in clips]
        self.timeline_panel.set_clips(clips)
        self._update_summary()
        self.status.setText(f'Added a fast flip: {n} pages in about {(gap * (n - 1) + each) / fps:.1f} s. '
                            'Press Play to watch it.')

    def _clear_pages(self):
        if self.pages.count() and QMessageBox.question(
                self, APP_NAME, 'Remove all pages from the list?') == QMessageBox.StandardButton.Yes:
            self.pages.clear()
            self._pages_changed()

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

    def _template_chosen(self, index):
        """Picking a template by hand also takes its own sheet count (a journal is 10 sheets)."""
        if 0 <= index < len(self.books) and self.books[index].get('page_count'):
            self.page_count.setValue(int(self.books[index]['page_count']))

    def _book(self):
        i = self.book_combo.currentIndex()
        return self.books[i] if 0 <= i < len(self.books) else self.books[0]

    def _edit_book(self):
        if self._book().get('engine') == 'journal':
            try:
                preview = (self._content_images(), self._values())
            except Exception:  # no pages yet or a broken setting: compare is just not offered
                preview = None
            old_aspect = float(self._book().get('page_aspect', 1.4318))
            dlg = JournalDialog(self._book(), self, preview=preview)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                reshaped = dlg.shape_changed()
                saved = templates.save(dlg.result_book(), None, dlg.new_images)
                self._reload_books(saved['folder'])
                if reshaped:
                    self._refit_pages()
                    self._rescale_pictures(old_aspect, float(self._book().get('page_aspect', old_aspect)))
                self._pages_changed()
                self._refresh_live()          # show the new images right away
                self.status.setText(f'Saved book "{saved["name"]}". The live view shows the new design.')
            return
        dlg = BookDialog(self._book(), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            saved = templates.save(dlg.result_book(), dlg.new_image, dlg.art_images)
            self._reload_books(saved['folder'])
            self.status.setText(f'Saved book "{saved["name"]}". Press "Preview still" to see it.')

    def _rescale_pictures(self, old_aspect, new_aspect):
        """Pictures and text on the pages follow a new page shape. Their place is kept as a share of
        the page; their size follows the page's height (shorter page = smaller pictures, taller =
        bigger), never wider than the page, so they keep their proportions and still fit."""
        r = new_aspect / max(1e-6, old_aspect)
        if abs(r - 1.0) < 1e-3:
            return
        for i in range(self.pages.count()):
            layers = self.pages.item(i).data(self.LAYERS_ROLE) or []
            if not layers:
                continue
            out = []
            for l in layers:
                l = dict(l)
                w = float(l.get('w', 0.6))
                limit = 0.98 if l.get('spread') else 0.95
                l['w'] = round(w * r if r < 1 else min(w * r, max(w, limit)), 4)
                out.append(l)
            self.pages.item(i).setData(self.LAYERS_ROLE, out)

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
    LAYERS_ROLE = Qt.ItemDataRole.UserRole + 3

    def _page_layers(self, i):
        return list(self.pages.item(i).data(self.LAYERS_ROLE) or [])

    def _page_size(self):
        """Pixel size of one page of the current book (what page pictures are made at)."""
        book = self._book() if self.books else {}
        need = required_size(book, 'page') if book else None
        if need:
            return need
        return (982, round(982 * float(book.get('page_aspect', 1.4318))))

    def _page_content(self):
        """Content sides in reading order: None (blank), or a {'kind': 'image'|'text', ...} dict."""
        out = []
        for i in range(self.pages.count()):
            item = self.pages.item(i)
            path = item.data(Qt.ItemDataRole.UserRole) or None
            text = item.data(self.TEXT_ROLE) or None
            layers = self._page_layers(i)
            if text:
                side = {'kind': 'text', 'text': text}
            elif path:
                side = {'kind': 'image', 'image': path}
            else:
                side = {'kind': 'blank'} if layers else None
            if layers:
                side['layers'] = layers
            out.append(side)
        return out

    def _content_images(self):
        """Rasterise text sides to PNGs and return plain image paths for the renderers."""
        from page_text import sides_to_images
        sides = self._page_content()
        images = sides_to_images(sides, paths.cache_dir('pages'), float(self._book().get('page_aspect', 1.4)))
        return self._with_layers(sides, images)

    def _with_layers(self, sides, images):
        """Flatten each side's pictures (with Ink on the page) onto its page image."""
        import page_layers
        size = self._page_size()
        out = list(images)
        spreads = []
        for i, side in enumerate(sides):
            own, spread = page_layers.split(side.get('layers') if isinstance(side, dict) else None)
            if own:
                try:
                    out[i] = page_layers.compose_to_file(images[i], own, size, paths.cache_dir('pages'))
                except Exception as exc:  # a missing or broken picture must not stop the preview
                    self.status.setText(f'Page {i + 1}: a picture could not be used ({exc}).')
            if spread and i % 2 == 1 and i + 1 < len(out):      # left page i + right page i + 1
                spreads.append((i, spread))
        for i, spread in spreads:      # pictures across a spread go on top of each page's own pictures
            try:
                out[i], out[i + 1] = page_layers.compose_spread_to_files(out[i], out[i + 1], spread, size,
                                                                         paths.cache_dir('pages'))
            except Exception as exc:
                self.status.setText(f'Pages {i + 1}-{i + 2}: a picture could not be used ({exc}).')
        return out

    def _edit_layers(self):
        """Open the picture window on the open spread of the selected page."""
        from layer_dialog import PicturesDialog
        from page_text import sides_to_images
        import page_layers
        if self.pages.count() == 0:
            self._add_blank()
        row = max(0, self.pages.currentRow())
        book = self._book()
        sides = self._page_content()
        bases = sides_to_images([dict(sd, layers=None) if isinstance(sd, dict) else sd for sd in sides],
                                paths.cache_dir('pages'), float(book.get('page_aspect', 1.4)))
        app = self

        class BookPages:
            page_size = self._page_size()
            page_cm = float((book.get('page_size_cm') or [15.0])[0])

            @staticmethod
            def count():
                return app.pages.count()

            @staticmethod
            def paper(r):
                field = 'paper_odd_image' if r % 2 == 0 else 'paper_even_image'
                return templates._texture_path(book, book.get(field) or book.get('paper_image'))

            @staticmethod
            def base(r):
                return bases[r] if r < len(bases) else None

            @staticmethod
            def layers(r):
                return app._page_layers(r)

        dlg = PicturesDialog(BookPages, row, self, self.settings.value('img_dir', ''),
                             float(self.settings.value('picture_margin', 0.08)))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            for r, layers in dlg.result().items():
                if r < self.pages.count():
                    self.pages.item(r).setData(self.LAYERS_ROLE, [dict(l) for l in layers])
            self.settings.setValue('img_dir', dlg.start_dir)
            self.settings.setValue('picture_margin', dlg.margin_value())
            self._pages_changed()
            self._refresh_live()

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

    def _add_page_item(self, path, text='', layers=None, at=None):
        if path:
            item = QListWidgetItem(QIcon(QPixmap(path).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                                              Qt.TransformationMode.SmoothTransformation)), '')
        else:
            item = QListWidgetItem('')
        item.setData(Qt.ItemDataRole.UserRole, path or '')
        item.setData(self.TEXT_ROLE, text or '')
        item.setData(self.FIT_ROLE, {'mode': 'fit', 'scale': 1.0, 'x': 0.0, 'y': 0.0})
        item.setData(self.LAYERS_ROLE, list(layers or []))
        if at is None or at >= self.pages.count():
            self.pages.addItem(item)
        else:
            self.pages.insertItem(max(0, at), item)

    def _ask_adjust(self, n_wrong, n_all, need, keep_label='Skip them'):
        box = QMessageBox(self)
        box.setWindowTitle('Page size')
        box.setText(f'{n_wrong} of the {n_all} image(s) are not {need[0]} × {need[1]} px, '
                    'the size of a page in this book.')
        box.setInformativeText('Adjust them for you? Your original files are not changed.')
        auto = box.addButton('Adjust all (crop to fill, centred)', QMessageBox.ButtonRole.AcceptRole)
        each = box.addButton('Let me adjust each one', QMessageBox.ButtonRole.ActionRole)
        skip = box.addButton(keep_label, QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return {auto: 'auto', each: 'each', skip: 'skip'}.get(box.clickedButton(), 'skip')

    def _refit_pages(self):
        """After the book changed shape: offer to fit page images that are not the new page size."""
        book = self._book()
        need = required_size(book, 'page')
        rows = [i for i in range(self.pages.count())
                if self.pages.item(i).data(Qt.ItemDataRole.UserRole)
                and check_size(book, 'page', self.pages.item(i).data(Qt.ItemDataRole.UserRole))]
        if not need or not rows:
            return
        choice = self._ask_adjust(len(rows), sum(1 for p in self._page_paths() if p), need,
                                  'Keep them (stretched to the new shape)')
        for i in rows:
            item = self.pages.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            if choice == 'auto':
                new = auto_adjust(path, need)
            elif choice == 'each':
                fit = ImageFitDialog(path, need, f'page {i + 1}', self)
                if fit.exec() != QDialog.DialogCode.Accepted or not fit.result_path:
                    continue
                new = fit.result_path
            else:
                return
            item.setData(Qt.ItemDataRole.UserRole, new)
            item.setIcon(QIcon(QPixmap(new).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                                   Qt.TransformationMode.SmoothTransformation)))

    def _add_images(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Choose page images', self.settings.value('img_dir', ''),
                                                'Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)')
        book = self._book() if self.books else {}
        need = required_size(book, 'page') if book else None
        wrong = [p for p in files if need and check_size(book, 'page', p)]
        choice = None
        if wrong:
            choice = self._ask_adjust(len(wrong), len(files), need)
        for path in files:
            if path in wrong:
                if choice == 'auto':
                    path = auto_adjust(path, need)
                elif choice == 'each':
                    fit = ImageFitDialog(path, need, f'page {self.pages.count() + 1}', self)
                    if fit.exec() != QDialog.DialogCode.Accepted or not fit.result_path:
                        continue
                    path = fit.result_path
                else:
                    continue
            self._add_page_item(path, at=self._next_slot())     # the next empty page
        if files:
            self.settings.setValue('img_dir', str(Path(files[0]).parent))
        self._pages_changed()

    def _add_blank(self):
        """One more sheet of paper: two blank pages at the end of the book."""
        self.page_count.setValue(self.page_count.value() + 1)
        self.status.setText(f'Added 2 blank pages: the book now has {self.pages.count()} pages.')

    def _add_text(self):
        """A page of text, on the next empty page (StrokeScribe's fonts)."""
        import fonts
        import page_layers
        from text_dialog import TextDialog
        book = self._book()
        at = self._next_slot()
        field = 'paper_odd_image' if at % 2 == 0 else 'paper_even_image'
        paper = templates._texture_path(book, book.get(field) or book.get('paper_image'))
        pw, ph = self._page_size()
        dlg = TextDialog(None, paper, pw, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        t = dlg.result_text()
        img = fonts.text_image_file(t, pw, paths.cache_dir('text'), float((book.get('page_size_cm') or [15.0])[0]))
        iw, ih = page_layers.picture_size(img)
        margin = float(self.settings.value('picture_margin', 0.08))
        placed_h = float(t['width']) * pw * ih / max(1, iw)
        layer = page_layers.new_layer(img, ink_on=False, ink_edges='No fading', text=t, w=float(t['width']), x=0.5,
                                      y=min(0.5, (margin * pw + placed_h / 2) / ph))
        if at < self.pages.count() and self._page_is_blank(at):
            self.pages.item(at).setData(self.LAYERS_ROLE, [layer])
        else:
            self._add_page_item(None, layers=[layer], at=at)
        self._pages_changed()
        self.status.setText(f'Text put on page {at + 1}. Double-click the pages to move it or change it.')

    # ------------------------------------------------------------------ pages as open spreads
    def _page_is_blank(self, i):
        item = self.pages.item(i)
        return not (item.data(Qt.ItemDataRole.UserRole) or item.data(self.TEXT_ROLE)
                    or item.data(self.LAYERS_ROLE))

    def _next_slot(self):
        """Where new pages go: right after the last page that has something on it."""
        last = -1
        for i in range(self.pages.count()):
            if not self._page_is_blank(i):
                last = i
        return last + 1

    def _sync_page_count(self):
        """The book always has every page of its sheets (2 per sheet): blank pages fill the end,
        and the book grows when more pages are added than it has."""
        if getattr(self, '_syncing', False) or not hasattr(self, 'page_count'):
            return
        self._syncing = True
        try:
            target = self.page_count.value() * 2
            n = self.pages.count()
            while n > target and self._page_is_blank(n - 1):
                self.pages.takeItem(n - 1)
                n -= 1
            if n > target:
                self.page_count.blockSignals(True)
                self.page_count.setValue((n + 1) // 2)
                self.page_count.blockSignals(False)
                target = self.page_count.value() * 2
            while n < target:
                self._add_page_item(None)
                n += 1
        finally:
            self._syncing = False

    def _spread_rows(self, s):
        n = self.pages.count()
        if s == 0:
            return (None, 0 if n else None)
        return (2 * s - 1 if 2 * s - 1 < n else None, 2 * s if 2 * s < n else None)

    def _spread_selected(self, s):
        left, right = self._spread_rows(max(0, s))
        row = right if right is not None else left
        if row is not None:
            self.pages.setCurrentRow(row)

    def _describe_page(self, i):
        item = self.pages.item(i)
        layers = item.data(self.LAYERS_ROLE) or []
        bits = []
        if item.data(self.TEXT_ROLE):
            bits.append('text')
        if item.data(Qt.ItemDataRole.UserRole):
            bits.append('full-page picture')
        texts = sum(1 for l in layers if l.get('text') and not l.get('spread'))
        pics = sum(1 for l in layers if not l.get('text') and not l.get('spread'))
        if texts:
            bits.append('text' if texts == 1 else f'{texts} texts')
        if pics:
            bits.append('1 picture' if pics == 1 else f'{pics} pictures')
        return ', '.join(bits) or 'blank'

    def _spread_thumb(self, s, images, book):
        """Small picture of an open spread: both pages with what is on them."""
        W, H = 136, 92
        pix = QPixmap(W, H)
        pix.fill(QColor('#24242a'))
        aspect = float(book.get('page_aspect', 1.43))
        ph = H - 8
        pw = min(int(ph / aspect), (W - 10) // 2)
        ph = int(pw * aspect)
        x0, y0 = (W - 2 * pw - 2) // 2, (H - ph) // 2
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        left, right = self._spread_rows(s)
        cache = self.__dict__.setdefault('_thumb_cache', {})

        def img(path):
            if not path or not Path(path).exists():
                return None
            key = (str(path), Path(path).stat().st_mtime_ns, pw, ph)
            if key not in cache:
                if len(cache) > 400:
                    cache.clear()
                q = QPixmap(str(path))
                cache[key] = None if q.isNull() else q.scaled(pw, ph, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                              Qt.TransformationMode.SmoothTransformation)
            return cache[key]
        for k, row in enumerate((left, right)):
            x = x0 + k * (pw + 2)
            if row is None:
                field = 'front_interior_image' if s == 0 else 'back_interior_image'
                cover = img(templates._texture_path(book, book.get(field)))
                if cover is not None:
                    p.drawPixmap(x, y0, cover)
                else:
                    p.fillRect(x, y0, pw, ph, QColor('#5a3018'))
                continue
            field = 'paper_odd_image' if row % 2 == 0 else 'paper_even_image'
            paper = img(templates._texture_path(book, book.get(field) or book.get('paper_image')))
            if paper is not None:
                p.drawPixmap(x, y0, paper)
            else:
                p.fillRect(x, y0, pw, ph, QColor('#e8dcc4'))
            content = img(images[row]) if row < len(images) else None
            if content is not None:
                p.drawPixmap(x, y0, content)
        p.end()
        return QIcon(pix)

    def _rebuild_spreads(self):
        if not hasattr(self, 'spreads') or not self.books:
            return
        book = self._book()
        try:
            images = self._content_images()
        except Exception:  # a broken picture must not empty the list
            images = [None] * self.pages.count()
        cur = max(0, self.spreads.currentRow())
        n = self.pages.count()
        count = 1 + n // 2 if n else 0
        self.spreads.blockSignals(True)
        self.spreads.clear()
        for s in range(count):
            left, right = self._spread_rows(s)
            if s == 0:
                title = 'Inside cover  ·  page 1'
                what = self._describe_page(0)
            elif right is None:
                title = f'Page {left + 1}  ·  back cover'
                what = self._describe_page(left)
            else:
                title = f'Pages {left + 1} – {right + 1}'
                across = any(l.get('spread') for l in (self.pages.item(left).data(self.LAYERS_ROLE) or []))
                a, b = self._describe_page(left), self._describe_page(right)
                what = ('picture across both pages' + ('' if (a, b) == ('blank', 'blank') else
                                                       f'  ·  {a}  |  {b}')) if across else f'{a}  |  {b}'
                if not across and a == b == 'blank':
                    what = 'blank'
            item = QListWidgetItem(self._spread_thumb(s, images, book), f'{title}\n{what}')
            item.setSizeHint(QSize(0, 98))
            self.spreads.addItem(item)
        self.spreads.setCurrentRow(min(cur, count - 1))
        self.spreads.blockSignals(False)

    def _page_menu(self):
        menu = QMenu(self)
        left, right = self._spread_rows(max(0, self.spreads.currentRow()))
        rows = [r for r in (left, right) if r is not None]
        for r in rows:
            sub = menu.addMenu(f'Page {r + 1}  ({self._describe_page(r)})')
            a = sub.addAction('Move it one page earlier', lambda r=r: self._swap_pages(r, r - 1))
            a.setEnabled(r > 0)
            a = sub.addAction('Move it one page later', lambda r=r: self._swap_pages(r, r + 1))
            a.setEnabled(r + 1 < self.pages.count())
            sub.addAction('Make it blank (keep the page)', lambda r=r: self._blank_page(r))
            sub.addAction('Remove it (the pages after it move up)', lambda r=r: self._remove_page_at(r))
        menu.addSeparator()
        menu.addAction('Make every page blank…', self._clear_pages)
        return menu

    def _swap_pages(self, a, b):
        if not (0 <= a < self.pages.count() and 0 <= b < self.pages.count()):
            return
        lo, hi = min(a, b), max(a, b)
        item = self.pages.takeItem(hi)
        self.pages.insertItem(lo, item)
        self._pages_changed()
        self.spreads.setCurrentRow(0 if b == 0 else (b + 1) // 2)

    def _blank_page(self, r):
        item = self.pages.item(r)
        for role in (Qt.ItemDataRole.UserRole, self.TEXT_ROLE):
            item.setData(role, '')
        item.setData(self.LAYERS_ROLE, [])
        item.setIcon(QIcon())
        self._pages_changed()

    def _remove_page_at(self, r):
        self.pages.takeItem(r)
        self._pages_changed()

    def _video_turns(self):
        """How many pages turn in the video: every page, or fewer if asked."""
        turns = layout_pages(self.pages.count())[0]
        if hasattr(self, 'turn_limit') and not getattr(self, '_turn_limit_all', True):
            return min(turns, self.turn_limit.value())
        return turns

    def _turns_changed(self, v):
        self._turn_limit_all = v >= self.turn_limit.maximum()
        if not getattr(self, '_syncing', False):
            self._update_summary()

    def _remove_page(self):
        row = self.pages.currentRow()
        if row >= 0:
            self._remove_page_at(row)

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
        self._sync_page_count()
        n = self.pages.count()
        turns = layout_pages(n)[0]
        self._syncing = True
        all_turns = getattr(self, '_turn_limit_all', True)
        self.turn_limit.setMaximum(max(turns, 0))
        if all_turns or self.turn_limit.value() > turns:
            self.turn_limit.setValue(turns)
        self._syncing = False
        self.turn_of.setText(f'of {turns}')
        filled = sum(1 for i in range(n) if not self._page_is_blank(i))
        self.page_summary.setText(f'{n} pages  ·  {self.page_count.value()} sheets  ·  '
                                  f'{filled} with something on them')
        need = required_size(self._book(), 'page') if self.books else None
        size = f' Full-page pictures are made {need[0]} × {need[1]} px.' if need else ''
        self.layout_hint.setText('Each row is the book open at two pages. Double-click a row to put pictures '
                                 'or text on it; right-click to move or remove a page.' + size)
        self._rebuild_spreads()
        self._update_summary()

    def _set_pages(self, pages):
        self.pages.clear()
        missing = 0
        for p in pages:
            if p is None:
                self._add_page_item(None)
            elif isinstance(p, dict):
                layers = [l for l in (p.get('layers') or []) if Path(l.get('image', '')).exists()]
                missing += len(p.get('layers') or []) - len(layers)
                self._add_page_item(p.get('image'), p.get('text', ''), layers)
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
                    turn_limit=None if getattr(self, '_turn_limit_all', True) else self.turn_limit.value(),
                    smoothness=self.smooth.value() / 100, recorded_clips=self.recorded_clips,
                    clip_list=self.edited_clips, transform=self._transform(),
                    page_shape=self.page_shape.currentData() or 'flat',
                    turn_style=self.turn_style.currentData() or 'natural',
                    hand=self.hand_turns.isChecked(), hand_left=self.hand_left.isChecked(),
                    hand_left_style=self.hand_left_style.currentData() or 'on', hand_size=self.hand_size.value(),
                    hand_skin=self.hand_skin.currentData() or '', hand_sleeve=self.hand_sleeve.currentData() or '',
                    page_fits=self._page_fits())

    def _state(self):
        v = self._values()
        v.update(resolution=self.resolution.currentText(), mov=self.mov.isChecked(), webm=self.webm.isChecked(),
                 keep_png=self.keep_png.isChecked(), mov_size=self.mov_size.currentData() or 'small',
                 book=self._book().get('folder') or '',
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
        if v.get('turn_limit') is not None and hasattr(self, 'turn_limit'):
            self._turn_limit_all = False
            self.turn_limit.setMaximum(max(self.turn_limit.maximum(), int(v['turn_limit'])))
            self.turn_limit.setValue(int(v['turn_limit']))
        elif hasattr(self, 'turn_limit'):
            self._turn_limit_all = True
        if isinstance(v.get('cam'), dict):
            self._set_cam(v['cam'])
        self._set_transform(v.get('transform'))
        for key, box in (('mov', self.mov), ('webm', self.webm), ('keep_png', self.keep_png),
                         ('start_closed', self.start_closed), ('hand', self.hand_turns),
                         ('hand_left', self.hand_left)):
            if key in v:
                box.setChecked(bool(v[key]))
        for combo, key in ((self.hand_skin, 'hand_skin'), (self.hand_sleeve, 'hand_sleeve')):
            val = v.get(key) or ''
            if val and val != 'book-leather' and not Path(val).exists():
                val = ''
            self._hand_set(combo, val)
        if 'hand_size' in v:
            self.hand_size.setValue(int(v['hand_size']))
        for combo, key, default in ((self.page_shape, 'page_shape', 'flat'), (self.turn_style, 'turn_style', 'natural'),
                                    (self.hand_left_style, 'hand_left_style', 'on')):
            j = combo.findData(v.get(key, default))
            if j >= 0:
                combo.setCurrentIndex(j)
        i = self.mov_size.findData(v.get('mov_size', 'small'))
        if i >= 0:
            self.mov_size.setCurrentIndex(i)
        if v.get('book'):
            self._reload_books(v['book'])
        return self._set_pages(v.get('pages', []))

    # --------------------------------------------------------------- camera
    def _cam(self):
        return dict(tilt=float(self.tilt.value()), turn=float(self.turn.value()), roll=float(self.roll.value()),
                    lens=float(self.lens.value()), zoom=self.zoom.value() / 100,
                    shift_x=self.shift_x.value() / 100, shift_y=self.shift_y.value() / 100,
                    move=cf.MOVES[self.move.currentText()],
                    zoom_mode=self.zoom_mode.currentData() if hasattr(self, 'zoom_mode') else 'lens')

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
        if hasattr(self, 'zoom_mode'):
            i = self.zoom_mode.findData(c.get('zoom_mode', 'lens'))
            self.zoom_mode.blockSignals(True)
            self.zoom_mode.setCurrentIndex(max(0, i))
            self.zoom_mode.blockSignals(False)
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

    MY_CAM = '★ '

    def _my_cameras(self):
        try:
            data = json.loads(self.settings.value('my_cameras', '{}') or '{}')
            return data if isinstance(data, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _add_my_cameras(self, select=None):
        self.shot.blockSignals(True)
        current = select or self.shot.currentText()
        for i in range(self.shot.count() - 1, -1, -1):
            if self.shot.itemText(i).startswith(self.MY_CAM):
                self.shot.removeItem(i)
        for name in sorted(self._my_cameras()):
            self.shot.addItem(self.MY_CAM + name)
        if self.shot.findText(current) >= 0:
            self.shot.setCurrentText(current)
        self.shot.blockSignals(False)
        if hasattr(self, 'del_cam'):
            self.del_cam.setEnabled(self.shot.currentText().startswith(self.MY_CAM))

    def _save_my_camera(self):
        name, ok = QInputDialog.getText(self, 'Save my camera', 'Name for this camera:',
                                        text=self.shot.currentText().removeprefix(self.MY_CAM))
        name = (name or '').strip()
        if not ok or not name:
            return
        cams = self._my_cameras()
        cams[name] = self._cam()
        self.settings.setValue('my_cameras', json.dumps(cams))
        self._add_my_cameras(select=self.MY_CAM + name)
        self.status.setText(f'Saved camera "{name}". Pick it in "Start from" for any book.')

    def _delete_my_camera(self):
        name = self.shot.currentText()
        if not name.startswith(self.MY_CAM):
            return
        cams = self._my_cameras()
        cams.pop(name[len(self.MY_CAM):], None)
        self.settings.setValue('my_cameras', json.dumps(cams))
        self._add_my_cameras(select=next(iter(cf.PRESETS)))

    def _true_shape(self, on):
        if self.live is not None:
            self.live.true_shape = bool(on)
            self.live.update()
        if on:
            cm = self._book().get('page_size_cm') if self.books else None
            size = f' (page {float(cm[0]):g} × {float(cm[1]):g} cm)' if cm else ''
            self.status.setText(f'True shape: the book seen flat from straight above{size}. '
                                'The video still uses your camera - press again to go back.')
            self._show_view(0)

    def _apply_preset(self, name):
        if hasattr(self, 'del_cam'):
            self.del_cam.setEnabled(name.startswith(self.MY_CAM))
        if name.startswith(self.MY_CAM):
            cam = self._my_cameras().get(name[len(self.MY_CAM):])
            if cam:
                self._set_cam(cam)
        elif name in cf.PRESETS:
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

        Selects the Leather Journal template, sets its own sheet count and aspect,
        and clears page artwork so the new project starts clean. Saved projects and the
        user's own templates are untouched - nothing is written to disk here.
        """
        def find():
            for i, b in enumerate(self.books):
                if Path(b.get('folder') or '').name == 'leather-journal':
                    return i
            for i, b in enumerate(self.books):
                if b.get('engine') == 'journal':
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
                'The "Leather Journal" template is not installed.\n'
                'Reinstall MotionCraft, or check your books folder.')
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
        self._timeline_hand_edited = False
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
                                              'MotionCraft project (*.hmproj)')
        if path:
            Path(path).write_text(json.dumps(self._state(), indent=2), encoding='utf-8')
            self.settings.setValue('proj_dir', str(Path(path).parent))
            self.status.setText(f'Project saved: {path}')

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open project', self.settings.value('proj_dir', ''),
                                              'MotionCraft project (*.hmproj)')
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
        self._sync_timeline()
        v = self._values()
        clips = [clip_from_dict(d) for d in (self.edited_clips or [])]
        if clips:
            # what actually plays: the timeline clips (the same list the preview and render use)
            frames = max(c.start + c.duration for c in clips) + round(v['end_hold'] * v['fps'])
            turns = sum(1 for c in clips if c.kind == 'turn')
        else:
            tl = self._timeline(v)
            frames, turns = tl.frames, tl.turns
        self.summary.setText(f'Video length: {frames / v["fps"]:.1f} s  ·  {frames} frames  ·  {turns} turn(s)')
        self._schedule_live()

    def _sync_timeline(self):
        """Keep the timeline in step with the pages: one turn clip per two pages.

        Untouched timelines are rebuilt from the timing settings. A timeline edited by hand keeps
        its clips; turn clips are only added at the end (or removed from the end) to match."""
        if not self.books or not hasattr(self, 'timeline_panel'):
            return
        turns = self._video_turns()
        if not self._timeline_hand_edited:
            self._init_timeline()
            return
        clips = [clip_from_dict(d) for d in (self.edited_clips or [])]
        turn_clips = [c for c in clips if c.kind == 'turn']
        if len(turn_clips) == turns:
            return
        v = self._values()
        if len(turn_clips) > turns:
            extra = turn_clips[turns:]
            clips = [c for c in clips if not any(c is e for e in extra)]
        else:
            length = max(2, round(v['turn_seconds'] * v['fps']))
            gap = round(v['pause'] * v['fps'])
            end = max((c.start + c.duration for c in clips), default=round(v['start_hold'] * v['fps']))
            for _ in range(turns - len(turn_clips)):
                clips.append(Clip('turn', end + gap, length, smoothness=v['smoothness']))
                end = end + gap + length
        self.edited_clips = [clip_to_dict(c) for c in clips]
        self.timeline_panel.set_clips(clips)

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
        self._schedule_hands()

    # ------------------------------------------------------------ hands in the live view
    def _schedule_hands(self):
        """The hands' movement depends on the timing, pages and hand options: work it out again
        (in Blender, in the background) a moment after the last change."""
        if not hasattr(self, '_hand_timer'):
            self._hand_timer = QTimer(self)
            self._hand_timer.setSingleShot(True)
            self._hand_timer.timeout.connect(self._update_hands)
        self._hand_timer.start(900)

    def _update_hands(self):
        live = getattr(self, 'live', None)
        if live is None or not hasattr(live, 'set_hands'):
            return
        book = self._book() if self.books else {}
        if not self.hand_turns.isChecked() or book.get('engine') != 'journal' or not self.blender:
            live.set_hands(None)
            return
        try:
            job = self._job(self._values(), paths.cache_dir('hand_bake'), quality='draft')
        except Exception as exc:
            self.status.setText(f'The hands could not be shown in the live view: {exc}')
            return
        key = bb.hand_bake_key(job)
        folder = paths.cache_dir('hand_bake') / key
        out = folder / 'hands.npz'
        if out.exists():
            live.set_hands(str(out))
            return
        worker = getattr(self, '_hand_worker', None)
        if worker is not None and worker.isRunning():
            self._hands_pending = True             # once this one is done, the newest settings
            return
        folder.mkdir(parents=True, exist_ok=True)
        job['hand_bake_out'] = str(out)
        job['out_dir'] = str(folder)
        job_path = folder / 'job.json'
        job_path.write_text(json.dumps(job, indent=2), encoding='utf-8')
        self._hands_pending = False
        self._hand_worker = HandBakeWorker(self.blender, str(job_path), str(out))
        self._hand_worker.finished_ok.connect(self._hands_ready)
        self._hand_worker.failed.connect(self._hands_failed)
        self._hand_worker.start()
        self.status.setText('Working out the hands\' movement for the live view…')

    def _hands_ready(self, path):
        if getattr(self, '_hands_pending', False):
            self._update_hands()
            return
        if self.hand_turns.isChecked():
            self.live.set_hands(path)
        self.status.setText('Hands ready in the live view.')
        self._prune_hand_bakes()

    def _hands_failed(self, msg):
        self.status.setText(msg)
        if getattr(self, '_hands_pending', False):
            self._update_hands()

    def _prune_hand_bakes(self, keep=6):
        """Keep the few most recent hand bakes (each is a couple of megabytes)."""
        try:
            dirs = sorted((d for d in paths.cache_dir('hand_bake').iterdir() if d.is_dir()),
                          key=lambda d: d.stat().st_mtime, reverse=True)
            for d in dirs[keep:]:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass

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
        turns = self._video_turns()
        open_sec = v['open_seconds'] if v['start_closed'] else 0.0
        tl = ClipTimeline(turns, v['fps'], v['start_hold'], v['turn_seconds'], v['pause'],
                          v['end_hold'], open_sec, smoothness=v['smoothness'])
        self.timeline_panel.base_frames = max(2, round(v['turn_seconds'] * v['fps']))
        self.edited_clips = [clip_to_dict(c) for c in tl.clips]
        self.timeline_panel.set_clips(tl.clips)

    def _timeline_changed(self):
        self._timeline_hand_edited = True
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
        self._update_where(frame)

    def _update_where(self, frame=None):
        """The page counter in the live view's corner, and the open pages marked in the page list."""
        if self.live is None:
            return
        if not hasattr(self, 'where_label'):
            self.where_label = QLabel(self.live)
            self.where_label.setStyleSheet('background: rgba(20,20,24,190); color: #f2d8a8; padding: 5px 10px;'
                                           'border-radius: 6px; font-weight: 600;')
            self.where_label.move(12, 12)
        text = self.live.where(frame) if self.show_where.isChecked() else ''
        self.where_label.setVisible(bool(text) and not self.live.true_shape)
        if text:
            self.where_label.setText(text)
            self.where_label.adjustSize()
        if hasattr(self, 'spreads') and text and not self.spreads.hasFocus():
            import re
            m = re.search(r'pages? (\d+)[–-](\d+)', text.lower())
            s = 0 if ('page 1' in text and 'Inside' in text) else (int(m.group(1)) // 2 if m else None)
            if s is not None and s < self.spreads.count() and self.spreads.currentRow() != s:
                self.spreads.blockSignals(True)
                self.spreads.setCurrentRow(s)
                self.spreads.blockSignals(False)

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
        workers = 2 if self.parallel.isChecked() else 1
        self.worker = RenderWorker(self.blender, job, encode_opts, workers=workers)
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
        opts = dict(mov=self.mov.isChecked(), webm=self.webm.isChecked(), keep_png=self.keep_png.isChecked(),
                    mov_size=self.mov_size.currentData() or 'small')
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


def apply_theme(app):
    """One fixed dark theme, so the app looks the same whatever Windows is set to."""
    from PySide6.QtGui import QPalette
    app.setStyle('Fusion')
    p = QPalette()
    for role, col in ((QPalette.ColorRole.Window, '#1f1f24'), (QPalette.ColorRole.WindowText, '#e6e6ec'),
                      (QPalette.ColorRole.Base, '#26262c'), (QPalette.ColorRole.AlternateBase, '#2c2c33'),
                      (QPalette.ColorRole.Text, '#e6e6ec'), (QPalette.ColorRole.Button, '#34343c'),
                      (QPalette.ColorRole.ButtonText, '#e8e8ee'), (QPalette.ColorRole.Highlight, '#b8772a'),
                      (QPalette.ColorRole.HighlightedText, '#ffffff'), (QPalette.ColorRole.ToolTipBase, '#2c2c33'),
                      (QPalette.ColorRole.ToolTipText, '#e6e6ec'), (QPalette.ColorRole.PlaceholderText, '#8a8a92')):
        p.setColor(role, QColor(col))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor('#6c6c74'))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor('#6c6c74'))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor('#6c6c74'))
    app.setPalette(p)


def main():
    # WebEngine and the OpenGL viewport can only coexist when they share GL contexts,
    # and this attribute must be set before the QApplication exists.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    # Software rendering keeps Chromium's GPU process from fighting the OpenGL viewport.
    os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    apply_theme(app)
    check = (paths.resource_dir() / 'assets' / 'check.svg').as_posix()
    app.setStyleSheet(
        'QCheckBox::indicator{width:15px;height:15px;border:1px solid #8a8a92;border-radius:3px;background:#2a2a30}'
        'QCheckBox::indicator:hover{border-color:#c0c0c8}'
        f'QCheckBox::indicator:checked{{background:#2f7de1;border-color:#2f7de1;image:url("{check}")}}')
    try:
        paths.remove_old_install()
    except Exception:
        pass
    w = Studio()
    w.resize(1440, 860)
    w.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()



