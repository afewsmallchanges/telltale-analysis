#!/usr/bin/env bash
# build-appimage.sh
# Builds dist/Telltale_Analysis-<version>-x86_64.AppImage.
#
# Run from anywhere inside the repo, ideally in an Ubuntu 22.04 container
# (see packaging/PACKAGING.md): an AppImage only runs on systems at least as
# new as the one it was built on, so building on an older base makes it work
# on more distros.

set -euo pipefail
cd "$(dirname "$0")/../.."

APP_ID=io.github.afewsmallchanges.TelltaleAnalysis
APPDIR=build/AppDir

# 1. A clean virtual environment with the app and PyInstaller
python3 -m venv .build-venv
# shellcheck disable=SC1091
. .build-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install . pyinstaller

# The installed app's version, wherever pyproject.toml gets it from
VERSION=$(python -c "from importlib.metadata import version; print(version('telltale-analysis'))")
OUT="dist/Telltale_Analysis-${VERSION}-x86_64.AppImage"
echo "==> Building Telltale Analysis ${VERSION}"

# 2. Bundle Python, Qt, OpenCV and FFmpeg into dist/telltale/
rm -rf build/telltale dist/telltale "$APPDIR"
pyinstaller --noconfirm --distpath dist --workpath build packaging/telltale.spec
chmod +x dist/telltale/_internal/imageio_ffmpeg/binaries/* 2>/dev/null || true

# 3. Lay out the AppDir
mkdir -p "$APPDIR/usr/lib" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/metainfo" \
         "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a dist/telltale "$APPDIR/usr/lib/telltale"
install -m755 packaging/appimage/AppRun "$APPDIR/AppRun"
install -m644 "packaging/appimage/$APP_ID.desktop" "$APPDIR/$APP_ID.desktop"
install -m644 "packaging/appimage/$APP_ID.desktop" "$APPDIR/usr/share/applications/$APP_ID.desktop"
install -m644 "packaging/appimage/$APP_ID.metainfo.xml" "$APPDIR/usr/share/metainfo/$APP_ID.metainfo.xml"
install -m644 packaging/icons/telltale.svg "$APPDIR/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"
install -m644 packaging/icons/telltale-256.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/$APP_ID.png"
install -m644 packaging/icons/telltale-256.png "$APPDIR/$APP_ID.png"
ln -sf "$APP_ID.png" "$APPDIR/.DirIcon"

# 4. Pack it with appimagetool (downloaded once into build/)
TOOL=build/appimagetool-x86_64.AppImage
if [ ! -x "$TOOL" ]; then
    wget -q -O "$TOOL" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi
# APPIMAGE_EXTRACT_AND_RUN lets appimagetool run without FUSE (e.g. in containers)
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$OUT"

echo "==> Done: $OUT"
