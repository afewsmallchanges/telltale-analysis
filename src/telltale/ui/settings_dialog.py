"""Settings dialog for scroll wheel and touchpad frame stepping."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import settings
from .wheel import WheelStepper


class ScrollTestPad(QWidget):
    """Scroll or swipe here to try the current settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = 0
        self._wheel = WheelStepper()
        self.setMinimumHeight(110)

    def wheelEvent(self, event):
        self.frame += self._wheel.steps(event)
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, _event):
        self.frame = 0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(10, 10, 12))
        p.setPen(QColor(90, 90, 95))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.setPen(QColor(150, 150, 155))
        p.drawText(self.rect().adjusted(0, 8, 0, 0),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   "Scroll or swipe here to try it  (double-click to reset)")
        f = QFont(self.font())
        f.setPointSize(f.pointSize() + 14)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(230, 230, 235))
        p.drawText(self.rect().adjusted(0, 20, 0, 0), Qt.AlignmentFlag.AlignCenter,
                   f"frame {self.frame:+d}")


class SettingsDialog(QDialog):
    """Changes apply live (so the test pad uses them); Cancel puts them back."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(460)
        self._original = settings.wheel.copy()
        w = settings.wheel

        self.direction = QComboBox()
        self.direction.addItem("Next frame", True)
        self.direction.addItem("Previous frame", False)
        self.direction.setCurrentIndex(0 if w.up_is_forward else 1)

        self.per_click = QSpinBox()
        self.per_click.setRange(1, 50)
        self.per_click.setSuffix(" frame(s)")
        self.per_click.setValue(w.frames_per_click)

        self.touchpad = QSpinBox()
        self.touchpad.setRange(1, 200)
        self.touchpad.setSuffix(" px per frame")
        self.touchpad.setValue(w.touchpad_px_per_frame)
        self.touchpad.setToolTip("Higher = slower, finer control on a touchpad")

        self.shift = QSpinBox()
        self.shift.setRange(1, 250)
        self.shift.setPrefix("× ")
        self.shift.setValue(w.shift_multiplier)

        self.jog = QSpinBox()
        self.jog.setRange(2, 90)
        self.jog.setSuffix("° per frame")
        self.jog.setValue(w.jog_degrees_per_frame)
        self.jog.setToolTip("How far to turn the on-screen jog wheel for one frame. "
                            "Smaller = faster.")

        form = QFormLayout()
        form.addRow("Scroll up goes to:", self.direction)
        form.addRow("Mouse wheel, one click:", self.per_click)
        form.addRow("Touchpad sensitivity:", self.touchpad)
        form.addRow("Holding Shift multiplies by:", self.shift)
        form.addRow("Jog wheel:", self.jog)

        note = QLabel("If the touchpad setting has no effect, your system is reporting the "
                      "touchpad as a mouse wheel (common on X11). Use the mouse wheel "
                      "setting instead.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            self._restore_defaults)

        # One tab per group of settings; add new tabs here as the app grows.
        scroll_tab = QWidget()
        scroll_layout = QVBoxLayout(scroll_tab)
        scroll_layout.addLayout(form)
        scroll_layout.addWidget(ScrollTestPad())
        scroll_layout.addWidget(note)

        # Drawing tab
        d = settings.drawing
        self._original_drawing = d.copy()
        self.hold = QDoubleSpinBox()
        self.hold.setRange(0.0, 10.0)
        self.hold.setSingleStep(0.1)
        self.hold.setDecimals(1)
        self.hold.setSuffix(" s either side")
        self.hold.setValue(d.hold_seconds)
        self.hold.setToolTip("How long a Hold drawing stays on screen before and after "
                             "the frame it was drawn on. 0 = that frame only.")
        self.thickness = QSpinBox()
        self.thickness.setRange(2, 30)
        self.thickness.setSuffix(" px")
        self.thickness.setValue(d.line_width)
        self.thickness.setToolTip("Line thickness for new drawings, as it looks when you draw")
        draw_form = QFormLayout()
        draw_form.addRow("Hold drawings for:", self.hold)
        draw_form.addRow("Line thickness:", self.thickness)
        draw_tab = QWidget()
        draw_layout = QVBoxLayout(draw_tab)
        draw_layout.addLayout(draw_form)
        draw_layout.addStretch()

        tabs = QTabWidget()
        tabs.addTab(scroll_tab, "Scroll && jog wheel")
        tabs.addTab(draw_tab, "Drawing")

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

        self.direction.currentIndexChanged.connect(self._apply_live)
        for box in (self.per_click, self.touchpad, self.shift, self.jog):
            box.valueChanged.connect(self._apply_live)

    def _current(self) -> settings.WheelSettings:
        return settings.WheelSettings(
            up_is_forward=bool(self.direction.currentData()),
            frames_per_click=self.per_click.value(),
            touchpad_px_per_frame=self.touchpad.value(),
            shift_multiplier=self.shift.value(),
            jog_degrees_per_frame=self.jog.value(),
        )

    def _apply_live(self, *_):
        settings.wheel.update_from(self._current())

    def _restore_defaults(self):
        d = settings.WheelSettings()
        self.direction.setCurrentIndex(0 if d.up_is_forward else 1)
        self.per_click.setValue(d.frames_per_click)
        self.touchpad.setValue(d.touchpad_px_per_frame)
        self.shift.setValue(d.shift_multiplier)
        self.jog.setValue(d.jog_degrees_per_frame)
        self.hold.setValue(settings.DrawingSettings().hold_seconds)
        self.thickness.setValue(settings.DrawingSettings().line_width)

    def accept(self):
        self._apply_live()
        settings.wheel.save()
        settings.drawing.hold_seconds = round(self.hold.value(), 1)
        settings.drawing.line_width = self.thickness.value()
        settings.drawing.save()
        super().accept()

    def reject(self):
        settings.wheel.update_from(self._original)
        settings.drawing.update_from(self._original_drawing)
        super().reject()
