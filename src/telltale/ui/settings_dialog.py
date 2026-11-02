"""Settings dialog for scroll wheel and touchpad frame stepping."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import settings
from .player import WheelStepper


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


class ScrollSettingsDialog(QDialog):
    """Changes apply live (so the test pad uses them); Cancel puts them back."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scroll & touchpad settings")
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

        form = QFormLayout()
        form.addRow("Scroll up goes to:", self.direction)
        form.addRow("Mouse wheel, one click:", self.per_click)
        form.addRow("Touchpad sensitivity:", self.touchpad)
        form.addRow("Holding Shift multiplies by:", self.shift)

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

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(ScrollTestPad())
        layout.addWidget(note)
        layout.addWidget(buttons)

        self.direction.currentIndexChanged.connect(self._apply_live)
        for box in (self.per_click, self.touchpad, self.shift):
            box.valueChanged.connect(self._apply_live)

    def _current(self) -> settings.WheelSettings:
        return settings.WheelSettings(
            up_is_forward=bool(self.direction.currentData()),
            frames_per_click=self.per_click.value(),
            touchpad_px_per_frame=self.touchpad.value(),
            shift_multiplier=self.shift.value(),
        )

    def _apply_live(self, *_):
        settings.wheel.update_from(self._current())

    def _restore_defaults(self):
        d = settings.WheelSettings()
        self.direction.setCurrentIndex(0 if d.up_is_forward else 1)
        self.per_click.setValue(d.frames_per_click)
        self.touchpad.setValue(d.touchpad_px_per_frame)
        self.shift.setValue(d.shift_multiplier)

    def accept(self):
        self._apply_live()
        settings.wheel.save()
        super().accept()

    def reject(self):
        settings.wheel.update_from(self._original)
        super().reject()
