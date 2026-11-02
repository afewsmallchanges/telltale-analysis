"""User settings, saved between sessions.

Stored in ~/.config/replaydesk/replaydesk.conf (a plain text INI file).
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

from PySide6.QtCore import QSettings


def _store() -> QSettings:
    return QSettings("video_review", "video_review")


@dataclass
class WheelSettings:
    up_is_forward: bool = True        # scroll up / swipe up = next frame
    frames_per_click: int = 1         # mouse wheel: frames per wheel click
    touchpad_px_per_frame: int = 12   # touchpad: pixels of swipe per frame
    shift_multiplier: int = 10        # Shift + scroll multiplies steps by this

    GROUP = "wheel"

    @classmethod
    def load(cls) -> "WheelSettings":
        s = _store()
        s.beginGroup(cls.GROUP)
        defaults = cls()
        values = {f.name: s.value(f.name, getattr(defaults, f.name), type=type(getattr(defaults, f.name)))
                  for f in fields(cls)}
        s.endGroup()
        return cls(**values)

    def save(self):
        s = _store()
        s.beginGroup(self.GROUP)
        for f in fields(self):
            s.setValue(f.name, getattr(self, f.name))
        s.endGroup()
        s.sync()

    def copy(self) -> "WheelSettings":
        return replace(self)

    def update_from(self, other: "WheelSettings"):
        """Change this object in place, so everyone holding it sees the change."""
        for f in fields(self):
            setattr(self, f.name, getattr(other, f.name))


# The one shared instance the app reads from.
wheel = WheelSettings.load()