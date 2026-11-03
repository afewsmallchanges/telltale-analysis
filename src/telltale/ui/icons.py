# icons.py
# Loads the SVG icons in ui/icons/. Edit the SVGs to restyle buttons.

from pathlib import Path

from PySide6.QtGui import QIcon

ICON_DIR = Path(__file__).parent / "icons"
ICON_PX = 24


def icon(name: str) -> QIcon:
    return QIcon(str(ICON_DIR / f"{name}.svg"))
