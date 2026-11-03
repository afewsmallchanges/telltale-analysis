# drawings.py
# Drawings over the video: straight and bendy arrows, lines, circles/ellipses and freehand pen.

# A drawing is stored in video-pixel coordinates (so it stays on the right spot when zooming or resizing) and is pinned to the frame it was drawn on.
# "Hold" drawings are saved with the scene and shown on their frame plus a short hold either side; 
# "Quick" drawings are never saved (the UI drops them as soon as the view moves to another frame).

# No Qt in here: the UI turns these into QGraphicsItems, using the shapes worked out by `outline` below.

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field, fields
from typing import Any, Optional

KINDS = ("arrow", "bendy", "line", "ellipse", "pen")
STYLES = ("solid", "dashed")
STYLED_KINDS = KINDS    # every kind can be solid or dashed
ARROW_KINDS = ("arrow", "bendy")
MIN_SIZE = 3.0          # video pixels; smaller strokes are taken as accidental clicks

Point = list[float]     # [x, y] in video pixels
Segment = tuple[Point, Point, Point, Point]   # cubic curve: start, control 1, control 2, end


def new_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Drawing:
    kind: str                      # one of KINDS
    frame: int                     # the clip frame it was drawn on
    points: list[Point]            # arrow: [start, bend, end] (bend = middle for a straight
                                   # arrow); bendy: points along its path; line: [a, b];
                                   # ellipse: two opposite corners; pen: the stroke
    colour: str = "#ff3b30"
    width: float = 6.0             # line thickness in video pixels
    style: str = "solid"           # "solid" or "dashed"
    id: str = field(default_factory=new_id)

    def visible_at(self, frame: int, hold_frames: int) -> bool:
        return abs(frame - self.frame) <= hold_frames

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Optional["Drawing"]:
        known = {f.name for f in fields(cls)}
        try:
            drawing = cls(**{k: v for k, v in d.items() if k in known})
        except TypeError:
            return None
        if drawing.kind not in KINDS or len(drawing.points) < 2:
            return None
        if drawing.kind == "arrow" and len(drawing.points) != 3:
            return None
        if drawing.style not in STYLES:
            drawing.style = "solid"
        drawing.points = [[float(x), float(y)] for x, y in drawing.points]
        return drawing


def hold_frames(hold_seconds: float, fps: float) -> int:
    return max(0, round(hold_seconds * fps))


# --- making drawings from strokes ---------------------------------------------

def build(kind: str, stroke: list[Point], frame: int, colour: str, width: float,
          circle: bool = False, style: str = "solid") -> Optional[Drawing]:
    # Turn the points the mouse/finger passed through into a drawing.
    # Returns None for strokes too small to be meant (a click or a tap).
    if kind not in KINDS or len(stroke) < 2:
        return None
    a, b = stroke[0], stroke[-1]
    if kind == "pen":
        pts = simplify(stroke, max(0.5, width * 0.25))
        if len(pts) < 2 or _extent(pts) < MIN_SIZE:
            return None
    elif kind == "bendy":
        # Keep just enough points to follow every bend; the curve is smoothed
        # through them when drawn.
        # Evenly spaced points first (uneven spacing makes the smoothed curve
        # kink), then drop the ones on straight stretches.
        pts = rdp(simplify(stroke, max(6.0, width * 2.0)), max(0.8, width * 0.15))
        if _extent(pts) < MIN_SIZE:
            return None
    elif kind == "ellipse":
        if circle:  # Shift held: a circle, sized by the larger side
            side = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
            b = [a[0] + math.copysign(side, b[0] - a[0] or 1), a[1] + math.copysign(side, b[1] - a[1] or 1)]
        if abs(b[0] - a[0]) < MIN_SIZE or abs(b[1] - a[1]) < MIN_SIZE:
            return None
        pts = [list(a), list(b)]
    else:  # arrow, line: straight from where you pressed to where you let go
        if _dist(a, b) < MIN_SIZE:
            return None
        mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
        pts = [list(a), mid, list(b)] if kind == "arrow" else [list(a), list(b)]
    return Drawing(kind, frame, [[float(x), float(y)] for x, y in pts], colour, float(width),
                   style if (kind in STYLED_KINDS and style in STYLES) else "solid")


def simplify(points: list[Point], min_step: float) -> list[Point]:
    # Drop points closer than min_step to the last kept one (keeps the end).
    if not points:
        return []
    out = [list(points[0])]
    for p in points[1:]:
        if _dist(p, out[-1]) >= min_step:
            out.append(list(p))
    if len(points) > 1 and out[-1] != list(points[-1]):
        out.append(list(points[-1]))
    return out


