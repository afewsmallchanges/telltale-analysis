# video_pane.py
# One view in the player: a video clip, or a board (a still picture or
# diagram). Up to four sit side by side in split view.
#
# PaneView shows the frame using QGraphicsView: the picture lives in "scene"
# coordinates (video pixels), and the view maps them to the screen. Zooming
# (crop) is just a different view of the same scene, and drawings added
# later will sit in the same video-pixel coordinates, so they stay attached
# to the picture when zooming or resizing.

from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QRubberBand,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
)

from .. import settings
from ..core import drawings
from ..core.boards import BoardInfo
from ..core.clip import ClipInfo
from ..core.frames import FrameSource
from .drawing_layer import Z_DRAWINGS, DrawingLayer, make_item
from .icons import icon
from .wheel import TimelineSlider, WheelStepper, slider_style

# One colour per pane, used for its border and its sync bar (red, blue, green, amber).
PANE_COLOURS = ["#e5322d", "#1e9be0", "#3fb950", "#f0a020"]


class PaneView(QGraphicsView):
    stepRequested = Signal(int)
    clicked = Signal()
    cropChanged = Signal()
    drawingStarted = Signal()
    drawingFinished = Signal(object)   # a finished Drawing (the player decides Quick / Hold)
    clearRequested = Signal()          # its "Clear Drawings" button
    contextRequested = Signal(object)  # right-click (global position)
    selectionChanged = Signal()        # a drawing was selected / deselected here
    editStarted = Signal()             # about to move the selected drawing
    editFinished = Signal(bool)        # done moving it (True if it actually moved)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._frame_item = QGraphicsPixmapItem()
        self._frame_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._frame_item)

        self.setBackgroundBrush(QColor(0, 0, 0))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(160, 90)
        # Let dropped files fall through to the main window (which imports them).
        self.setAcceptDrops(False)
        self.viewport().setAcceptDrops(False)

        self._wheel = WheelStepper()
        self._size: Optional[tuple[int, int]] = None   # video width, height
        self.crop: Optional[QRectF] = None              # zoomed area, in video pixels
        self.crop_mode = False
        self._band = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
        self._band_origin = None

        # Drawing
        self.layer = DrawingLayer(self._scene)
        self.tool: Optional[str] = None   # "arrow", "line", "ellipse", "pen" or None
        self.colour = "#ff3b30"
        self.line_style = "solid"
        self.frame: Optional[int] = None  # clip frame on show (drawings are pinned to it)
        self._stroke: Optional[list] = None
        self._preview = None
        self._drag: Optional[tuple] = None   # moving a drawing: (start point, its original points)
        self.setMouseTracking(True)          # hover: show a move cursor over drawings

        # Floating "Clear Drawings" button, shown by the pane when there's
        # something to clear. Away from the tools so it isn't hit by accident.
        self.clear_btn = QToolButton(self.viewport())
        self.clear_btn.setText("Clear Drawings")
        self.clear_btn.setIcon(icon("clear"))
        self.clear_btn.setIconSize(QSize(18, 18))
        self.clear_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setToolTip("Remove the drawings on screen in this view "
                                  "(Edit → Clear All for the whole scene)")
        self.clear_btn.setStyleSheet(
            "QToolButton { background: #f8d0d0; color: #1a1a1a; border: 1px solid #c0504d;"
            " border-radius: 7px; padding: 4px 10px 4px 6px; font-weight: 600; }"
            "QToolButton:hover { background: #ffb3b3; }"
            "QToolButton:pressed { background: #f08080; }")
        self.clear_btn.clicked.connect(lambda _c=False: self.clearRequested.emit())
        self.clear_btn.hide()

    # --- picture ------------------------------------------------------------
    def set_frame(self, rgb: np.ndarray):
        h, w = rgb.shape[:2]
        rgb = np.ascontiguousarray(rgb)
        image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self._frame_item.setPixmap(QPixmap.fromImage(image))  # copies the pixels
        if self._size != (w, h):
            self._size = (w, h)
            self._scene.setSceneRect(0, 0, w, h)
            self.crop = None
            self.fit()

    def clear(self):
        self._frame_item.setPixmap(QPixmap())
        self._size = None
        self.crop = None
        self.frame = None
        self._cancel_stroke()
        self.layer.reset()

    def fit(self):
        if self._size:
            whole = QRectF(0, 0, *self._size)
            self.fitInView(self.crop or whole, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()
        self.place_clear_button()

    def place_clear_button(self):
        # "Clear Drawings" sits at the top middle of the picture area.
        b = self.clear_btn
        b.adjustSize()
        b.move(max(0, (self.viewport().width() - b.width()) // 2), 8)
        b.raise_()

    def contextMenuEvent(self, event):
        # Right-clicking a drawing selects it, so the menu can offer "Delete drawing".
        if self._size is not None and self.tool is None:
            d = self.layer.at(self._scene_xy(event.pos()), self._tolerance())
            if d is not None:
                self.select(d.id)
        self.contextRequested.emit(event.globalPos())
        event.accept()

    def showEvent(self, event):
        super().showEvent(event)
        self.fit()

    # --- crop / zoom --------------------------------------------------------
    def set_crop_mode(self, on: bool):
        self.crop_mode = on and self._size is not None
        self._update_cursor()

    def set_tool(self, tool: Optional[str]):
        self.tool = tool
        self._cancel_stroke()
        if tool is not None:
            self.select(None)  # drawing, not editing
        self._update_cursor()

    def _update_cursor(self):
        drawing = self.crop_mode or self.tool is not None
        self.viewport().setCursor(Qt.CursorShape.CrossCursor if drawing else Qt.CursorShape.ArrowCursor)

    # --- drawing ------------------------------------------------------------
    def _scene_xy(self, pos) -> list:
        # A point on the widget, in video pixels.
        p = self.mapToScene(pos)
        return [p.x(), p.y()]

    def _video_point(self, event) -> list:
        # Where the pointer is, in video pixels (kept inside the picture).
        x, y = self._scene_xy(event.position().toPoint())
        w, h = self._size
        return [min(max(x, 0.0), float(w)), min(max(y, 0.0), float(h))]

    def _tolerance(self) -> float:
        # How close (in video pixels) a click must be to grab a drawing:
        # 8 pixels on screen, whatever the zoom.
        scale = self.transform().m11() or 1.0
        return 8.0 / scale

    # --- selecting and moving drawings --------------------------------------
    def select(self, did: Optional[str]):
        if did != self.layer.selected:
            self.layer.select(did)
            self.selectionChanged.emit()

    def _pointer_cursor(self, event):
        if self.tool or self.crop_mode or self._size is None or self._drag:
            return
        over = self.layer.at(self._scene_xy(event.position().toPoint()), self._tolerance())
        self.viewport().setCursor(Qt.CursorShape.SizeAllCursor if over else Qt.CursorShape.ArrowCursor)

    def _video_width(self) -> float:
        # The chosen on-screen thickness, in video pixels at the current zoom.
        scale = self.transform().m11() or 1.0
        return round(settings.drawing.line_width / scale, 2)

    def _current_drawing(self, event=None):
        shift = bool(event and event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        return drawings.build(self.tool, self._stroke, self.frame or 0, self.colour,
                              self._video_width(), circle=shift, style=self.line_style)

    def _show_preview(self, d):
        if self._preview is not None:
            self._scene.removeItem(self._preview)
            self._preview = None
        if d is not None:
            self._preview = make_item(d)
            self._preview.setZValue(Z_DRAWINGS + 1)
            self._scene.addItem(self._preview)

    def _cancel_stroke(self):
        self._stroke = None
        self._show_preview(None)

    def reset_crop(self):
        self.crop = None
        self.fit()
        self.cropChanged.emit()

    # --- mouse --------------------------------------------------------------
    def wheelEvent(self, event):
        n = self._wheel.steps(event)
        if n:
            self.stepRequested.emit(n)
        event.accept()

    def mousePressEvent(self, event):
        self.clicked.emit()
        left = event.button() == Qt.MouseButton.LeftButton
        if self.crop_mode and left:
            self._band_origin = event.position().toPoint()
            self._band.setGeometry(QRect(self._band_origin, QSize()))
            self._band.show()
            event.accept()
            return
        if self.tool and left and self._size is not None:
            self.drawingStarted.emit()
            self._stroke = [self._video_point(event)]
            event.accept()
            return
        if left and self._size is not None:
            # No tool: click a drawing to select it (and drag to move it);
            # click anywhere else to deselect.
            point = self._scene_xy(event.position().toPoint())
            d = self.layer.at(point, self._tolerance())
            self.select(d.id if d else None)
            if d is not None:
                self.editStarted.emit()
                self._drag = (point, [list(p) for p in d.points], False)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._band_origin is not None:
            self._band.setGeometry(QRect(self._band_origin, event.position().toPoint()).normalized())
            event.accept()
            return
        if self._stroke is not None:
            self._stroke.append(self._video_point(event))
            self._show_preview(self._current_drawing(event))
            event.accept()
            return
        if self._drag is not None:
            start, original, _moved = self._drag
            x, y = self._scene_xy(event.position().toPoint())
            d = self.layer.selected_drawing()
            if d is not None:
                d.points = [list(p) for p in original]
                drawings.move(d, x - start[0], y - start[1])
                self.layer.redraw(d.id)
                self._drag = (start, original, (x, y) != tuple(start))
            event.accept()
            return
        self._pointer_cursor(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            moved = self._drag[2]
            self._drag = None
            self.editFinished.emit(moved)
            event.accept()
            return
        if self._stroke is not None:
            self._stroke.append(self._video_point(event))
            d = self._current_drawing(event)
            self._cancel_stroke()
            if d is not None:
                self.drawingFinished.emit(d)
            event.accept()
            return
        if self._band_origin is None:
            super().mouseReleaseEvent(event)
            return
        box = self._band.geometry()
        self._band.hide()
        self._band_origin = None
        self.set_crop_mode(False)
        if box.width() > 8 and box.height() > 8:
            area = self.mapToScene(box).boundingRect().intersected(self.sceneRect())
            if area.width() > 4 and area.height() > 4:
                self.crop = area
                self.fit()
        self.cropChanged.emit()
        event.accept()


class VideoPane(QFrame):
    # A PaneView plus, in split view, a header (✕ and name) and, for a clip,
    # its own coloured sync bar for lining it up with the other clips.
    # A board has no timeline: it shows the same picture whatever the frame,
    # so its drawings (Quick and Hold) stay until they're cleared.

    activated = Signal()          # clicked: make this the selected pane
    addRequested = Signal()       # its "+" was clicked, or "Replace…": choose a clip or board
    removeClipRequested = Signal()  # ✕ on a view with a clip or board: empty it (shows "+")
    closeRequested = Signal()       # ✕ on an empty view: close the view
    stepRequested = Signal(int)   # scrolled over the picture: move all clips
    syncScrubbed = Signal(int)    # its own bar dragged to this frame
    syncStepped = Signal(int)     # scrolled over its own bar: nudge this clip only

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.setObjectName("pane")
        self.clip: Optional[ClipInfo] = None
        self.source: Optional[FrameSource] = None
        self.board: Optional[BoardInfo] = None
        self._shown: Optional[int] = None
        self._active = False
        self._split = False
        self._pending_crop: Optional[list] = None

        self.view = PaneView()
        self.view.stepRequested.connect(self.stepRequested.emit)
        self.view.clicked.connect(self.activated.emit)
        self.view.layer.changed = self.update_clear_button

        # Empty view: a big "+" to add a clip
        self.add_btn = QToolButton()
        self.add_btn.setText("+")
        self.add_btn.setFixedSize(110, 110)
        self.add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.add_btn.setToolTip("Add a clip from this project or the full library, or a board")
        self.add_btn.setStyleSheet(
            "QToolButton { color: #8a8a92; background: transparent; font-size: 48pt;"
            " border: 2px dashed #4a4a52; border-radius: 10px; }"
            "QToolButton:hover { color: #f2f2f5; border-color: #8a8a92; }")
        self.add_btn.clicked.connect(lambda _c=False: self.addRequested.emit())
        add_label = QLabel("Add a clip or board")
        add_label.setStyleSheet("color: #8a8a92;")
        add_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder = QFrame()
        self.placeholder.setStyleSheet("QFrame { background: #101012; }")
        pl = QVBoxLayout(self.placeholder)
        pl.addStretch()
        pl.addWidget(self.add_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        pl.addWidget(add_label)
        pl.addStretch()

        self.stack = QStackedWidget()
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.placeholder)
        self.stack.setCurrentWidget(self.placeholder)

        # Header (split view only)
        self.close_btn = QToolButton()
        self.close_btn.setIcon(icon("close"))
        self.close_btn.setIconSize(QSize(12, 12))
        self.close_btn.setAutoRaise(True)
        self.close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_btn.clicked.connect(lambda _c=False: self._close_clicked())
        self.name = QLabel()
        self.header = QFrame()
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(2, 0, 4, 0)
        hl.addWidget(self.close_btn)
        hl.addWidget(self.name, 1)

        # Sync bar (split view only)
        self.sync_bar = TimelineSlider(lambda n: self.syncStepped.emit(n))
        self.sync_bar.setToolTip("Drag to line this clip up with the others.\n"
                                 "Scroll over the bar to nudge it a frame at a time.")
        self.sync_bar.valueChanged.connect(self.syncScrubbed.emit)
        self.sync_label = QLabel("—")
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.sync_label.setFont(mono)
        self.sync_label.setStyleSheet("color: #a0a0a8;")
        self.sync_row = QFrame()
        sl = QHBoxLayout(self.sync_row)
        sl.setContentsMargins(6, 4, 6, 2)
        sl.addWidget(self.sync_bar, 1)
        sl.addWidget(self.sync_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        layout.addWidget(self.header)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.sync_row)

        self.set_index(index)
        self.set_split(False)
        self._update_close_tip()

    # --- appearance ---------------------------------------------------------
    def set_index(self, index: int):
        self.index = index
        self.colour = PANE_COLOURS[index]
        self.sync_bar.setStyleSheet(slider_style(self.colour))
        self._update_border()

    def set_split(self, on: bool):
        self._split = on
        self.header.setVisible(on)
        self.sync_row.setVisible(on and self.board is None)  # boards have no timeline
        self._update_border()

    @property
    def has_content(self) -> bool:
        return self.clip is not None or self.board is not None

    @property
    def item(self):
        return self.clip or self.board

    def set_active(self, on: bool):
        self._active = on
        self._update_border()
        self.update_clear_button()

    def update_clear_button(self):
        # Only on the selected view, and only when it has drawings showing.
        show = self._active and self.has_content and bool(self.view.layer.visible())
        if show != self.view.clear_btn.isVisible():
            self.view.clear_btn.setVisible(show)
            if show:
                self.view.place_clear_button()

    def _close_clicked(self):
        # First ✕ empties the view; ✕ on an empty view closes it.
        if self.has_content:
            self.removeClipRequested.emit()
        else:
            self.closeRequested.emit()

    def _update_close_tip(self):
        tip = ("Remove this board from the view" if self.board is not None
               else "Remove this clip from the view" if self.clip is not None
               else "Close this view")
        self.close_btn.setToolTip(tip)

    def _update_border(self):
        colour = self.colour if (self._split and self._active) else "transparent"
        self.setStyleSheet(f"QFrame#pane {{ border: 2px solid {colour}; border-radius: 3px; }}")

    # --- clip ---------------------------------------------------------------
    def load(self, clip: ClipInfo, source: FrameSource, crop: Optional[list] = None,
             saved_drawings: Optional[list] = None):
        self.clip = clip
        self.source = source
        self.board = None
        self._shown = None
        # Start clean: picture, zoom and drawings (the view may have shown a
        # board or another clip of the same size, with a zoom of its own).
        self.view.clear()
        self.view.layer.load(saved_drawings or [])
        self._pending_crop = crop  # applied once the first frame (and its size) is shown
        self.name.setText(clip.name)
        self.name.setToolTip(clip.name)
        self._update_close_tip()
        self.sync_bar.blockSignals(True)
        self.sync_bar.setRange(0, source.frame_count - 1)
        self.sync_bar.setPageStep(max(1, round(source.fps)))
        self.sync_bar.blockSignals(False)
        self.sync_bar.setEnabled(True)
        self.sync_row.setVisible(self._split)
        self.stack.setCurrentWidget(self.view)

    def load_board(self, board: BoardInfo, picture, crop: Optional[list] = None,
                   saved_drawings: Optional[list] = None):
        # Show a board. `picture`: its RGB image (core.boards.load_image).
        self.clip = None
        self.source = None
        self.board = board
        self._shown = None
        self.view.clear()
        self.view.layer.load(saved_drawings or [])
        self.view.set_frame(picture)
        if crop:
            self.view.crop = QRectF(*crop)
            self.view.fit()
        self._pending_crop = None
        # A board is one picture: everything on it lives on "frame 0".
        self.view.frame = 0
        self.view.layer.set_frame(0, 0)
        self.name.setText(f"{board.name}  (board)")
        self.name.setToolTip(board.name)
        self._update_close_tip()
        self.sync_bar.blockSignals(True)
        self.sync_bar.setRange(0, 0)
        self.sync_bar.blockSignals(False)
        self.sync_bar.setEnabled(False)
        self.sync_row.setVisible(False)
        self.stack.setCurrentWidget(self.view)
        self.update_clear_button()

    def unload(self):
        self.clip = None
        self.source = None
        self.board = None
        self._shown = None
        self.view.clear()
        self.view.set_crop_mode(False)
        self.name.setText("")
        self.sync_label.setText("—")
        self.sync_bar.blockSignals(True)
        self.sync_bar.setRange(0, 0)
        self.sync_bar.blockSignals(False)
        self.sync_bar.setEnabled(False)
        self.sync_row.setVisible(self._split)
        self.stack.setCurrentWidget(self.placeholder)
        self._update_close_tip()
        self.update_clear_button()

    def show_frame(self, n: Optional[int]):
        if self.source is None or n is None:
            return
        if n != self._shown:
            self._shown = n
            self.view.set_frame(self.source.frame(n))
            if self._pending_crop:
                self.view.crop = QRectF(*self._pending_crop)
                self.view.fit()
                self._pending_crop = None
        self.view.frame = n
        self.view.layer.set_frame(n, drawings.hold_frames(settings.drawing.hold_seconds,
                                                          self.source.fps))
        self.sync_bar.blockSignals(True)
        self.sync_bar.setValue(n)
        self.sync_bar.blockSignals(False)
        self.sync_label.setText(f"{self.source.timecode(n)}  {n + 1}")

    def mousePressEvent(self, event):
        self.activated.emit()
        super().mousePressEvent(event)

    def crop_list(self) -> Optional[list]:
        # Current zoom as [x, y, width, height] in video pixels, for saving.
        if self._pending_crop:
            return list(self._pending_crop)
        c = self.view.crop
        return None if c is None else [round(c.x(), 1), round(c.y(), 1),
                                       round(c.width(), 1), round(c.height(), 1)]
