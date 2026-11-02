# timebase.py
# Frame-rate and time maths.
#
# Frame rates are kept as exact fractions (29.97 fps is really 30000/1001).
# Using the rounded value would make timers and side-by-side sync drift on
# long clips: 0.1% is 3.6 seconds over an hour.

from __future__ import annotations

from fractions import Fraction

# Rates that are really n * 1000/1001 (the "NTSC" family: 23.976, 29.97, 59.94...)
_NTSC_BASES = (24, 30, 48, 60, 120, 240)
# Common whole-number rates (cameras, GoPros, phones, broadcast)
_STANDARD = (12, 15, 24, 25, 30, 48, 50, 60, 90, 100, 120, 200, 240)


def snap_frame_rate(fps: float) -> Fraction:
    # Turn FFmpeg's rounded figure (e.g. 29.97, 23.98) into the exact rate.
    # Phones record at slightly variable rates (e.g. 29.83); within 1% of a
    # standard rate we snap to it, so the imported clip has a clean rate.
    for n in _NTSC_BASES:
        if abs(fps - n * 1000 / 1001) < 0.006:
            return Fraction(n * 1000, 1001)
    for n in _STANDARD:
        if abs(fps - n) / n < 0.01:
            return Fraction(n)
    return Fraction(fps).limit_denominator(1001)


def parse_rate(text: str) -> Fraction:
    # "30000/1001" or "50" -> Fraction
    return Fraction(text)


def format_rate(rate: Fraction) -> str:
    # Fraction(30000, 1001) -> "29.97", Fraction(50) -> "50"
    return f"{float(rate):.3f}".rstrip("0").rstrip(".")


def frame_to_seconds(n: int, rate: Fraction) -> float:
    return float(n / rate)


def seconds_to_frame(t: float, rate: Fraction) -> int:
    # Nearest frame to time t.
    return round(Fraction(t).limit_denominator(10**9) * rate)


def timecode(n: int, rate: Fraction) -> str:
    # mm:ss.ff label, where ff is the frame number within the second.
    # For 29.97 fps this counts 30 frames per labelled "second", like a
    # camera's timecode; use frame_to_seconds for real elapsed time.
    per_sec = max(1, round(rate))
    total_s, ff = divmod(int(n), per_sec)
    m, s = divmod(total_s, 60)
    return f"{m:02d}:{s:02d}.{ff:02d}"
