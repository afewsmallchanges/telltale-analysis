# main_window.py
# The main window: opening/importing clips, menus and keyboard shortcuts.

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
)

from ..core import timebase
from ..core.clip import ClipInfo
from ..core.frames import FrameSource
from ..core.library import ImportCancelled, Library
from .player import PlayerWidget

APP_TITLE = "Telltale Analysis"

VIDEO_FILTER = "Video files (*.mp4 *.mov *.mkv *.avi *.mts *.m2ts *.ts *.webm *.mxf);;All files (*)"


class ImportWorker(QThread):
    # Runs Library.import_clip off the UI thread.

    progress = Signal(float)
    finished_ok = Signal(object)  # ClipInfo
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, library: Library, path: Path, parent=None):
        super().__init__(parent)
        self.library = library
        self.path = path
        self.cancel_event = threading.Event()

    def run(self):
        try:
            info = self.library.import_clip(self.path, self.progress.emit, self.cancel_event)
        except ImportCancelled:
            self.cancelled.emit()
        except Exception as e:  # report anything to the user rather than crash
            self.failed.emit(str(e))
        else:
            self.finished_ok.emit(info)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        self.library = Library()
        self.player = PlayerWidget()
        self.setCentralWidget(self.player)
        self._worker: ImportWorker | None = None
        self._progress: QProgressDialog | None = None

        file_menu = self.menuBar().addMenu("&File")
        open_act = QAction("&Open clip…", self, shortcut=QKeySequence(QKeySequence.StandardKey.Open))
        open_act.triggered.connect(self.open_dialog)
        file_menu.addAction(open_act)
        file_menu.addSeparator()
        quit_act = QAction("&Quit", self, shortcut=QKeySequence(QKeySequence.StandardKey.Quit))
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        #edit_menu = self.menuBar().addMenu("&Edit")

        #view_menu = self.menuBar().addMenu("&View")

        settings_menu = self.menuBar().addMenu("&Settings")
        scroll_act = QAction("&Scroll && touchpad…", self, shortcut=QKeySequence("Ctrl+,"))
        scroll_act.triggered.connect(self.open_scroll_settings)
        settings_menu.addAction(scroll_act)

        p = self.player
        keys = {
            "Space": p.toggle_play,
            "Left": lambda: p.step(-1),
            "Right": lambda: p.step(1),
            ",": lambda: p.step(-1),
            ".": lambda: p.step(1),
            "Shift+Left": lambda: p.step(-10),
            "Shift+Right": lambda: p.step(10),
            "Home": lambda: p.seek(0),
            "End": lambda: p.seek(10**9),
            "F": self.toggle_fullscreen,
            "Escape": self.leave_fullscreen,
        }
        for seq, slot in keys.items():
            QShortcut(QKeySequence(seq), self, activated=slot)

        self.statusBar().showMessage("Open a clip to start.")

    # --- opening clips -----------------------------------------------------
    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open clip", str(Path.home()), VIDEO_FILTER)
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path):
        if self._worker is not None:
            return  # an import is already running
        self.player.pause()

        self._progress = QProgressDialog(f"Preparing {path.name} for frame stepping…",
                                         "Cancel", 0, 1000, self)
        self._progress.setWindowTitle("Importing clip")
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(400)  # instant for already-imported clips
        self._progress.setValue(0)

        worker = ImportWorker(self.library, path, self)
        worker.progress.connect(lambda f: self._progress and self._progress.setValue(int(f * 1000)))
        worker.finished_ok.connect(self._import_done)
        worker.failed.connect(self._import_failed)
        worker.cancelled.connect(lambda: self.statusBar().showMessage("Import cancelled."))
        worker.finished.connect(self._worker_finished)
        self._progress.canceled.connect(worker.cancel_event.set)
        self._worker = worker
        worker.start()

    def _import_done(self, info: ClipInfo):
        self.player.load(FrameSource(info))
        self.setWindowTitle(f"{info.name} — {APP_TITLE}")
        sound = "" if info.has_audio else "   no audio"
        self.statusBar().showMessage(
            f"{info.name}   {info.width}×{info.height}   "
            f"{timebase.format_rate(info.rate)} fps   {info.frame_count} frames{sound}"
        )

    def _import_failed(self, message: str):
        QMessageBox.critical(self, "Could not open clip", message)

    def _worker_finished(self):
        if self._progress:
            self._progress.reset()
            self._progress.deleteLater()
            self._progress = None
        if self._worker:
            self._worker.deleteLater()
            self._worker = None

    # added with addition of settings menu
    def open_scroll_settings(self):
        from .settings_dialog import ScrollSettingsDialog
        self.player.pause()
        ScrollSettingsDialog(self).exec()

    # --- drag and drop -----------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = [u for u in event.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.open_path(Path(urls[0].toLocalFile()))

    # --- window ------------------------------------------------------------
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.leave_fullscreen()
        else:
            self.menuBar().hide()
            self.statusBar().hide()
            self.showFullScreen()

    def leave_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.menuBar().show()
            self.statusBar().show()

    def closeEvent(self, event):
        if self._worker is not None:
            self._worker.cancel_event.set()
            self._worker.wait(5000)
        super().closeEvent(event)