def rdp(points: list[Point], tolerance: float) -> list[Point]:
    # Ramer–Douglas–Peucker: the fewest points that stay within `tolerance`
    # of the original path. Keeps every real bend, drops the jitter.
    if len(points) < 3:
        return [list(p) for p in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        a, b = points[i], points[j]
        far, far_d = None, tolerance
        for k in range(i + 1, j):
            d = _segment_distance(points[k], a, b)
            if d > far_d:
                far, far_d = k, d
        if far is not None:
            keep[far] = True
            stack += [(i, far), (far, j)]
    return [list(p) for p, k in zip(points, keep, strict=True) if k]


# --- shapes for drawing (used by the UI) --------------------------------------

def smooth(points: list[Point]) -> list[Segment]:
    # A smooth curve through all the points (Catmull-Rom), as cubic segments.
    n = len(points)
    if n == 2:
        a, b = points
        return [(a, _lerp(a, b, 1 / 3), _lerp(a, b, 2 / 3), b)]
    segs = []
    for i in range(n - 1):
        p0 = points[max(i - 1, 0)]
        p1, p2 = points[i], points[i + 1]
        p3 = points[min(i + 2, n - 1)]
        c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6]
        c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6]
        segs.append((p1, c1, c2, p2))
    return segs


def outline(d: Drawing) -> tuple[list[Segment], Optional[list[Point]]]:
    # The curve(s) to stroke and, for arrows, the arrowhead triangle.
    # Lines and pen strokes are straight segments; ellipses are drawn by the UI
    # from their two corners.
    if d.kind == "bendy":
        segs = smooth(d.points)
    elif d.kind == "arrow":  # quadratic through its bend point, as a cubic
        s, c, e = d.points
        segs = [(s, _lerp(s, c, 2 / 3), _lerp(e, c, 2 / 3), e)]
    else:
        segs = [(a, a, b, b) for a, b in zip(d.points, d.points[1:], strict=False)]
    if d.kind not in ARROW_KINDS:
        return segs, None

    # Arrowhead: pointing along the curve's final direction. The curve stops
    # a little short so its rounded end doesn't poke through the tip.
    p0, c1, c2, tip = segs[-1]
    from_pt = c2 if _dist(c2, tip) > 1e-6 else (c1 if _dist(c1, tip) > 1e-6 else p0)
    dx, dy = tip[0] - from_pt[0], tip[1] - from_pt[1]
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    head_len = max(d.width * 3.2, 10.0)
    half = head_len * 0.6
    back = [tip[0] - ux * head_len, tip[1] - uy * head_len]
    head = [list(tip), [back[0] - uy * half, back[1] + ux * half],
            [back[0] + uy * half, back[1] - ux * half]]
    shift = [-ux * head_len * 0.85, -uy * head_len * 0.85]
    end = [tip[0] + shift[0], tip[1] + shift[1]]
    segs[-1] = (p0, c1, [c2[0] + shift[0], c2[1] + shift[1]], end)
    return segs, head


# --- selecting and moving -----------------------------------------------------

def distance(d: Drawing, p: Point) -> float:
    # How far point p is from the drawn line (0 inside an arrowhead).
    if d.kind == "ellipse":
        (x1, y1), (x2, y2) = d.points
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        rx, ry = abs(x2 - x1) / 2, abs(y2 - y1) / 2
        outline_pts = [[cx + rx * math.cos(t * math.pi / 36), cy + ry * math.sin(t * math.pi / 36)]
                       for t in range(73)]
        return _polyline_distance(p, outline_pts)
    segs, head = outline(d)
    if head and _in_triangle(p, *head):
        return 0.0
    line = [segs[0][0]]
    for seg in segs:
        if d.kind in ("line", "pen"):
            line.append(seg[3])
        else:
            line += [_cubic(seg, i / 12) for i in range(1, 13)]
    dist = _polyline_distance(p, line)
    if head:  # the arrowhead's edges too
        dist = min(dist, _polyline_distance(p, head + [head[0]]))
    return dist


def hit(d: Drawing, p: Point, tolerance: float) -> bool:
    # Is p on the drawing? `tolerance` is extra slack beyond the line's own width.
    return distance(d, p) <= tolerance + d.width / 2


def move(d: Drawing, dx: float, dy: float):
    d.points = [[x + dx, y + dy] for x, y in d.points]


# --- helpers -------------------------------------------------------------------

def _cubic(seg: Segment, t: float) -> Point:
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = seg
    u = 1 - t
    return [u ** 3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3 * x3,
            u ** 3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3 * y3]


def _polyline_distance(p: Point, pts: list[Point]) -> float:
    if len(pts) == 1:
        return _dist(p, pts[0])
    return min(_segment_distance(p, a, b) for a, b in zip(pts, pts[1:], strict=False))


def _in_triangle(p: Point, a: Point, b: Point, c: Point) -> bool:
    def side(u, v, w):
        return (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])
    s1, s2, s3 = side(a, b, p), side(b, c, p), side(c, a, p)
    return (s1 >= 0 and s2 >= 0 and s3 >= 0) or (s1 <= 0 and s2 <= 0 and s3 <= 0)


def _dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _lerp(a: Point, b: Point, t: float) -> Point:
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]


def _segment_distance(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return _dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return _dist(p, [a[0] + t * dx, a[1] + t * dy])


def _extent(points: list[Point]) -> float:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return max(max(xs) - min(xs), max(ys) - min(ys))
