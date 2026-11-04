# telltale.spec
# PyInstaller recipe for Telltale Analysis, used for the AppImage and the
# Windows installer. It produces a folder, dist/telltale/, holding the
# `telltale` (or telltale.exe) program plus everything it needs.
#
# Run from the repo root, in a virtual environment with the app installed:
#   pip install . pyinstaller
#   pyinstaller --noconfirm packaging/telltale.spec

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

ROOT = Path(SPECPATH).parent          # SPECPATH = the folder this file is in
WINDOWS = sys.platform == "win32"

datas = []
datas += collect_data_files("telltale")         # ui/icons/*.svg
datas += collect_data_files("imageio_ffmpeg")   # the bundled FFmpeg program
datas += copy_metadata("telltale-analysis")     # lets Help → About show the version

binaries = []
if sys.platform.startswith("linux"):
    # Qt's native Wayland support. PyInstaller may already collect these;
    # adding them again is harmless. Without them the app still runs, via
    # XWayland.
    import PySide6

    plugins = Path(PySide6.__file__).parent / "Qt" / "plugins"
    for group in ("wayland-decoration-client", "wayland-graphics-integration-client",
                  "wayland-shell-integration"):
        for f in sorted((plugins / group).glob("*.so")):
            binaries.append((str(f), f"PySide6/Qt/plugins/{group}"))

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=["PySide6.QtSvg"],   # draws the SVG icons
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="telltale",
    console=False,                     # no terminal window on Windows
    icon=str(ROOT / "packaging" / "icons" / "telltale.ico") if WINDOWS else None,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="telltale",
    strip=False,
    upx=False,
)
