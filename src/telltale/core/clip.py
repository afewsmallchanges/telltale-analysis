# clip.py
# ClipInfo: the record kept for each imported clip, saved as clip.json in
# the clip's library folder:
#
#   <library>/<clip id>/
#       clip.json        this record
#       frames/          000000.jpg, 000001.jpg, ... one file per frame
#       audio.m4a        the clip's sound (only if the original had any)
#       thumb.jpg        small preview picture for the library
#
# Unloading a project deletes frames/ (by far the biggest part) to save disk
# space; the rest stays, so the clip still shows in the library and in scene
# thumbnails. Loading makes frames/ again from the original video.

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from fractions import Fraction
from pathlib import Path
from typing import Optional

from . import timebase

# Bump when the folder layout or import settings change. Clips imported with
# an older version are imported again the next time they are opened.
FORMAT_VERSION = 1

META_FILE = "clip.json"
FRAMES_DIR = "frames"
FRAME_PATTERN = "%06d.jpg"
AUDIO_FILE = "audio.m4a"
THUMB_FILE = "thumb.jpg"


@dataclass
class ClipInfo:
    id: str                 # from the original file's contents (see library.clip_id)
    name: str               # original file name, e.g. "start_race3.mp4"
    source: str             # where the original was last seen
    frame_rate: str         # exact, e.g. "30000/1001" or "50"
    frame_count: int
    width: int
    height: int
    has_audio: bool = False
    imported_at: str = ""   # ISO date/time
    disk_bytes: int = 0     # space used by this clip's folder (0 = not measured yet)
    version: int = FORMAT_VERSION
    # Not saved: where this clip's folder is right now.
    folder: str = field(default="", compare=False)

    # --- frame rate ---------------------------------------------------------
    @property
    def rate(self) -> Fraction:
        return timebase.parse_rate(self.frame_rate)

    @property
    def fps(self) -> float:
        return float(self.rate)

    @property
    def duration(self) -> float:
        return timebase.frame_to_seconds(self.frame_count, self.rate)

    # --- files --------------------------------------------------------------
    @property
    def path(self) -> Path:
        return Path(self.folder)

    def frame_path(self, n: int) -> Path:
        return self.path / FRAMES_DIR / (FRAME_PATTERN % n)

    @property
    def audio_path(self) -> Optional[Path]:
        return self.path / AUDIO_FILE if self.has_audio else None

    @property
    def thumb_path(self) -> Path:
        return self.path / THUMB_FILE

    @property
    def frames_dir(self) -> Path:
        return self.path / FRAMES_DIR

    @property
    def has_frames(self) -> bool:
        # False once the frames were deleted (its project was unloaded). The
        # last frame is checked: frames/ is only ever removed or added whole.
        return self.frame_path(self.frame_count - 1).is_file()

    # --- saving / loading ---------------------------------------------------
    def save(self):
        data = {k: v for k, v in asdict(self).items() if k != "folder"}
        tmp = self.path / (META_FILE + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.path / META_FILE)  # never leaves a half-written file

    @classmethod
    def load(cls, folder: Path) -> Optional["ClipInfo"]:
        # Returns None if the folder isn't a complete, current-version clip.
        try:
            data = json.loads((Path(folder) / META_FILE).read_text())
        except (OSError, ValueError):
            return None
        known = {f.name for f in fields(cls)} - {"folder"}
        try:
            info = cls(**{k: v for k, v in data.items() if k in known})
        except TypeError:
            return None
        if info.version != FORMAT_VERSION or info.frame_count < 1:
            return None
        info.folder = str(Path(folder))
        return info
