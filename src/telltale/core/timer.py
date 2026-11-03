# timer.py
# The scene timer: counts against a "zero" moment on the scene clock.
#
#   DN   count down to the zero frame (holds at 0:00.00 after it)
#   UP   count up from the zero frame (0:00.00 before it)
#   D/U  count down, then up: −0:05.20 … 0:00.00 … +0:03.12
#
# Times are exact Fractions of the scene's master clock (core/sync.py), so the
# timer is right in split view and with clips at different frame rates.

from __future__ import annotations

import math
from fractions import Fraction
from typing import Optional

MODES = {"dn": "DN", "up": "UP", "du": "D/U"}            # id -> short label
MODE_NAMES = {
    "dn": "Count down to frame",
    "up": "Count up from frame",
    "du": "Count down, then up (zero at frame)",
}
MINUS = "−"


def value(mode: str, zero: Fraction, now: Fraction) -> Fraction:
    # Seconds to show: DN and UP never go below zero; D/U is negative before zero.
    since = Fraction(now) - Fraction(zero)
    if mode == "dn":
        return max(-since, Fraction(0))
    if mode == "up":
        return max(since, Fraction(0))
    return since


def format_seconds(seconds: Fraction, signed: bool = False) -> str:
    # 0:05.20, 2:05.20, 1:02:05.20 (hundredths, rounded down);
    # signed adds − / + for the D/U timer.
    hundredths = math.floor(abs(Fraction(seconds)) * 100)
    h, rest = divmod(hundredths, 360000)
    m, rest = divmod(rest, 6000)
    s, c = divmod(rest, 100)
    body = f"{h}:{m:02d}:{s:02d}.{c:02d}" if h else f"{m}:{s:02d}.{c:02d}"
    if signed and hundredths:
        body = (MINUS if seconds < 0 else "+") + body
    return body


def display(mode: str, zero: Fraction, now: Fraction) -> str:
    return format_seconds(value(mode, zero, now), signed=(mode == "du"))


def parse(data) -> Optional[tuple[str, Fraction]]:
    # A saved timer {"mode": "dn", "zero": "12/5"} -> ("dn", Fraction(12, 5)); None if unusable.
    if not isinstance(data, dict) or data.get("mode") not in MODES:
        return None
    try:
        return data["mode"], Fraction(str(data.get("zero", "0")))
    except (ValueError, ZeroDivisionError):
        return None
