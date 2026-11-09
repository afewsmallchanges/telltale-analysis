# picture_reader.py
# Reads pictures with Qt, for boards OpenCV can't open: SVG diagrams (drawn
# at a good size), and any other format Qt has a plug-in for. Used by the
# board import in core/boards.py as its `fallback` reader.

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPainter

SVG_LONG_SIDE = 2400   # pixels: SVGs are drawn this big on their longer side


def read_picture(path: Path) -> Optional[np.ndarray]:
    # The picture as an RGBA array (H × W × 4), or None if Qt can't read it.
    if Path(path).suffix.lower() == ".svg":
        image = _render_svg(Path(path))
    else:
        image = QImage(str(path))
    if image is None or image.isNull():
        return None
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h, stride = image.width(), image.height(), image.bytesPerLine()
    data = np.frombuffer(image.constBits(), dtype=np.uint8, count=image.sizeInBytes())
    return data.reshape(h, stride)[:, :w * 4].reshape(h, w, 4).copy()


def _render_svg(path: Path) -> Optional[QImage]:
    from PySide6.QtSvg import QSvgRenderer  # only needed for SVG files

    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return None
    size = renderer.defaultSize()
    if size.isEmpty():                     # only a viewBox, no width/height
        box = renderer.viewBoxF().size()
        size = QSize(round(box.width()), round(box.height())) if not box.isEmpty() else QSize(4, 3)
    scale = SVG_LONG_SIDE / max(size.width(), size.height())
    image = QImage(max(1, round(size.width() * scale)), max(1, round(size.height() * scale)),
                   QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)  # becomes white on import
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    return image
