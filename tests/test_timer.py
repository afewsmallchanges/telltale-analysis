# The scene timer: DN / UP / D/U against a zero on the scene clock.

from fractions import Fraction as F

import pytest

from telltale.core import timer
from telltale.core.projects import ProjectStore
from telltale.core.sync import SyncGroup


@pytest.mark.parametrize("mode, now, shown", [
    ("dn", F(26, 5), "0:05.20"),   # 5.2 s before zero
    ("dn", F(10), "0:00.40"),
    ("dn", F(52, 5), "0:00.00"),   # at zero
    ("dn", F(20), "0:00.00"),      # after zero: holds at 0
    ("up", F(5), "0:00.00"),       # before zero: not started
    ("up", F(52, 5), "0:00.00"),
    ("up", F(13), "0:02.60"),
    ("up", F(52, 5) + 125, "2:05.00"),
    ("du", F(26, 5), "−0:05.20"),
    ("du", F(52, 5), "0:00.00"),
    ("du", F(13), "+0:02.60"),
])
def test_modes(mode, now, shown):
    assert timer.display(mode, F(52, 5), now) == shown   # zero at 10.4 s


def test_format_rounds_down_and_handles_hours():
    assert timer.format_seconds(F(4999, 1000)) == "0:04.99"
    assert timer.format_seconds(F(3725)) == "1:02:05.00"
    assert timer.format_seconds(F(-1, 200), signed=True) == "0:00.00"   # under a hundredth: no sign


def test_exact_at_2997_fps():
    # 300 frames at 29.97 fps is 10.01 s, not 10 s
    rate = F(30000, 1001)
    assert timer.display("up", F(0), F(300) / rate) == "0:10.01"


def test_zero_set_from_a_lead_frame_matches_other_clips():
    g = SyncGroup()
    g.load(0, F(50), 1000)
    g.load(1, F(25), 500)
    g.seek_lead(0, 300)
    g.set_frame(1, 40)
    zero = g.lead_time(0, 400)                 # flag dragged to clip 0's frame 400
    assert g.tracks[0].position(zero) == 400
    assert g.tracks[1].position(zero) == 90    # = 40 + 100 frames at 50 → 50 at 25 fps
    g.seek(zero - 2)
    assert timer.display("dn", zero, g.time) == "0:02.00"


def test_timer_saved_with_the_scene(tmp_path, monkeypatch):
    monkeypatch.setenv("TELLTALE_DATA_DIR", str(tmp_path / "data"))
    store = ProjectStore()
    p = store.create("p")
    s = store.create_scene(p.id, ["a"])
    assert s.timer is None
    s.timer = {"mode": "du", "zero": "52/5"}
    store.save_scene(p.id, s)
    assert store.get_scene(p.id, s.id).timer == {"mode": "du", "zero": "52/5"}


@pytest.mark.parametrize("bad", [{"mode": "sideways", "zero": "1"}, {"mode": "up", "zero": "x"},
                                 "dn", None, {"mode": "dn", "zero": "1/0"}])
def test_bad_saved_timers_are_dropped(bad):
    assert timer.parse(bad) is None
