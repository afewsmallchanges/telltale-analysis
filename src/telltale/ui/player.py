# player.py
# The player screen:
#
#   +---------+---------------------------+--------------+
#   | Tools   |  video area: 1-4 views    | Clip Library |
#   | jog     |           [crop][split] ▲ |              |
#   +---------+---------------------------+              |
#   |transport|  main timeline            |      +       |
#   +---------+---------------------------+--------------+
#
# In split view every clip moves together (main timeline, jog wheel, arrow
# keys, play); each clip's own coloured bar sets its sync point. The maths
# is in core/sync.py. A board takes no part in the timeline, but can be zoomed and drawn on.

from __future__ import annotations

from fractions import Fraction
from typing import Optional

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QWidget,
    QWidgetAction,
)

from .. import settings
from ..core.boards import BoardInfo, load_image
from ..core.clip import ClipInfo
from ..core.frames import FrameSource
from ..core.projects import DEFAULT_LAYOUTS, Scene, SceneSlot, valid_layout
from ..core import timer as timer_mod
from ..core.sync import SyncGroup
from .icons import ICON_PX, icon
from .layout_picker import LayoutPicker
from .side_panels import PANEL_WIDTH, ScenesPanel, ToolsPanel
from .video_pane import VideoPane
from .wheel import TimelineSlider

MAX_VIEWS = 4
MAIN_BAR_COLOUR = "#7a2cf0"
SPEEDS = [("1×", 1.0), ("½×", 0.5), ("¼×", 0.25), ("⅒×", 0.1)]
BOX_STYLE = "QFrame#box { border: 1px solid #4a4a52; border-radius: 5px; }"


SAVE_DELAY_MS = 800  # scene changes are saved this long after the last change


