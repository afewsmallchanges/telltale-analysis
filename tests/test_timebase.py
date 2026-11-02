from fractions import Fraction

import pytest

from telltale.core import timebase


@pytest.mark.parametrize("reported, exact", [
    (23.98, Fraction(24000, 1001)),
    (24, Fraction(24)),
    (25, Fraction(25)),
    (29.97, Fraction(30000, 1001)),
    (30, Fraction(30)),
    (29.83, Fraction(30)),          # phone, slightly variable rate
    (50, Fraction(50)),
    (59.94, Fraction(60000, 1001)),
    (60, Fraction(60)),
    (119.88, Fraction(120000, 1001)),
    (239.76, Fraction(240000, 1001)),
    (12.5, Fraction(25, 2)),        # unusual rate kept as-is
])
def test_snap_frame_rate(reported, exact):
    assert timebase.snap_frame_rate(reported) == exact


def test_format_rate():
    assert timebase.format_rate(Fraction(30000, 1001)) == "29.97"
    assert timebase.format_rate(Fraction(50)) == "50"
    assert timebase.format_rate(Fraction(24000, 1001)) == "23.976"


def test_no_drift_over_an_hour():
    rate = Fraction(30000, 1001)
    frames_in_hour = timebase.seconds_to_frame(3600, rate)
    assert frames_in_hour == 107892            # not 108000
    assert timebase.frame_to_seconds(frames_in_hour, rate) == pytest.approx(3600, abs=1 / 60)


def test_seconds_frame_round_trip():
    rate = Fraction(60000, 1001)
    for n in (0, 1, 59, 60, 12345, 215784):
        assert timebase.seconds_to_frame(timebase.frame_to_seconds(n, rate), rate) == n


def test_timecode():
    assert timebase.timecode(0, Fraction(50)) == "00:00.00"
    assert timebase.timecode(50 * 61 + 7, Fraction(50)) == "01:01.07"
    assert timebase.timecode(30, Fraction(30000, 1001)) == "00:01.00"
