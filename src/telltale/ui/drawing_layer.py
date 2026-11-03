# drawing_layer.py
# Shows a view's drawings on top of the video, as QGraphicsItems in the same
# video-pixel coordinates as the picture (so they zoom and resize with it).
#
#   hold   saved drawings, shown on their frame plus a hold either side
#   quick  temporary drawings, removed as soon as the view's frame changes

from __future__ import annotations

import copy
from typing import Callable, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
)

from ..core import drawings
from ..core.drawings import Drawing

Z_DRAWINGS = 10
HALO = QColor(0, 0, 0, 100)  # soft dark edge so drawings show up on bright water and sky


DASH = [2.2, 2.6]   # dash, gap — in line widths (round caps make dashes look longer)


def _pen(colour: QColor, width: float, dashed: bool, base_width: float) -> QPen:
    pen = QPen(colour, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    if dashed:
        # Dash lengths are in units of this pen's width; scale so a halo's
        # dashes line up with the coloured line's.
        k = base_width / width
        pen.setDashPattern([DASH[0] * k, DASH[1] * k])
    return pen


def make_item(d: Drawing) -> QGraphicsItem:
    colour = QColor(d.colour)
    w = d.width
    dashed = d.style == "dashed"
    path = QPainterPath()
    head = None

    if d.kind == "ellipse":
        (x1, y1), (x2, y2) = d.points
        path.addEllipse(QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)))
    else:
        segments, head = drawings.outline(d)
        path.moveTo(QPointF(*segments[0][0]))
        for _p0, c1, c2, p3 in segments:
            if d.kind in ("line", "pen"):
                path.lineTo(QPointF(*p3))
            else:
                path.cubicTo(QPointF(*c1), QPointF(*c2), QPointF(*p3))

    item = QGraphicsPathItem(path)
    item.setPen(_pen(colour, w, dashed, w))
    item.setZValue(Z_DRAWINGS)

    halo_w = w + max(2.0, w * 0.6)
    halo = QGraphicsPathItem(path, item)
    halo.setPen(_pen(HALO, halo_w, dashed, w))
    halo.setFlag(QGraphicsItem.GraphicsItemFlag.ItemStacksBehindParent)

    if head is not None:
        tip = QGraphicsPolygonItem(QPolygonF([QPointF(x, y) for x, y in head]), item)
        tip.setBrush(colour)
        tip.setPen(QPen(HALO, max(1.0, w * 0.35), Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    return item


Snapshot = tuple[list[Drawing], list[Drawing]]   # (hold, quick) copies, for undo


class DrawingLayer:
    def __init__(self, scene: QGraphicsScene):
        self.scene = scene
        self.hold: list[Drawing] = []
        self.quick: list[Drawing] = []
        self.frame: Optional[int] = None
        self.hold_frames = 0
        self.selected: Optional[str] = None    # id of the selected drawing
        self._items: dict[str, QGraphicsItem] = {}
        self._box: Optional[QGraphicsRectItem] = None
        self.changed: Optional[Callable[[], None]] = None   # called when what's shown changes

    # --- what's on screen ---------------------------------------------------
    def set_frame(self, frame: int, hold_frames: int):
        if frame != self.frame:
            self.quick.clear()  # quick drawings never outlive their frame
        self.frame = frame
        self.hold_frames = hold_frames
        self._sync()

    def visible(self) -> list[Drawing]:
        if self.frame is None:
            return []
        return [d for d in self.hold if d.visible_at(self.frame, self.hold_frames)] + self.quick

    def find(self, did: Optional[str]) -> Optional[Drawing]:
        return next((d for d in self.hold + self.quick if d.id == did), None)

    def is_saved(self, did: str) -> bool:
        return any(d.id == did for d in self.hold)

    def at(self, point: list, tolerance: float) -> Optional[Drawing]:
        # The drawing under `point` (video pixels), topmost first.
        for d in reversed(self.visible()):
            if drawings.hit(d, point, tolerance):
                return d
        return None

    # --- selecting ----------------------------------------------------------
    def select(self, did: Optional[str]):
        if did != self.selected:
            self.selected = did
            self._sync()

    def selected_drawing(self) -> Optional[Drawing]:
        return self.find(self.selected)

    def redraw(self, did: str):
        # A drawing changed (moved, recoloured): rebuild its item.
        item = self._items.pop(did, None)
        if item is not None:
            self.scene.removeItem(item)
        self._sync()

    # --- undo ---------------------------------------------------------------
    def snapshot(self) -> Snapshot:
        return copy.deepcopy(self.hold), copy.deepcopy(self.quick)

    def restore(self, snap: Snapshot):
        hold, quick = copy.deepcopy(snap)
        self.hold = hold
        self.quick = [d for d in quick if d.frame == self.frame]  # quick ones only on their frame
        for did in list(self._items):  # rebuild everything: drawings may have moved
            self.scene.removeItem(self._items.pop(did))
        self._sync()

    # --- changing -----------------------------------------------------------
    def load(self, drawings_: list[Drawing]):
        self.hold = list(drawings_)
        self.quick = []
        self.selected = None
        self._sync()

    def add(self, d: Drawing, quick: bool):
        (self.quick if quick else self.hold).append(d)
        self._sync()

    def remove(self, did: str) -> bool:
        before = len(self.hold) + len(self.quick)
        self.hold = [d for d in self.hold if d.id != did]
        self.quick = [d for d in self.quick if d.id != did]
        self._sync()
        return len(self.hold) + len(self.quick) < before

    def clear_visible(self) -> int:
        # "Clear": remove everything showing now. Returns how many saved ones went.
        showing = {d.id for d in self.visible()}
        removed = sum(1 for d in self.hold if d.id in showing)
        self.hold = [d for d in self.hold if d.id not in showing]
        self.quick = []
        self._sync()
        return removed

    def clear_all(self):
        self.hold = []
        self.quick = []
        self._sync()

    def reset(self):
        # Clip unloaded.
        self.clear_all()
        self.frame = None

    def _sync(self):
        shown = self.visible()
        wanted = {d.id: d for d in shown}
        if self.selected not in wanted:
            self.selected = None  # it's gone, or off screen
        for did in list(self._items):
            if did not in wanted:
                self.scene.removeItem(self._items.pop(did))
        for did, d in wanted.items():
            if did not in self._items:
                item = make_item(d)
                self.scene.addItem(item)
                self._items[did] = item
        self._update_box()
        if self.changed:
            self.changed()

    def _update_box(self):
        # Dashed box around the selected drawing.
        if self._box is not None:
            self.scene.removeItem(self._box)
            self._box = None
        item = self._items.get(self.selected) if self.selected else None
        if item is None:
            return
        rect = item.sceneBoundingRect()
        pad = 4.0
        self._box = QGraphicsRectItem(rect.adjusted(-pad, -pad, pad, pad))
        pen = QPen(QColor(255, 255, 255, 230), 1.5, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)  # same thickness on screen at any zoom
        self._box.setPen(pen)
        self._box.setZValue(Z_DRAWINGS + 2)
        self.scene.addItem(self._box)
