# import_worker.py
# Imports one or more videos into the library on a background thread, so the
# window stays responsive. Already-imported videos finish instantly.

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.library import ImportCancelled, Library


class ImportWorker(QThread):
    progress = Signal(float, str)   # overall 0.0-1.0, label e.g. "2 of 5: start.mp4"
    clipReady = Signal(object)      # ClipInfo, once per video imported
    clipFailed = Signal(str, str)   # file name, error message
    cancelled = Signal()

    def __init__(self, library: Library, paths: list[Path], parent=None):
        super().__init__(parent)
        self.library = library
        self.paths = list(paths)
        self.cancel_event = threading.Event()

    def run(self):
        total = len(self.paths)
        for i, path in enumerate(self.paths):
            if self.cancel_event.is_set():
                self.cancelled.emit()
                return
            label = f"{i + 1} of {total}: {path.name}" if total > 1 else path.name

            def report(f, i=i, label=label):
                self.progress.emit((i + f) / total, label)

            report(0.0)
            try:
                info = self.library.import_clip(path, report, self.cancel_event)
            except ImportCancelled:
                self.cancelled.emit()
                return
            except Exception as e:  # report and carry on with the next file
                self.clipFailed.emit(path.name, str(e))
            else:
                self.clipReady.emit(info)
