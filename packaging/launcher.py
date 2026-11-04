# launcher.py
# Entry point for PyInstaller builds (AppImage and Windows).
# PyInstaller needs a plain script: telltale/__main__.py uses a relative
# import, which only works when run as `python -m telltale`.

import sys

from telltale.app import main

if __name__ == "__main__":
    sys.exit(main())
