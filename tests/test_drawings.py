# Drawings: building them from strokes, hold visibility, saving with scenes.

import json
import math

import pytest

from telltale.core import drawings
from telltale.core.drawings import Drawing, build
from telltale.core.projects import ProjectStore, SceneSlot


def test_arrow_is_straight_whatever_the_path():
    stroke = [[0, 0], [25, 30], [50, -20], [100, 0]]
    d = build("arrow", stroke, frame=7, colour="#ffd60a", width=5, style="dashed")
    assert d.kind == "arrow" and d.frame == 7 and d.colour == "#ffd60a" and d.width == 5
    assert d.points == [[0, 0], [50, 0], [100, 0]] and d.style == "dashed"


def _snake(n=200):
    # Back-and-forth path: three bends
    return [[i * 2.0, 60 * math.sin(i / n * 3 * math.pi)] for i in range(n + 1)]


def test_bendy_arrow_keeps_every_bend_but_few_points():
    stroke = _snake()
    d = build("bendy", stroke, 0, "#fff", 6)
    assert d.kind == "bendy" and d.points[0] == [0, 0] and d.points[-1] == stroke[-1]
    assert 6 <= len(d.points) <= 40
    ys = [p[1] for p in d.points]
    assert max(ys) > 55 and min(ys) < -55                  # both peaks kept
    # The smoothed curve passes through every kept point and stays near the stroke
    segs = drawings.smooth(d.points)
    assert len(segs) == len(d.points) - 1
    for (p0, _c1, _c2, p3), (a, b) in zip(segs, zip(d.points, d.points[1:], strict=False), strict=True):
        assert p0 == a and p3 == b


def test_bendy_straight_drag_is_just_two_points():
    d = build("bendy", [[0, 0], [30, 0.5], [60, -0.4], [100, 0]], 0, "#fff", 6)
    assert d.points == [[0, 0], [100, 0]]


def test_arrowheads_point_along_the_end_of_the_curve():
    up = Drawing("arrow", 0, [[0, 100], [0, 50], [0, 0]], width=6)
    segs, head = drawings.outline(up)
    tip, left, right = head
    assert tip == [0, 0] and left[1] > 0 and right[1] > 0          # head behind the tip
    assert segs[-1][3][1] > 0                                       # curve stops short of the tip
    snake = build("bendy", _snake(), 0, "#fff", 6)
    segs, head = drawings.outline(snake)
    assert head[0] == snake.points[-1]
    assert drawings.outline(Drawing("line", 0, [[0, 0], [5, 5]]))[1] is None


def test_line_ellipse_and_circle():
    line = build("line", [[10, 10], [20, 30], [40, 50]], 0, "#fff", 4)
    assert line.points == [[10, 10], [40, 50]]
    ell = build("ellipse", [[10, 10], [60, 30]], 0, "#fff", 4)
    assert ell.points == [[10, 10], [60, 30]]
    circ = build("ellipse", [[100, 100], [60, 130]], 0, "#fff", 4, circle=True)
    (x1, y1), (x2, y2) = circ.points
    assert abs(x2 - x1) == abs(y2 - y1) == 40 and x2 < x1 and y2 > y1   # keeps drag direction


def test_pen_is_thinned_but_keeps_its_ends():
    stroke = [[i * 0.2, 0] for i in range(500)]       # 100 px long, 500 points
    d = build("pen", stroke, 0, "#fff", 8)
    assert d.points[0] == [0, 0] and d.points[-1] == stroke[-1]
    assert 20 < len(d.points) < 120


@pytest.mark.parametrize("kind", drawings.KINDS)
def test_clicks_and_tiny_strokes_are_ignored(kind):
    assert build(kind, [[5, 5], [6, 6]], 0, "#fff", 4) is None
    assert build(kind, [[5, 5]], 0, "#fff", 4) is None


def test_hold_visibility():
    d = Drawing("line", 100, [[0, 0], [10, 10]])
    hold = drawings.hold_frames(0.5, 50)               # 25 frames
    assert hold == 25
    assert d.visible_at(100, hold) and d.visible_at(75, hold) and d.visible_at(125, hold)
    assert not d.visible_at(74, hold) and not d.visible_at(126, hold)
    assert d.visible_at(100, 0) and not d.visible_at(101, 0)


