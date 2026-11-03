# app.py
# Starts the app. Run with `telltale`, or `python -m telltale [clip]`.

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .ui.main_window import APP_TITLE, MainWindow
from .ui.theme import apply_dark_theme


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName(APP_TITLE)
    #app.setDesktopFileName("telltale") # uncomment when app package is produced.
    apply_dark_theme(app)
    win = MainWindow()
    win.show()
    files = [Path(a) for a in argv[1:] if not a.startswith("-")]
    if files:
        win.import_paths(files, play_after=True)
    return app.exec()
