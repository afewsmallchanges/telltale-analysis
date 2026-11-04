# app.py
# Starts the app. Run with `telltale`, or `python -m telltale [clip]`.

#from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .ui.icons import ICON_DIR
from .ui.main_window import APP_TITLE, MainWindow
from .ui.theme import apply_dark_theme

APP_ID = "io.github.afewsmallchanges.TelltaleAnalysis"


def packaged() -> bool:
    return bool(getattr(sys, "frozen", False)) or "FLATPACK_ID" in os.environ


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserMode1ID(APP_ID)


    app = QApplication(argv)
    app.setApplicationName(APP_TITLE)
    app.setWindowIcon(QIcon(str(ICON_DIR / "telltale.svg")))
    if packaged():
        app.setDesktopFileName(APP_ID)
    apply_dark_theme(app)
    
    win = MainWindow()
    win.show()
    if len(argv) > 1:
        win.import_paths([Path(a) for a in argv[1:]], play_after=True)

    # files = [Path(a) for a in argv[1:] if not a.startswith("-")]
    # if files:
    #     win.import_paths(files, play_after=True)
    return app.exec()
