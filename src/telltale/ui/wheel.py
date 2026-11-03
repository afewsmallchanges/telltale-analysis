# wheel.py
# Turning mouse-wheel / touchpad scrolling into frame steps, and the
# timeline slider that uses it.

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QWheelEvent
from PySide6.QtWidgets import QSlider

from .. import settings

NOTCH = 120  # Qt reports one mouse-wheel click as 120 units (fixed by Qt)


class WheelStepper:
    # Mouse wheels send 120 units per click; touchpads send many small pixel
    # deltas. Leftovers are kept so slow touchpad swipes still step.

    def __init__(self):
        self._acc = 0.0

    def steps(self, event: QWheelEvent) -> int:
        s = settings.wheel  # read every time, so changes apply immediately
        pixel = event.pixelDelta()
        angle = event.angleDelta()
        if not pixel.isNull():
            delta = (pixel.y() or pixel.x()) / s.touchpad_px_per_frame
        else:
            # Some systems turn Shift+wheel into horizontal scrolling.
            delta = (angle.y() or angle.x()) / NOTCH * s.frames_per_click
        if not s.up_is_forward:
            delta = -delta
        if self._acc and (delta > 0) != (self._acc > 0):
            self._acc = 0.0  # direction changed: drop the leftover
        self._acc += delta
        whole = int(self._acc)
        self._acc -= whole
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            whole *= s.shift_multiplier
        return whole


def slider_style(colour: str, thick: bool = False) -> str:
    # Coloured progress bar look: filled in `colour` up to the handle.
    groove = 10 if thick else 6
    handle = 22 if thick else 14
    margin = (handle - groove) // 2
    return f"""
        QSlider::groove:horizontal {{
            height: {groove}px; background: #3a3a40; border-radius: {groove // 2}px; }}
        QSlider::sub-page:horizontal {{
            background: {colour}; border-radius: {groove // 2}px; }}
        QSlider::handle:horizontal {{
            background: #f2f2f5; border: 1px solid #55555c;
            width: {handle}px; margin: -{margin}px 0; border-radius: {handle // 2}px; }}
        QSlider::sub-page:horizontal:disabled {{ background: #55555c; }}
    """


MARKER_FILL = QColor("#ff6a00")
MARKER_EDGE = QColor("#b34700")
FLAG_W, FLAG_H = 14, 14   # the marker's flag, above the bar


class TimelineSlider(QSlider):
    # Horizontal scrubber. Its scroll wheel steps frames like the picture.
    # Can show a draggable marker flag (the timer's zero).

    markerMoved = Signal(int)

    def __init__(self, on_steps: Callable[[int], None], colour: Optional[str] = None,
                 thick: bool = False, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._on_steps = on_steps
        self._wheel = WheelStepper()
        self._handle_px = 22 if thick else 14   # matches slider_style
        self.marker: Optional[int] = None
        self.marker_tip = ""
        self._bar_tip = ""
        self._dragging_marker = False
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setTracking(True)
        self.setMouseTracking(True)
        if colour:
            self.setStyleSheet(slider_style(colour, thick))
        if thick:
            self.setMinimumHeight(FLAG_H + 30)  # room for the marker flag above the bar

    # --- value <-> position ---------------------------------------------------
    def x_for(self, value: int) -> float:
        lo, hi = self.minimum(), self.maximum()
        half = self._handle_px / 2
        if hi <= lo:
            return half
        return half + (value - lo) * (self.width() - self._handle_px) / (hi - lo)

    def value_at(self, x: float) -> int:
        lo, hi = self.minimum(), self.maximum()
        span = max(1, self.width() - self._handle_px)
        v = lo + (x - self._handle_px / 2) * (hi - lo) / span
        return max(lo, min(hi, round(v)))

    # --- marker -----------------------------------------------------------------
    def set_marker(self, value: Optional[int], tip: str = ""):
        # Show the flag at `value` (None hides it).
        if value is not None and not (self.minimum() <= value <= self.maximum()):
            value = None  # outside the clips
        self.marker = value
        self.marker_tip = tip
        self.update()

    def _on_flag(self, x: float, y: float) -> bool:
        if self.marker is None:
            return False
        return abs(x - self.x_for(self.marker)) <= FLAG_W / 2 + 3 and y <= FLAG_H + 4

    # --- mouse --------------------------------------------------------------------
    def wheelEvent(self, event: QWheelEvent):
        n = self._wheel.steps(event)
        if n:
            self._on_steps(n)
        event.accept()

    def mousePressEvent(self, event):
        x, y = event.position().x(), event.position().y()
        if event.button() == Qt.MouseButton.LeftButton and self._on_flag(x, y):
            self._dragging_marker = True
            event.accept()
            return
        # Jump straight to the clicked point instead of paging.
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > self.minimum():
            self.setValue(self.value_at(x))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        x, y = event.position().x(), event.position().y()
        if self._dragging_marker:
            v = self.value_at(x)
            if v != self.marker:
                self.marker = v
                self.update()
                self.markerMoved.emit(v)
            event.accept()
            return
        tip = self.marker_tip if self._on_flag(x, y) else self._bar_tip
        if tip != self.toolTip():
            self.setToolTip(tip)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging_marker:
            self._dragging_marker = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def set_bar_tip(self, text: str):
        self._bar_tip = text
        self.setToolTip(text)

    # --- drawing --------------------------------------------------------------
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.marker is None:
            return
        x = self.x_for(self.marker)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(MARKER_FILL, 2))
        p.drawLine(QPointF(x, FLAG_H - 2), QPointF(x, self.height() / 2 + 8))
        p.setPen(QPen(MARKER_EDGE, 1.5))
        p.setBrush(MARKER_FILL)
        h = FLAG_W / 2
        p.drawPolygon(QPolygonF([QPointF(x - h, 1), QPointF(x + h, 1), QPointF(x + h, FLAG_H * 0.55),
                                 QPointF(x, FLAG_H), QPointF(x - h, FLAG_H * 0.55)]))
        p.end()