class PlayerScreen(QWidget):
    activeClipChanged = Signal()   # the selected view now shows a different clip (or none)
    drawingSelectionChanged = Signal()  # a drawing was selected / deselected
    addClipRequested = Signal(int) # a view's "+" was clicked
    saveRequested = Signal()       # the scene changed (sent after a short pause)
    historyChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.sync = SyncGroup(MAX_VIEWS)
        self.rows, self.cols = 1, 1     # layout of the views
        self.views_shown = 1            # = rows × cols
        self.active = 0
        self.speed = 1.0
        self._jog_last: Optional[tuple[int, int]] = None   # (lead view, its position) last shown
        self._from_jog = False
        # Timer: mode ("dn" / "up" / "du") and its zero on the scene clock
        self.timer_mode: Optional[str] = None
        self.timer_zero = Fraction(0)

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)

        # Saving: a scene is saved shortly after it stops changing.
        self.saving = False            # True while a scene (not a quick view) is open
        self._loading = False
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(lambda: self.saveRequested.emit())

        # --- side panels ----------------------------------------------------
        self.tools = ToolsPanel()
        self.tools.jog.stepRequested.connect(self._jog_step)
        self.tools.jog.pressed.connect(self.pause)
        self.tools.toolChanged.connect(self._tool_changed)
        self.tools.modeChanged.connect(lambda m: settings.set_ui_value("draw/mode", m))
        self.tools.colourChanged.connect(self._colour_changed)
        self.tools.styleChanged.connect(self._style_changed)
        
        self.tools.undoRequested.connect(self.undo_drawing)
        self.tools.redoRequested.connect(self.redo_drawing)
        # Undo for drawings: each entry holds how the affected views' drawings
        # looked just before a change (add, move, delete, restyle, clear).
        # Undoing moves an entry to _redo (holding how they looked before the
        # undo); any new change clears _redo.
        self._undo: list[list[tuple[VideoPane, object]]] = []
        self._redo: list[list[tuple[VideoPane, object]]] = []        
        self.scenes_panel = ScenesPanel()


        # --- video area -----------------------------------------------------
        self.video_area = QWidget()
        self.grid = QGridLayout(self.video_area)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        self.panes: list[VideoPane] = []
        for i in range(MAX_VIEWS):
            pane = VideoPane(i)
            # Panes can change position when one is closed, so look them up.
            pane.activated.connect(lambda p=pane: self.set_active(self.panes.index(p)))
            pane.addRequested.connect(lambda p=pane: self._add_clicked(self.panes.index(p)))
            pane.closeRequested.connect(lambda p=pane: self.close_view(self.panes.index(p)))
            pane.removeClipRequested.connect(lambda p=pane: self.remove_clip(self.panes.index(p)))
            pane.view.clearRequested.connect(lambda p=pane: self.clear_view_drawings(p))
            pane.view.contextRequested.connect(lambda pos, p=pane: self._view_menu(p, pos))
            pane.view.selectionChanged.connect(lambda p=pane: self._selection_changed(p))
           # commented for undo/redo testing
           # pane.view.editStarted.connect(lambda p=pane: self._push_undo([p]))
            pane.view.editStarted.connect(lambda p=pane: self._push_undo([p], keep_redo=True))
            pane.view.editFinished.connect(lambda moved, p=pane: self._edit_finished(p, moved))
            pane.stepRequested.connect(self.step)
            pane.syncScrubbed.connect(lambda f, p=pane: self.scrub_view(self.panes.index(p), f))
            pane.syncStepped.connect(lambda n, p=pane: self.nudge_view(self.panes.index(p), n))
            pane.view.cropChanged.connect(self._crop_changed)
            pane.view.drawingStarted.connect(self.pause)
            pane.view.drawingFinished.connect(lambda d, p=pane: self._drawing_finished(p, d))
            self.panes.append(pane)

        # Crop and split buttons, floating in the video area's top-right corner
        # Timer readout on the video (optional), top-left
        self.timer_badge = QLabel(self.video_area)
        self.timer_badge.setObjectName("timerBadge")
        badge_font = QFont("monospace")
        badge_font.setStyleHint(QFont.StyleHint.Monospace)
        badge_font.setPointSize(18)
        badge_font.setBold(True)
        self.timer_badge.setFont(badge_font)
        self.timer_badge.setStyleSheet(
            "QLabel#timerBadge { color: white; background: rgba(0, 0, 0, 160);"
            " border-left: 4px solid #ff6a00; border-radius: 5px; padding: 3px 10px; }")
        self.timer_badge.hide()

        self.overlay = QFrame(self.video_area)
        self.overlay.setObjectName("overlay")
        self.overlay.setStyleSheet("QFrame#overlay { background: rgba(0, 0, 0, 150); border-radius: 5px; }")
        self.crop_btn = QToolButton()
        self.crop_btn.setIcon(icon("crop"))
        self.crop_btn.setCheckable(True)
        self.crop_btn.clicked.connect(lambda _c=False: self._crop_clicked())
        self.split_btn = QToolButton()
        self.split_btn.setIcon(icon("split"))
        self.split_btn.setToolTip("Split view: compare up to 4 clips")
        self.split_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.split_menu = QMenu(self.split_btn)
        self.layout_picker = LayoutPicker()
        self.layout_picker.chosen.connect(self._layout_chosen)
        picker_action = QWidgetAction(self.split_menu)
        picker_action.setDefaultWidget(self.layout_picker)
        self.split_menu.addAction(picker_action)
        self.split_btn.setMenu(self.split_menu)
        ol = QHBoxLayout(self.overlay)
        ol.setContentsMargins(3, 3, 3, 3)
        ol.setSpacing(2)
        for b in (self.crop_btn, self.split_btn):
            b.setAutoRaise(True)
            b.setIconSize(QSize(18, 18))
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            ol.addWidget(b)
        self.video_area.installEventFilter(self)

        # --- transport (bottom left) ----------------------------------------
        self.icon_play = icon("play")
        self.icon_pause = icon("pause")

        def button(ico, tip, slot):
            b = QToolButton()
            b.setIcon(ico)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _c=False: slot())
            b.setIconSize(QSize(ICON_PX, ICON_PX))
            b.setFixedSize(ICON_PX + 10, ICON_PX + 10)
            return b

        self.btn_start = button(icon("first"), "Start (Home)", self.to_start)
        self.btn_back = button(icon("step_back"), "Back one frame (←, scroll, jog wheel)", lambda: self.step(-1))
        self.btn_play = button(self.icon_play, "Play / pause (Space)", self.toggle_play)
        self.btn_fwd = button(icon("step_fwd"), "Forward one frame (→, scroll, jog wheel)", lambda: self.step(1))
        self.btn_end = button(icon("last"), "End (End)", self.to_end)
        self.transport_buttons = [self.btn_start, self.btn_back, self.btn_play, self.btn_fwd, self.btn_end]

        transport = QFrame()
        transport.setObjectName("box")
        transport.setStyleSheet(BOX_STYLE)
        transport.setFixedWidth(PANEL_WIDTH)
        tl = QHBoxLayout(transport)
        tl.setContentsMargins(4, 6, 4, 6)
        tl.setSpacing(0)
        tl.addStretch()
        for b in self.transport_buttons:
            tl.addWidget(b)
        tl.addStretch()

        # --- main timeline (bottom centre) ----------------------------------
        self.main_bar = TimelineSlider(self.step, colour=MAIN_BAR_COLOUR, thick=True)
        self.main_bar.set_bar_tip("Main timeline: moves every clip together")
        self.main_bar.markerMoved.connect(self._timer_flag_moved)
        self.main_bar.valueChanged.connect(self._main_bar_moved)

        self.speed_box = QComboBox()
        self.speed_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.speed_box.setToolTip("Playback speed")
        for label, value in SPEEDS:
            self.speed_box.addItem(label, value)
        self.speed_box.currentIndexChanged.connect(self._speed_changed)

        self.readout = QLabel("—")
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.readout.setFont(mono)
        self.readout.setMinimumWidth(230)
        self.readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        bar_box = QFrame()
        bar_box.setObjectName("box")
        bar_box.setStyleSheet(BOX_STYLE)
        bl = QHBoxLayout(bar_box)
        bl.setContentsMargins(12, 6, 10, 6)
        bl.addWidget(self.main_bar, 1)
        bl.addSpacing(8)
        bl.addWidget(self.speed_box)
        bl.addWidget(self.readout)

        # --- put it together ------------------------------------------------
        g = QGridLayout(self)
        g.setContentsMargins(8, 8, 8, 8)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        g.addWidget(self.tools, 0, 0)
        g.addWidget(transport, 1, 0)
        g.addWidget(self.video_area, 0, 1)
        g.addWidget(bar_box, 1, 1)
        g.addWidget(self.scenes_panel, 0, 2, 2, 1)
        g.setColumnStretch(1, 1)
        g.setRowStretch(0, 1)

        self._build_timer_menu()
        self._relayout()
        self.tools.set_mode(str(settings.ui_value("draw/mode", "quick")))
        self.tools.set_style(str(settings.ui_value("draw/style", "solid")))
        self.tools.set_colour(str(settings.ui_value("draw/colour", "#ff3b30")))
        self.refresh()

    # --- what's showing -----------------------------------------------------
    def lead(self) -> Optional[int]:
        # The clip the timeline counts in: the selected view, else the first loaded.
        if self.sync.tracks[self.active] is not None:
            return self.active
        loaded = [i for i in self.sync.loaded() if i < self.views_shown]
        return loaded[0] if loaded else None

    def has_clip(self) -> bool:
        return bool(self.sync.loaded())

    def has_content(self) -> bool:
        return any(p.has_content for p in self.panes[:self.views_shown])

    def active_clip(self) -> Optional[ClipInfo]:
        return self.panes[self.active].clip

    def active_item(self):
        return self.panes[self.active].item

    # --- scenes -------------------------------------------------------------
    def clear(self):
        # Empty everything: one empty view.
        self.pause()
        self.save_timer.stop()
        self.saving = False
        for pane in self.panes:
            pane.unload()
        self.sync.clear()
        self._undo.clear()
        self._redo.clear()
        self._history_changed()
        self.rows, self.cols, self.views_shown = 1, 1, 1
        self.active = 0
        self._jog_last = None
        self.timer_mode = None
        self._relayout()
        self.refresh()
        self.activeClipChanged.emit()

    def load_scene(self, scene: Scene, clips: dict[str, ClipInfo],
                   boards: Optional[dict[str, BoardInfo]] = None):
        # Show a saved scene: its views, clips, boards, sync, zoom and position.
        # `clips` / `boards`: the libraries by id (missing ones show as empty views).
        self.clear()
        self._loading = True
        self.rows, self.cols = scene.rows, scene.cols
        self.views_shown = scene.rows * scene.cols
        self.sync.time = Fraction(scene.time)
        for i, slot in enumerate(scene.slots[:MAX_VIEWS]):
            if slot is not None and slot.is_board:
                board = (boards or {}).get(slot.board_id)
                if board is not None:
                    self._show_board(i, board, crop=slot.crop, saved_drawings=slot.drawings)
                continue
            info = clips.get(slot.clip_id) if slot else None
            if info is None:
                continue
            self.sync.load(i, info.rate, info.frame_count, offset=Fraction(slot.offset))
            self.panes[i].load(info, FrameSource(info, cache_mb=160), crop=slot.crop, saved_drawings=slot.drawings)
        self.sync.seek(self.sync.time)  # keep it within the clips
        self.active = min(scene.active, self.views_shown - 1)
        saved_timer = timer_mod.parse(scene.timer)
        self.timer_mode, self.timer_zero = saved_timer if saved_timer else (None, Fraction(0))
        self._relayout()
        self.refresh()
        self._loading = False
        self.saving = True
        self.activeClipChanged.emit()

    def fill_scene(self, scene: Scene):
        # Copy what's on screen into `scene` (for saving).
        scene.rows, scene.cols, scene.views = self.rows, self.cols, self.views_shown
        scene.slots = []
        for i in range(self.views_shown):
            pane = self.panes[i]
            off = self.sync.offset(i)
            if pane.board is not None:
                scene.slots.append(SceneSlot(board_id=pane.board.id, crop=pane.crop_list(), drawings=list(pane.view.layer.hold)))
            elif pane.clip and off is not None:
                scene.slots.append(SceneSlot(clip_id=pane.clip.id, offset=str(off), crop=pane.crop_list(), drawings=list(pane.view.layer.hold)))
            else:
                scene.slots.append(None)
        scene.time = str(self.sync.time)
        scene.active = self.active
        scene.timer = ({"mode": self.timer_mode, "zero": str(self.timer_zero)} if self.timer_mode else None)

    def _changed(self):
        if self.saving and not self._loading:
            self.save_timer.start(SAVE_DELAY_MS)

    def flush_save(self):
        # Save now if a save is waiting (e.g. before leaving the scene).
        if self.save_timer.isActive():
            self.save_timer.stop()
            self.saveRequested.emit()

    def open_slots(self) -> list[int]:
        return [i for i in range(self.views_shown) if not self.panes[i].has_content]

    # --- loading clips ------------------------------------------------------
    def load_clip(self, info: ClipInfo, index: Optional[int] = None):
        # Show `info` in view `index` (default: the selected view).
        i = self.active if index is None else index
        if i >= self.views_shown:
            return
        if i != self.active:
            self.set_active(i)
        pane = self.panes[i]
        if pane.clip and pane.clip.id == info.id:
            return
        self.pause()
        self._forget_undo(pane)
        self.sync.load(i, info.rate, info.frame_count)
        pane.load(info, FrameSource(info, cache_mb=160))
        self.refresh()
        self.activeClipChanged.emit()

    def load_board(self, board: BoardInfo, index: Optional[int] = None):
        # Show `board` in view `index` (default: the selected view).
        i = self.active if index is None else index
        if i >= self.views_shown:
            return
        if i != self.active:
            self.set_active(i)
        pane = self.panes[i]
        if pane.board and pane.board.id == board.id:
            return
        self.pause()
        self._forget_undo(pane)
        self._show_board(i, board)
        self.refresh()
        self.activeClipChanged.emit()

    def _show_board(self, i: int, board: BoardInfo, crop: Optional[list] = None, saved_drawings: Optional[list] = None):
        if self.sync.tracks[i] is not None:
            self.sync.unload(i)  # a board has no place on the timeline
        try:
            picture = load_image(board)
        except OSError:
            self.panes[i].unload()
            return
        self.panes[i].load_board(board, picture, crop=crop, saved_drawings=saved_drawings)

    def _add_clicked(self, i: int):
        self.set_active(i)
        self.addClipRequested.emit(i)

    def _crop_changed(self):
        self._update_overlay()
        self._changed()

    def _unload(self, i: int):
        self.panes[i].unload()
        self.sync.unload(i)

    def unload_clips(self, ids: list[str]):
        # Clips deleted from the library: stop showing them.
        self._unload_where(lambda pane: pane.clip is not None and pane.clip.id in ids)

    def unload_boards(self, ids: list[str]):
        # Boards deleted: stop showing them.
        self._unload_where(lambda pane: pane.board is not None and pane.board.id in ids)

    def _unload_where(self, test):
        changed = False
        for i, pane in enumerate(self.panes):
            if test(pane):
                self._forget_undo(pane)
                self._unload(i)
                changed = True
        if changed:
            self.pause()
            self.refresh()
            self.activeClipChanged.emit()

    # --- views --------------------------------------------------------------
    def set_view_count(self, n: int):
        # 1-4 views in their usual layout (Ctrl+Shift+1…4).
        n = max(1, min(MAX_VIEWS, n))
        self.set_layout(*DEFAULT_LAYOUTS[n])

    def _layout_chosen(self, rows: int, cols: int):
        self.split_menu.close()
        self.set_layout(rows, cols)

    def set_layout(self, rows: int, cols: int):
        # Arrange the views in rows × columns (up to 4 views). Clips in views
        # that no longer fit are taken out; the others stay as they were.
        if not valid_layout(rows, cols) or (rows, cols) == (self.rows, self.cols):
            return
        self.pause()
        old = self.views_shown
        n = rows * cols
        for i in range(n, MAX_VIEWS):
            if self.panes[i].has_content:
                self._unload(i)
        self.rows, self.cols, self.views_shown = rows, cols, n
        # Adding views: select the first new (empty) one, ready for a clip.
        self.active = old if n > old else min(self.active, n - 1)
        self._relayout()
        self.refresh()
        self.activeClipChanged.emit()

    def remove_clip(self, i: int):
        # Empty view i (it shows "+" again). Its drawings go with the clip or board.
        if not self.panes[i].has_content:
            return
        self.pause()
        self._unload(i)
        self._forget_undo(self.panes[i])
        self.refresh()
        self.activeClipChanged.emit()

    def close_view(self, i: int):
        if self.views_shown == 1:
            self.remove_clip(0)
            return
        self.pause()
        pane = self.panes.pop(i)
        self._forget_undo(pane)
        pane.unload()
        self.panes.append(pane)
        self.sync.remove_slot(i)
        n = self.views_shown - 1
        # Keep a single row / single column shape; otherwise the usual layout.
        if self.rows == 1:
            self.rows, self.cols = 1, n
        elif self.cols == 1:
            self.rows, self.cols = n, 1
        else:
            self.rows, self.cols = DEFAULT_LAYOUTS[n]
        self.views_shown = n
        if self.active > i or self.active >= n:
            self.active = max(0, self.active - 1)
        self._relayout()
        self.refresh()
        self.activeClipChanged.emit()

    def _view_menu(self, pane: VideoPane, pos):
        # Right-click on a view.
        i = self.panes.index(pane)
        self.set_active(i)
        menu = QMenu(self)
        if pane.has_content:
            what = "board" if pane.board is not None else "clip"
            menu.addAction("Replace…").triggered.connect(lambda _c=False: self._add_clicked(i))
            menu.addAction(f"Remove {what}").triggered.connect(lambda _c=False: self.remove_clip(i))
        else:
            menu.addAction("Add clip or board…").triggered.connect(lambda _c=False: self._add_clicked(i))
        if self.views_shown > 1:
            menu.addSeparator()
            menu.addAction("Close view").triggered.connect(lambda _c=False: self.close_view(i))
        if pane.view.layer.selected_drawing() is not None:
            menu.addSeparator()
            menu.addAction("Delete drawing").triggered.connect(
                lambda _c=False: self.delete_selected_drawing())
        if pane.view.layer.visible():
            if pane.view.layer.selected_drawing() is None:
                menu.addSeparator()
            menu.addAction("Clear drawings here").triggered.connect(
                lambda _c=False: self.clear_view_drawings(pane))
        menu.exec(pos)

    def set_active(self, i: int):
        if i >= self.views_shown or i == self.active:
            return
        self.panes[self.active].view.set_crop_mode(False)
        self.active = i
        for j, pane in enumerate(self.panes):
            pane.set_active(j == i)
        self.refresh()
        self.activeClipChanged.emit()

    def _relayout(self):
        for pane in self.panes:
            self.grid.removeWidget(pane)
            pane.hide()
        for k in range(MAX_VIEWS):
            self.grid.setRowStretch(k, 0)
            self.grid.setColumnStretch(k, 0)
        split = self.views_shown > 1
        for i in range(self.views_shown):
            r, c = divmod(i, self.cols)
            pane = self.panes[i]
            pane.set_index(i)
            pane.set_split(split)
            pane.set_active(i == self.active)
            self.grid.addWidget(pane, r, c)
            self.grid.setRowStretch(r, 1)
            self.grid.setColumnStretch(c, 1)
            pane.show()
        self.layout_picker.set_current(self.rows, self.cols)
        self._place_overlay()

    def eventFilter(self, obj, event):
        if obj is self.video_area and event.type() == QEvent.Type.Resize:
            self._place_overlay()
        return super().eventFilter(obj, event)

    def _place_overlay(self):
        self.overlay.adjustSize()
        self.overlay.move(self.video_area.width() - self.overlay.width() - 6, 6)
        self.overlay.raise_()
        self.timer_badge.adjustSize()
        self.timer_badge.move(6, 6)
        self.timer_badge.raise_()

    # --- drawing ------------------------------------------------------------
    def _tool_changed(self, tool: Optional[str]):
        for pane in self.panes:
            pane.view.set_crop_mode(False)
            pane.view.set_tool(tool)
        self._update_overlay()

    def put_down_tool(self):
        if self.tools.tool is not None:
            self.tools.set_tool(None)

    def _colour_changed(self, colour: str):
        settings.set_ui_value("draw/colour", colour)
        for pane in self.panes:
            pane.view.colour = colour
        self._restyle_selected(colour=colour)

    def _style_changed(self, style: str):
        settings.set_ui_value("draw/style", style)
        for pane in self.panes:
            pane.view.line_style = style
        self._restyle_selected(style=style)

    def _restyle_selected(self, colour: Optional[str] = None, style: Optional[str] = None):
        # Picking a colour or line style while a drawing is selected changes it.
        found = self.selected_drawing()
        if found is None:
            return
        pane, d = found
        if (colour is None or colour == d.colour) and (style is None or style == d.style):
            return
        self._push_undo([pane])
        if colour is not None:
            d.colour = colour
        if style is not None:
            d.style = style
        pane.view.layer.redraw(d.id)
        if pane.view.layer.is_saved(d.id):
            self._changed()

    def _drawing_finished(self, pane: VideoPane, d):
        quick = self.tools.mode == "quick"
        self._push_undo([pane])
        pane.view.layer.add(d, quick=quick)
        if not quick:
            self._changed()

    def clear_view_drawings(self, pane: VideoPane):
        # "Clear Drawings": remove the drawings on screen now in this view.
        if not pane.view.layer.visible():
            return
        self._push_undo([pane])
        if pane.view.layer.clear_visible():
            self._changed()

    # --- selected drawing ---------------------------------------------------
    def selected_drawing(self):
        # (view, drawing) of the selected drawing, if any.
        for pane in self.panes[:self.views_shown]:
            d = pane.view.layer.selected_drawing()
            if d is not None:
                return pane, d
        return None

    def _selection_changed(self, pane: VideoPane):
        # One selected drawing at a time, across all views.
        d = pane.view.layer.selected_drawing()
        if d is not None:
            for other in self.panes:
                if other is not pane:
                    other.view.select(None)
            self.set_active(self.panes.index(pane))
            # Show its colour and style on the panel (picking another changes it).
            self.tools.set_colour(d.colour)
            self.tools.set_style(d.style)
        self.drawingSelectionChanged.emit()

    def deselect_drawing(self) -> bool:
        found = self.selected_drawing()
        if found:
            found[0].view.select(None)
        return found is not None

    def delete_selected_drawing(self) -> bool:
        found = self.selected_drawing()
        if found is None:
            return False
        pane, d = found
        self._push_undo([pane])
        saved = pane.view.layer.is_saved(d.id)
        pane.view.layer.remove(d.id)
        if saved:
            self._changed()
        self.drawingSelectionChanged.emit()
        return True

    def _edit_finished(self, pane: VideoPane, moved: bool):
        if not moved:
            if self._undo:
                self._undo.pop()  # just a click: nothing to undo
                self._history_changed()
            return
        self._redo.clear()  # a real change
        self._history_changed()
            
            # if self._undo:
            #     self._undo.pop()  # just a click: nothing to undo
            # return
        d = pane.view.layer.selected_drawing()
        if d is not None and pane.view.layer.is_saved(d.id):
            self._changed()

    # --- undo ---------------------------------------------------------------
    # def _push_undo(self, panes: list[VideoPane]):
    #     self._undo.append([(p, p.view.layer.snapshot()) for p in panes])
    #     del self._undo[:-50]  # keep the last 50 steps

    # def _forget_undo(self, pane: VideoPane):
    #     # The view's clip changed: its old drawings can't come back.
    #     self._undo = [e for e in self._undo if all(p is not pane for p, _snap in e)]

    def _push_undo(self, panes: list[VideoPane], keep_redo: bool = False):
        self._undo.append([(p, p.view.layer.snapshot()) for p in panes])
        del self._undo[:-50]  # keep the last 50 steps
        if not keep_redo:
            self._redo.clear()  # a new change: what was undone can't be redone
        self._history_changed()

    def _forget_undo(self, pane: VideoPane):
        # The view's clip changed: its old drawings can't come back.
        self._undo = [e for e in self._undo if all(p is not pane for p, _snap in e)]
        self._redo = [e for e in self._redo if all(p is not pane for p, _snap in e)]
        self._history_changed()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def _history_changed(self):
        self.tools.set_history(self.can_undo(), self.can_redo())
        self.historyChanged.emit()

    # --- timer --------------------------------------------------------------
    def _build_timer_menu(self):
        menu = QMenu(self.tools.timer_tool)
        self.timer_actions = {}
        for mode, name in timer_mod.MODE_NAMES.items():
            a = menu.addAction(f"{name}  ({timer_mod.MODES[mode]})")
            a.setCheckable(True)
            a.triggered.connect(lambda _c=False, m=mode: self.start_timer(m))
            self.timer_actions[mode] = a
        menu.addSeparator()
        self.act_timer_zero = menu.addAction("Set zero to this frame  (T)")
        self.act_timer_zero.triggered.connect(lambda _c=False: self.set_timer_zero_here())
        self.act_timer_badge = menu.addAction("Show timer on the video")
        self.act_timer_badge.setCheckable(True)
        self.timer_on_video = _truthy(settings.ui_value("timer/on_video", True))
        self.act_timer_badge.setChecked(self.timer_on_video)
        self.act_timer_badge.triggered.connect(lambda checked=False: self._timer_badge_toggled(checked))
        menu.addSeparator()
        self.act_timer_off = menu.addAction("Turn timer off")
        self.act_timer_off.triggered.connect(lambda _c=False: self.timer_off())
        self.tools.timer_tool.setMenu(menu)

    def start_timer(self, mode: str):
        # Choose DN / UP / D/U. Starting the timer puts its zero at this frame;
        # switching mode keeps the zero where it is.
        if self.lead() is None or mode not in timer_mod.MODES:
            return
        if self.timer_mode is None:
            self.timer_zero = self.sync.time
        self.timer_mode = mode
        settings.set_ui_value("timer/mode", mode)
        self.refresh()

    def set_timer_zero_here(self):
        # T key / menu: zero at the current frame (starts the timer if it's off).
        if self.lead() is None:
            return
        if self.timer_mode is None:
            self.start_timer(str(settings.ui_value("timer/mode", "du")) or "du")
        self.timer_zero = self.sync.time
        self.refresh()

    def timer_off(self):
        self.timer_mode = None
        self.refresh()

    def _timer_flag_moved(self, position: int):
        # The orange flag was dragged to `position` (in the lead clip's frames).
        lead = self.lead()
        if lead is None or self.timer_mode is None:
            return
        self.timer_zero = self.sync.lead_time(lead, position)
        self.refresh()

    def _timer_badge_toggled(self, on: bool):
        self.timer_on_video = bool(on)
        settings.set_ui_value("timer/on_video", self.timer_on_video)
        self.refresh()

    def timer_text(self) -> str:
        if self.timer_mode is None:
            return ""
        return timer_mod.display(self.timer_mode, self.timer_zero, self.sync.time)

    def _update_timer(self, lead: Optional[int]):
        button = self.tools.timer_tool
        active = self.timer_mode is not None and lead is not None
        button.setEnabled(lead is not None)
        button.setChecked(active)
        for mode, a in self.timer_actions.items():
            a.setChecked(mode == self.timer_mode)
        self.act_timer_off.setEnabled(self.timer_mode is not None)
        if not active:
            button.setText("Timer\n—")
            self.main_bar.set_marker(None)
            self.timer_badge.hide()
            return
        label = timer_mod.MODES[self.timer_mode]
        text = self.timer_text()
        button.setText(f"{label}\n{text}")
        zero_at = self.sync.tracks[lead].position(self.timer_zero)
        self.main_bar.set_marker(zero_at, f"Timer zero ({label}) — drag to move it")
        if self.timer_on_video:
            self.timer_badge.setText(f"{label}  {text}")
            self.timer_badge.adjustSize()
            self.timer_badge.show()
            self.timer_badge.raise_()
        else:
            self.timer_badge.hide()

    # --- jog wheel ----------------------------------------------------------
    def _jog_step(self, n: int):
        self._from_jog = True
        try:
            self.step(n)
        finally:
            self._from_jog = False

    def _spin_jog(self, lead: Optional[int]):
        # Turn the jog wheel along with playback and scrubbing (the wheel
        # already turned itself if it did the stepping).
        pos = self.sync.lead_position(lead) if lead is not None else None
        now = (lead, pos) if lead is not None else None
        last = self._jog_last
        if now and last and now[0] == last[0] and not self._from_jog:
            self.tools.jog.spin(now[1] - last[1])
        self._jog_last = now

    def saved_drawing_count(self) -> int:
        return sum(len(self.panes[i].view.layer.hold) for i in range(self.views_shown))

    def clear_all_drawings(self):
        # Edit > Clear All: every drawing in the scene, on every frame (undoable).
        shown = self.panes[:self.views_shown]
        self._push_undo(shown)
        for pane in shown:
            pane.view.layer.clear_all()
        self._changed()

    # commented out while testing undo/redo buttons.
    # def undo_drawing(self) -> bool:
    #     # Put the drawings back how they were before the last change.
    #     if not self._undo:
    #         return False
    #     for pane, snap in self._undo.pop():
    #         pane.view.layer.restore(snap)
    #     self._changed()
    #     self.drawingSelectionChanged.emit()
    #     return True

    def undo_drawing(self) -> bool:
        # Put the drawings back how they were before the last change.
        return self._step_history(self._undo, self._redo)

    def redo_drawing(self) -> bool:
        # Put back a change that was undone.
        return self._step_history(self._redo, self._undo)

    def _step_history(self, source: list, target: list) -> bool:
        # Take the last entry from `source` (undo or redo), first saving how
        # those views look now on `target`, so the step can be reversed.
        if not source:
            return False
        entry = source.pop()
        target.append([(pane, pane.view.layer.snapshot()) for pane, _snap in entry])
        for pane, snap in entry:
            pane.view.layer.restore(snap)
        self._changed()
        self._history_changed()
        self.drawingSelectionChanged.emit()
        return True

    # --- crop / zoom --------------------------------------------------------
    def _crop_clicked(self):
        view = self.panes[self.active].view
        if view.crop is not None:
            view.reset_crop()
        elif view.crop_mode:
            view.set_crop_mode(False)
        else:
            self.pause()
            self.put_down_tool()  # cropping and drawing both use the mouse
            view.set_crop_mode(True)
        self._update_overlay()

    def _update_overlay(self):
        pane = self.panes[self.active]
        view = pane.view
        self.crop_btn.setEnabled(pane.has_content)
        self.crop_btn.setChecked(view.crop_mode or view.crop is not None)
        if view.crop is not None:
            self.crop_btn.setToolTip("Zoomed in — click to show the whole picture")
        elif view.crop_mode:
            self.crop_btn.setToolTip("Drag a box over the picture to zoom into it (click to cancel)")
        else:
            self.crop_btn.setToolTip("Crop / zoom: drag a box over the picture to zoom in")

    # --- moving -------------------------------------------------------------
    def refresh(self):
        # Show the right frame in every view and update the controls.
        for i in range(self.views_shown):
            self.panes[i].show_frame(self.sync.frame(i))
        lead = self.lead()
        has = lead is not None

        self.main_bar.blockSignals(True)
        if has:
            lo, hi = self.sync.lead_bounds(lead)
            self.main_bar.setRange(lo, hi)
            self.main_bar.setPageStep(max(1, round(self.panes[lead].source.fps)))
            self.main_bar.setValue(self.sync.lead_position(lead))
        else:
            self.main_bar.setRange(0, 0)
        self.main_bar.blockSignals(False)

        for w in self.transport_buttons + [self.main_bar, self.speed_box, self.tools.jog]:
            w.setEnabled(has)
        if has:
            s = self.panes[lead].source
            n = self.sync.frame(lead)
            width = len(str(s.frame_count))
            self.readout.setText(f"{s.timecode(n)}   frame {n + 1:>{width}}/{s.frame_count}")
        else:
            self.readout.setText("—")
        self._spin_jog(lead)
        self._update_timer(lead)
        self._update_overlay()
        self._changed()

    def step(self, n: int):
        # Move every clip n frames (of the selected clip).
        self.pause()
        lead = self.lead()
        if lead is not None:
            self.sync.step(n, lead)
            self.refresh()

    def nudge_view(self, i: int, n: int):
        # Move one clip only, changing its sync with the others.
        self.pause()
        if self.sync.tracks[i] is not None:
            self.sync.step_one(i, n)
            self.refresh()

    def nudge_active(self, n: int):
        self.nudge_view(self.active, n)

    def scrub_view(self, i: int, frame: int):
        self.pause()
        if self.sync.tracks[i] is not None:
            self.sync.set_frame(i, frame)
            self.refresh()

    def _main_bar_moved(self, value: int):
        self.pause()
        lead = self.lead()
        if lead is not None:
            self.sync.seek_lead(lead, value)
            self.refresh()

    def to_start(self):
        self.pause()
        self.sync.to_start()
        self.refresh()

    def to_end(self):
        self.pause()
        self.sync.to_end()
        self.refresh()

    # --- playback -----------------------------------------------------------
    def toggle_play(self):
        if self.timer.isActive():
            self.pause()
        else:
            self.play()

    def play(self):
        lead = self.lead()
        if lead is None:
            return
        if self.sync.at_end():
            self.sync.to_start()
        rate = float(self.sync.tracks[lead].rate)
        self.timer.start(max(1, round(1000 / (rate * self.speed))))
        self.btn_play.setIcon(self.icon_pause)

    def pause(self):
        self.timer.stop()
        self.btn_play.setIcon(self.icon_play)

    def _tick(self):
        lead = self.lead()
        if lead is None or self.sync.at_end():
            self.pause()
            return
        self.sync.step(1, lead)
        self.refresh()

    def _speed_changed(self, _index):
        self.speed = float(self.speed_box.currentData())
        if self.timer.isActive():
            self.play()  # restart with the new interval


def _truthy(v) -> bool:
    # QSettings gives booleans back as "true"/"false" strings on some systems.
    return v is True or str(v).lower() in ("true", "1")
