# sync.py
# Keeping up to four clips in step, for split view.
#
# There is one shared "master" clock, `time` (seconds). Each loaded clip has
# an offset, and shows the moment  time + offset  of its own footage.
#
#   - The main timeline, jog wheel, arrow keys and Play move `time`, so every
#     clip moves together and stays in sync.
#   - Scrubbing one clip's own bar changes only that clip's offset. That's how
#     you line up the same moment (e.g. the start gun) in different clips.
#
# One clip is the "lead" (the selected pane): stepping moves exactly one of
# its frames, and the main timeline counts in its frames. Clips at other
# frame rates show their nearest frame.
#
# All times are exact Fractions, so 29.97 and 50 fps clips never drift apart.

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

HALF = Fraction(1, 2)


@dataclass
class Track:
    rate: Fraction          # frames per second, exact
    frame_count: int
    offset: Fraction = Fraction(0)

    @property
    def last_time(self) -> Fraction:
        return (self.frame_count - 1) / self.rate

    def position(self, t: Fraction) -> int:
        # Nearest frame to master time t, NOT clamped to the clip.
        return math.floor((t + self.offset) * self.rate + HALF)

    def frame_at(self, t: Fraction) -> int:
        return max(0, min(self.position(t), self.frame_count - 1))


class SyncGroup:
    def __init__(self, slots: int = 4):
        self.tracks: list[Optional[Track]] = [None] * slots
        self.time = Fraction(0)

    # --- loading ------------------------------------------------------------
    def loaded(self) -> list[int]:
        return [i for i, t in enumerate(self.tracks) if t is not None]

    def load(self, i: int, rate: Fraction, frame_count: int,
             offset: Optional[Fraction] = None):
        # A newly loaded clip starts at its first frame "now", so you can then
        # scrub it to the matching moment. If it's the only clip, start at 0.
        # Pass `offset` to restore a saved sync instead.
        if offset is None:
            others = [j for j in self.loaded() if j != i]
            if not others:
                self.time = Fraction(0)
                offset = Fraction(0)
            else:
                offset = -self.time
        self.tracks[i] = Track(Fraction(rate), max(1, int(frame_count)), Fraction(offset))

    def clear(self):
        self.tracks = [None] * len(self.tracks)
        self.time = Fraction(0)

    def offset(self, i: int) -> Optional[Fraction]:
        t = self.tracks[i]
        return None if t is None else t.offset

    def unload(self, i: int):
        self.tracks[i] = None
        self._clamp()

    def remove_slot(self, i: int):
        # Pane i closed: later panes move up one place.
        del self.tracks[i]
        self.tracks.append(None)
        self._clamp()

    # --- reading ------------------------------------------------------------
    def frame(self, i: int) -> Optional[int]:
        t = self.tracks[i]
        return None if t is None else t.frame_at(self.time)

    def range(self) -> tuple[Fraction, Fraction]:
        # Earliest and latest master time at which some clip is still showing.
        loaded = [t for t in self.tracks if t is not None]
        if not loaded:
            return Fraction(0), Fraction(0)
        return (min(-t.offset for t in loaded),
                max(t.last_time - t.offset for t in loaded))

    def at_end(self) -> bool:
        return self.time >= self.range()[1]

    # Main timeline, counted in the lead clip's frames (may run past either
    # end of the lead clip when other clips are longer).
    def lead_position(self, lead: int) -> int:
        return self.tracks[lead].position(self.time)

    def lead_time(self, lead: int, position: int) -> Fraction:
        # Master time at which the lead clip is at `position`.
        t = self.tracks[lead]
        return Fraction(position) / t.rate - t.offset

    def lead_bounds(self, lead: int) -> tuple[int, int]:
        t = self.tracks[lead]
        lo, hi = self.range()
        return (math.ceil((lo + t.offset) * t.rate), math.floor((hi + t.offset) * t.rate))

    # --- moving everything together -----------------------------------------
    def seek(self, t: Fraction):
        self.time = Fraction(t)
        self._clamp()

    def seek_lead(self, lead: int, position: int):
        t = self.tracks[lead]
        self.seek(Fraction(position) / t.rate - t.offset)

    def step(self, n: int, lead: int):
        # Exactly n frames of the lead clip.
        self.seek_lead(lead, self.lead_position(lead) + n)

    def to_start(self):
        self.seek(self.range()[0])

    def to_end(self):
        self.seek(self.range()[1])

    # --- moving one clip (changing its sync) --------------------------------
    def set_frame(self, i: int, frame: int):
        # Make clip i show `frame` now, without moving the others.
        t = self.tracks[i]
        frame = max(0, min(int(frame), t.frame_count - 1))
        t.offset = Fraction(frame) / t.rate - self.time

    def step_one(self, i: int, n: int):
        self.set_frame(i, self.frame(i) + n)

    def _clamp(self):
        lo, hi = self.range()
        self.time = min(max(self.time, lo), hi)
