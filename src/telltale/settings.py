"""User settings, saved between sessions.

Stored in ~/.config/telltale/telltale.conf (a plain text INI file).
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import ClassVar

from PySide6.QtCore import QSettings


def _store() -> QSettings:
    return QSettings("telltale", "telltale")


class _Group:
    # Load/save for a dataclass of settings stored under [GROUP] in the file.
    GROUP: ClassVar[str] = ""

    @classmethod
    def load(cls):
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

    def copy(self):
        return replace(self)

    def update_from(self, other):
        """Change this object in place, so everyone holding it sees the change."""
        for f in fields(self):
            setattr(self, f.name, getattr(other, f.name))


@dataclass
class WheelSettings(_Group):
    up_is_forward: bool = True        # scroll up / swipe up = next frame
    frames_per_click: int = 1         # mouse wheel: frames per wheel click
    touchpad_px_per_frame: int = 12   # touchpad: pixels of swipe per frame
    shift_multiplier: int = 10        # Shift + scroll multiplies steps by this
    jog_degrees_per_frame: int = 15   # jog wheel: turn this far for one frame

    GROUP: ClassVar[str] = "wheel"


@dataclass
class DrawingSettings(_Group):
    hold_seconds: float = 0.5         # "Hold" drawings show this long either side of their frame
    line_width: int = 6               # thickness on screen when drawn, in pixels

    GROUP: ClassVar[str] = "drawing"


# Small values the UI remembers between sessions (e.g. last selected project).
def ui_value(key: str, default=None):
    return _store().value(f"ui/{key}", default)


def set_ui_value(key: str, value):
    s = _store()
    s.setValue(f"ui/{key}", value)
    s.sync()


# The shared instances the app reads from.
wheel = WheelSettings.load()
drawing = DrawingSettings.load()
