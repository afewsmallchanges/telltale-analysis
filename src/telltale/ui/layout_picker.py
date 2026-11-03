# layout_picker.py
# The split button's pop-up: a small grid to pick rows × columns, like
# choosing a table size in a word processor. Up to 4 views in total, so
# shapes like 1×2, 2×1 (stacked), 1×4, 4×1 and 2×2 can all be picked.

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core.projects import MAX_CLIPS_PER_SCENE

GRID = 4          # 4 × 4 cells shown
CELL = 26
GAP = 4
PAD = 10
LABEL_H = 26

FREE = QColor(58, 58, 64)
BLOCKED = QColor(36, 36, 40)
LIT = QColor(122, 44, 240)
CURRENT = QColor(242, 242, 245)


class LayoutPicker(QWidget):
    chosen = Signal(int, int)   # rows, columns

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.current = (1, 1)                     # layout in use (outlined)
        self.hover: Optional[tuple[int, int]] = None

    def sizeHint(self) -> QSize:
        side = PAD * 2 + GRID * CELL + (GRID - 1) * GAP
        return QSize(side, side + LABEL_H)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_current(self, rows: int, cols: int):
        self.current = (rows, cols)
        self.hover = None
        self.update()

    @staticmethod
    def allowed(rows: int, cols: int) -> bool:
        return 1 <= rows and 1 <= cols and rows * cols <= MAX_CLIPS_PER_SCENE

    def _cell_rect(self, r: int, c: int) -> QRectF:
        return QRectF(PAD + c * (CELL + GAP), PAD + r * (CELL + GAP), CELL, CELL)

    def cell_at(self, x: float, y: float) -> Optional[tuple[int, int]]:
        # The (rows, cols) picked by pointing at x, y; None outside the grid.
        c = int((x - PAD) // (CELL + GAP))
        r = int((y - PAD) // (CELL + GAP))
        if 0 <= r < GRID and 0 <= c < GRID:
            return r + 1, c + 1
        return None

    def mouseMoveEvent(self, event):
        cell = self.cell_at(event.position().x(), event.position().y())
        self.hover = cell if cell and self.allowed(*cell) else None
        self.update()

    def leaveEvent(self, _event):
        self.hover = None
        self.update()

    def mouseReleaseEvent(self, event):
        cell = self.cell_at(event.position().x(), event.position().y())
        if cell and self.allowed(*cell):
            self.chosen.emit(*cell)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shown = self.hover or self.current
        for r in range(GRID):
            for c in range(GRID):
                rect = self._cell_rect(r, c)
                if not self.allowed(r + 1, c + 1):
                    colour = BLOCKED
                elif r < shown[0] and c < shown[1]:
                    colour = LIT
                else:
                    colour = FREE
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(colour)
                p.drawRoundedRect(rect, 4, 4)
                if self.hover is None and r < self.current[0] and c < self.current[1]:
                    p.setPen(QPen(CURRENT, 1.5))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)
        rows, cols = shown
        n = rows * cols
        label = f"{rows} × {cols}  ·  {n} view{'' if n == 1 else 's'}"
        p.setPen(QColor(220, 220, 226))
        p.drawText(QRectF(0, self.height() - LABEL_H, self.width(), LABEL_H - 4),
                   Qt.AlignmentFlag.AlignCenter, label)