def test_every_kind_can_be_dashed_and_old_drawings_default_to_solid():
    for kind in drawings.KINDS:
        assert build(kind, [[0, 0], [10, 10], [40, 30]], 0, "#fff", 4, style="dashed").style == "dashed"
    old = Drawing.from_dict({"kind": "arrow", "frame": 1, "points": [[0, 0], [5, 9], [10, 0]]})
    assert old.style == "solid" and old.points[1] == [5.0, 9.0]    # old curved arrows still load
    assert Drawing.from_dict({"kind": "line", "frame": 1, "points": [[0, 0], [5, 5]],
                              "style": "wavy"}).style == "solid"


def test_from_dict_rejects_bad_drawings():
    assert Drawing.from_dict({"kind": "star", "frame": 1, "points": [[0, 0], [1, 1]]}) is None
    assert Drawing.from_dict({"kind": "line", "frame": 1, "points": [[0, 0]]}) is None
    assert Drawing.from_dict({"frame": 1}) is None
    ok = Drawing.from_dict({"kind": "line", "frame": 3, "points": [[0, 0], [5, 5]], "extra": 1})
    assert ok.kind == "line" and ok.points == [[0.0, 0.0], [5.0, 5.0]]


def test_drawings_are_saved_with_the_scene(tmp_path, monkeypatch):
    monkeypatch.setenv("TELLTALE_DATA_DIR", str(tmp_path / "data"))
    store = ProjectStore()
    p = store.create("p")
    s = store.create_scene(p.id, ["clip"])
    arrow = build("bendy", [[0, 0], [50, 40], [100, 0]], 12, "#34c759", 6, style="dashed")
    pen = build("pen", [[0, 0], [10, 0], [20, 5]], 30, "#ffffff", 3)
    s.slots[0].drawings = [arrow, pen]
    store.save_scene(p.id, s)

    raw = json.loads((p.path / "project.json").read_text())
    assert raw["scenes"][0]["slots"][0]["drawings"][0]["kind"] == "bendy"
    back = store.get_scene(p.id, s.id).slots[0].drawings
    assert back == [arrow, pen]


def test_old_slots_without_drawings_and_damaged_drawings_load():
    slot = SceneSlot.from_dict({"clip_id": "a", "offset": "0"})
    assert slot.drawings == []
    slot = SceneSlot.from_dict({"clip_id": "a", "drawings": [
        {"kind": "line", "frame": 1, "points": [[0, 0], [9, 9]]}, {"kind": "??"}, "junk"]})
    assert len(slot.drawings) == 1


def test_hit_testing_follows_the_drawn_shape():
    line = Drawing("line", 0, [[0, 0], [100, 0]], width=4)
    assert drawings.hit(line, [50, 3], tolerance=2)          # 3 px off, within 2 + 4/2
    assert not drawings.hit(line, [50, 6], tolerance=2)
    assert not drawings.hit(line, [130, 0], tolerance=2)      # past the end

    ring = Drawing("ellipse", 0, [[0, 0], [100, 60]], width=4)
    assert drawings.hit(ring, [100, 30], tolerance=2)        # on the outline
    assert not drawings.hit(ring, [50, 30], tolerance=2)     # the middle is see-through

    arrow = Drawing("arrow", 0, [[0, 0], [50, 0], [100, 0]], width=6)
    assert drawings.distance(arrow, [95, 0]) == 0            # inside the head
    assert drawings.hit(arrow, [96, 6], tolerance=2)         # the head's wide part

    snake = build("bendy", _snake(), 0, "#fff", 6)
    on_curve = [100.0, 60 * math.sin(50 / 200 * 3 * math.pi)]
    assert drawings.hit(snake, on_curve, tolerance=4)
    assert not drawings.hit(snake, [100.0, on_curve[1] + 30], tolerance=4)

    pen = build("pen", [[0, 0], [20, 20], [40, 0]], 0, "#fff", 4)
    assert drawings.hit(pen, [20, 19], tolerance=2) and not drawings.hit(pen, [20, 0], tolerance=2)


def test_moving_shifts_every_point():
    d = build("bendy", _snake(), 0, "#fff", 6)
    before = [list(p) for p in d.points]
    drawings.move(d, 15, -7)
    assert d.points == [[x + 15, y - 7] for x, y in before]
    assert drawings.hit(d, [before[3][0] + 15, before[3][1] - 7], tolerance=1)
