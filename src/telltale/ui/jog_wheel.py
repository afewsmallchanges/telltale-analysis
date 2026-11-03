# jog_wheel.py
# An on-screen jog dial for stepping frames by touch or mouse: drag it round
# like a real jog wheel. Clockwise = forward. Scrolling over it also works.
# How far to turn per frame is in File > Settings.

from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import settings
from .wheel import WheelStepper

FACE = QColor(58, 58, 64)
RIM = QColor(110, 110, 118)
KNOB = QColor(150, 150, 158)
ARROWS = QColor(160, 160, 168)


class JogWheel(QWidget):
    stepRequested = Signal(int)
    pressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(110, 120)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setToolTip("Turn to step frames — clockwise is forward.\n"
                        "Scrolling over the wheel works too.")
        self._knob_angle = -50.0          # where the finger dot is drawn (degrees)
        self._last: Optional[float] = None  # angle at the previous mouse move
        self._turned = 0.0                # degrees turned but not yet a whole frame
        self._wheel = WheelStepper()

    def sizeHint(self) -> QSize:
        return QSize(160, 170)

    # --- geometry -----------------------------------------------------------
    def _dial(self) -> tuple[QPointF, float]:
        # Centre and radius of the dial, leaving room above for the arrows.
        top_room = 22
        r = max(10.0, min(self.width(), self.height() - top_room) / 2 - 6)
        return QPointF(self.width() / 2, top_room + (self.height() - top_room) / 2), r

    def _angle_at(self, pos: QPointF) -> Optional[float]:
        c, r = self._dial()
        dx, dy = pos.x() - c.x(), pos.y() - c.y()
        if math.hypot(dx, dy) < r * 0.15:
            return None  # too close to the centre to tell direction reliably
        return math.degrees(math.atan2(dy, dx))  # screen y is down: + is clockwise

    # --- input --------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._last = self._angle_at(event.position())
            self._turned = 0.0
            self.pressed.emit()
        event.accept()

    def mouseMoveEvent(self, event):
        a = self._angle_at(event.position())
        if a is None:
            return
        if self._last is None:
            self._last = a
            return
        d = (a - self._last + 180) % 360 - 180  # shortest way round, -180..180
        self._last = a
        self._knob_angle += d
        self._turned += d
        per = max(1, settings.wheel.jog_degrees_per_frame)
        steps = int(self._turned / per)
        if steps:
            self._turned -= steps * per
            self.stepRequested.emit(steps)
        self.update()

    def mouseReleaseEvent(self, _event):
        self._last = None
        self._turned = 0.0

    def wheelEvent(self, event):
        n = self._wheel.steps(event)
        if n:
            self._knob_angle += n * max(1, settings.wheel.jog_degrees_per_frame)
            self.stepRequested.emit(n)
            self.update()
        event.accept()

    def spin(self, frames: int):
        # Turn to match frames moved by something else (playback, scrubbing).
        if frames:
            per = max(1, settings.wheel.jog_degrees_per_frame)
            self._knob_angle = (self._knob_angle + frames * per) % 360
            self.update()

    # --- drawing ------------------------------------------------------------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c, r = self._dial()

        # Curved double arrow above the dial
        arc_r = r + 9
        arc_rect = QRectF(c.x() - arc_r, c.y() - arc_r, 2 * arc_r, 2 * arc_r)
        p.setPen(QPen(ARROWS, 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        start, span = 40, 100  # degrees, Qt counts anticlockwise from 3 o'clock
        path = QPainterPath()
        path.arcMoveTo(arc_rect, start)
        path.arcTo(arc_rect, start, span)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ARROWS)
        for deg, direction in ((start, -1), (start + span, 1)):
            p.drawPolygon(_arrow_head(c, arc_r, deg, direction))

        # Dial face
        p.setPen(QPen(RIM, 2))
        p.setBrush(FACE)
        p.drawEllipse(c, r, r)

        # Finger dot
        a = math.radians(self._knob_angle)
        knob_c = QPointF(c.x() + math.cos(a) * r * 0.6, c.y() + math.sin(a) * r * 0.6)
        p.setPen(QPen(RIM.darker(130), 1.5))
        p.setBrush(KNOB)
        p.drawEllipse(knob_c, r * 0.17, r * 0.17)


def _arrow_head(c: QPointF, radius: float, qt_deg: float, direction: int) -> QPolygonF:
    # Small triangle at the end of the arc, pointing along it (outwards).
    a = math.radians(qt_deg)
    tip = QPointF(c.x() + math.cos(a) * radius, c.y() - math.sin(a) * radius)
    # Tangent to the circle (Qt angles go anticlockwise, screen y is down)
    tx, ty = -math.sin(a) * direction, -math.cos(a) * direction
    nx, ny = math.cos(a), -math.sin(a)  # outward normal
    size = 6.0
    back = QPointF(tip.x() - tx * size, tip.y() - ty * size)
    return QPolygonF([
        QPointF(tip.x() + tx * 2, tip.y() + ty * 2),
        QPointF(back.x() + nx * size * 0.6, back.y() + ny * size * 0.6),
        QPointF(back.x() - nx * size * 0.6, back.y() - ny * size * 0.6),
    ])
