# paths.py
# Where Telltale keeps its data on each operating system.
#
#   Linux    ~/.local/share/telltale        (or $XDG_DATA_HOME/telltale)
#   macOS    ~/Library/Application Support/telltale
#   Windows  %LOCALAPPDATA%\telltale
#
# Set TELLTALE_DATA_DIR to use a different folder (the tests do this).

from __future__ import annotations

import os
import sys
from pathlib import Path

APP = "telltale"


def data_dir() -> Path:
    override = os.environ.get("TELLTALE_DATA_DIR")
    if override:
        d = Path(override)
    elif sys.platform == "win32":
        d = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP
    elif sys.platform == "darwin":
        d = Path.home() / "Library" / "Application Support" / APP
    else:
        d = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP
    d.mkdir(parents=True, exist_ok=True)
    return d


def library_dir() -> Path:
    d = data_dir() / "library"
    d.mkdir(parents=True, exist_ok=True)
    return d


def projects_dir() -> Path:
    d = data_dir() / "projects"
    d.mkdir(parents=True, exist_ok=True)
    return d
