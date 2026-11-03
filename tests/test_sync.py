# Split-view sync: one master clock, a per-clip offset.

from fractions import Fraction as F

from telltale.core.sync import SyncGroup


def test_single_clip_behaves_like_a_normal_player():
    g = SyncGroup()
    g.load(0, F(50), 100)
    assert g.frame(0) == 0 and g.lead_bounds(0) == (0, 99)
    g.step(1, lead=0)
    assert g.frame(0) == 1
    g.step(-5, lead=0)
    assert g.frame(0) == 0                       # clamped at the start
    g.seek_lead(0, 42)
    assert g.frame(0) == 42 and g.lead_position(0) == 42
    g.to_end()
    assert g.frame(0) == 99 and g.at_end()
    g.step(3, lead=0)
    assert g.frame(0) == 99


def test_new_clip_starts_at_its_first_frame_now():
    g = SyncGroup()
    g.load(0, F(50), 500)
    g.seek_lead(0, 200)
    g.load(1, F(25), 300)
    assert g.frame(0) == 200 and g.frame(1) == 0


def test_scrubbing_one_clip_sets_sync_then_both_move_together():
    g = SyncGroup()
    g.load(0, F(50), 1000)
    g.load(1, F(50), 1000)
    g.seek_lead(0, 300)            # start gun in clip A at frame 300
    g.set_frame(1, 120)            # start gun in clip B at frame 120
    assert (g.frame(0), g.frame(1)) == (300, 120)

    g.step(10, lead=0)
    assert (g.frame(0), g.frame(1)) == (310, 130)
    g.step(-50, lead=0)
    assert (g.frame(0), g.frame(1)) == (260, 80)

    g.step_one(1, 2)               # nudge clip B alone
    assert (g.frame(0), g.frame(1)) == (260, 82)
    g.step(1, lead=0)
    assert (g.frame(0), g.frame(1)) == (261, 83)


def test_mixed_frame_rates_stay_in_sync_without_drift():
    g = SyncGroup()
    g.load(0, F(30000, 1001), 200_000)   # 29.97 fps, ~1h50m
    g.load(1, F(50), 400_000)
    for _ in range(3):
        g.step(1, lead=0)
    # After an hour of 29.97 footage, clip 1 must be exactly one hour in.
    g.seek_lead(0, 107892)                 # 3600 s at 29.97
    assert g.frame(1) == 180000            # 3600 s at 50 fps
    # Stepping the 50 fps clip as lead moves exactly one of its frames.
    before = g.frame(1)
    g.step(1, lead=1)
    assert g.frame(1) == before + 1


def test_range_covers_all_clips_and_lead_bounds_follow_lead():
    g = SyncGroup()
    g.load(0, F(25), 100)          # 0 .. 3.96 s
    g.seek_lead(0, 50)             # time = 2 s
    g.load(1, F(25), 250)          # starts now: offset -2 s → runs to 11.96 s master
    lo, hi = g.range()
    assert lo == 0 and hi == F(249, 25) + 2
    assert g.lead_bounds(0) == (0, 299)     # timeline in clip 0's frames runs past its end
    g.seek_lead(0, 299)
    assert g.frame(0) == 99 and g.frame(1) == 249


def test_unload_and_remove_slot():
    g = SyncGroup()
    g.load(0, F(25), 100)
    g.load(1, F(25), 1000)
    g.load(2, F(50), 10)
    g.remove_slot(0)               # pane 0 closed, others move up
    assert g.loaded() == [0, 1]
    assert g.tracks[0].frame_count == 1000 and g.tracks[3] is None
    g.unload(0)
    g.unload(1)
    assert g.loaded() == [] and g.range() == (0, 0) and g.time == 0
    g.load(3, F(25), 10)           # only clip again: starts at 0
    assert g.frame(3) == 0 and g.time == 0


def test_restoring_saved_offsets_and_time():
    g = SyncGroup()
    g.load(0, F(50), 1000)
    g.load(1, F(25), 500)
    g.seek_lead(0, 300)
    g.set_frame(1, 40)
    saved = (g.time, g.offset(0), g.offset(1))

    h = SyncGroup()
    h.time = saved[0]
    h.load(0, F(50), 1000, offset=saved[1])
    h.load(1, F(25), 500, offset=saved[2])
    assert (h.frame(0), h.frame(1)) == (300, 40)
    h.clear()
    assert h.loaded() == [] and h.time == 0
