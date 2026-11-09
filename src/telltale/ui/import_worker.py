# import_worker.py
# Imports one or more videos into the library on a background thread, so the
# window stays responsive. Already-imported videos finish instantly.
# LoadWorker does the same for loading an unloaded project's clips.

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.clip import ClipInfo
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


class LoadWorker(QThread):
    # Makes the frames of unloaded clips again from their original videos
    # (loading a project). Same signals as ImportWorker.
    progress = Signal(float, str)
    clipReady = Signal(object)      # ClipInfo, once per clip loaded
    clipFailed = Signal(str, str)   # clip name, error message
    cancelled = Signal()

    def __init__(self, library: Library, jobs: list[tuple[ClipInfo, Path]], parent=None):
        # `jobs`: (clip, its original video) for each clip to load.
        super().__init__(parent)
        self.library = library
        self.jobs = list(jobs)
        self.cancel_event = threading.Event()

    def run(self):
        total = len(self.jobs)
        for i, (clip, src) in enumerate(self.jobs):
            if self.cancel_event.is_set():
                self.cancelled.emit()
                return
            label = f"{i + 1} of {total}: {clip.name}" if total > 1 else clip.name

            def report(f, i=i, label=label):
                self.progress.emit((i + f) / total, label)

            report(0.0)
            try:
                info = self.library.reload_clip(clip.id, src, report, self.cancel_event)
            except ImportCancelled:
                self.cancelled.emit()
                return
            except Exception as e:  # report and carry on with the next clip
                self.clipFailed.emit(clip.name, str(e))
            else:
                self.clipReady.emit(info)
