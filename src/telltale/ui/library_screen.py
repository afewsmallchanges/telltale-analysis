# library_screen.py
# The start screen. Left: "All clips", "Boards", then each project. Right:
# for a project, its Scenes and Clips tabs; for All clips, every imported
# clip; for Boards, every imported picture or diagram.
#
# Clips live once in the shared library; projects only list clip ids, so a
# clip can be in several projects. Removing a clip from a project keeps it in
# the library; deleting it from the library removes it everywhere.

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import settings
from ..core import timebase
from ..core.boards import BoardInfo, BoardLibrary
from ..core.clip import ClipInfo
from ..core.library import Library
from ..core.projects import DEFAULT_LAYOUTS, MAX_CLIPS_PER_SCENE, Project, ProjectStore, Scene

ALL_CLIPS = "__all__"           # sidebar entry id for "All clips"
BOARDS = "__boards__"           # sidebar entry id for "Boards"
LIBRARY_ENTRIES = (ALL_CLIPS, BOARDS)
ROLE_ID = Qt.ItemDataRole.UserRole

THUMB_SIZE = QSize(192, 108)    # 16:9 thumbnails
GRID_SIZE = QSize(216, 172)     # thumbnail + two lines of text


# --- formatting -------------------------------------------------------------

def format_bytes(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1000:
            return f"{n:.0f} {unit}" if unit in ("bytes", "KB") else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} TB"


def format_duration(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def scene_summary(scene: Scene) -> str:
    # "2 clips", "1 clip · 1 board", "1 board"…
    n_clips, n_boards = len(scene.clip_ids()), len(scene.board_ids())
    parts = [plural(n_clips, "clip")] if (n_clips or not n_boards) else []
    if n_boards:
        parts.append(plural(n_boards, "board"))
    return " · ".join(parts)


def scene_items(scene: Scene, clips: dict[str, ClipInfo],
                boards: Optional[dict[str, BoardInfo]] = None) -> list:
    # What each of the scene's views shows: ClipInfo, BoardInfo or None.
    boards = boards or {}
    return [None if slot is None
            else boards.get(slot.board_id) if slot.is_board
            else clips.get(slot.clip_id)
            for slot in scene.slots]


# --- thumbnails -------------------------------------------------------------

_thumb_cache: dict[tuple[str, float], QIcon] = {}


def thumb_icon(clip) -> QIcon:
    # A clip's or board's thumbnail (both have .thumb_path).
    path = clip.thumb_path
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        return QIcon()
    icon = _thumb_cache.get(key)
    if icon is None:
        icon = QIcon(QPixmap(str(path)))
        _thumb_cache[key] = icon
    return icon


def scene_icon(clips: list, rows: int = 0, cols: int = 0) -> QIcon:
    # A scene's thumbnail: its clips' (or boards') pictures laid out like its
    # views (rows × cols), with "+" for empty views.
    w, h = THUMB_SIZE.width() * 2, THUMB_SIZE.height() * 2  # drawn at 2x for sharpness
    pm = QPixmap(w, h)
    pm.fill(QColor(16, 16, 18))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if rows * cols != len(clips) or not clips:
        rows, cols = DEFAULT_LAYOUTS[max(1, min(4, len(clips)))]
    for i, clip in enumerate(clips[:rows * cols]):
        r, c = divmod(i, cols)
        cell = QRectF(c * w / cols + 2, r * h / rows + 2, w / cols - 4, h / rows - 4)
        thumb = QPixmap(str(clip.thumb_path)) if clip else QPixmap()
        if not thumb.isNull():
            scaled = thumb.scaled(int(cell.width()), int(cell.height()),
                                  Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int(cell.x() + (cell.width() - scaled.width()) / 2),
                         int(cell.y() + (cell.height() - scaled.height()) / 2), scaled)
        else:
            p.setPen(QPen(QColor(90, 90, 98), 2, Qt.PenStyle.DashLine))
            p.drawRect(cell.adjusted(6, 6, -6, -6))
            f = p.font()
            f.setPixelSize(int(min(cell.width(), cell.height()) * 0.35))
            p.setFont(f)
            p.drawText(cell, Qt.AlignmentFlag.AlignCenter, "+")
    p.end()
    return QIcon(pm)


# --- clip grid --------------------------------------------------------------

class ClipGrid(QListWidget):
    # Thumbnail grid of clips. Used on the start screen and in "Add from library".

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setIconSize(THUMB_SIZE)
        self.setGridSize(GRID_SIZE)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._clips: dict[str, ClipInfo] = {}

    def set_clips(self, clips: list[ClipInfo]):
        keep = {c.id for c in self.selected_clips()}
        self.clear()
        self._clips = {c.id: c for c in clips}
        for c in clips:
            details = (f"{format_duration(c.duration)} · {c.width}×{c.height} · "
                       f"{timebase.format_rate(c.rate)} fps")
            item = QListWidgetItem(thumb_icon(c), f"{c.name}\n{details}")
            item.setData(ROLE_ID, c.id)
            item.setToolTip(
                f"<b>{c.name}</b><br>{details}<br>{plural(c.frame_count, 'frame')}"
                f"{'' if c.has_audio else ' · no audio'}<br>"
                f"Imported {c.imported_at[:16].replace('T', ' ')}<br>"
                f"Original: {c.source}"
            )
            self.addItem(item)
            if c.id in keep:
                item.setSelected(True)

    def clip_for(self, item: QListWidgetItem) -> ClipInfo:
        return self._clips[item.data(ROLE_ID)]

    def selected_clips(self) -> list[ClipInfo]:
        # In grid order, not click order.
        return [self.clip_for(self.item(i)) for i in range(self.count())
                if self.item(i).isSelected() and not self.item(i).isHidden()]

    def selected_items(self) -> list:
        return self.selected_clips()

    def filter(self, text: str):
        text = text.casefold().strip()
        for i in range(self.count()):
            item = self.item(i)
            item.setHidden(bool(text) and text not in self.clip_for(item).name.casefold())


class BoardGrid(QListWidget):
    # Thumbnail grid of boards (pictures and diagrams).

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setIconSize(THUMB_SIZE)
        self.setGridSize(GRID_SIZE)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._boards: dict[str, BoardInfo] = {}

    def set_boards(self, boards: list[BoardInfo]):
        keep = {b.id for b in self.selected_boards()}
        self.clear()
        self._boards = {b.id: b for b in boards}
        for b in boards:
            item = QListWidgetItem(thumb_icon(b), f"{b.name}\n{b.width}×{b.height} · board")
            item.setData(ROLE_ID, b.id)
            item.setToolTip(f"<b>{b.name}</b><br>{b.width}×{b.height} picture<br>"
                            f"Imported {b.imported_at[:16].replace('T', ' ')}<br>"
                            f"Original: {b.source}")
            self.addItem(item)
            if b.id in keep:
                item.setSelected(True)

    def board_for(self, item: QListWidgetItem) -> BoardInfo:
        return self._boards[item.data(ROLE_ID)]

    def selected_boards(self) -> list[BoardInfo]:
        return [self.board_for(self.item(i)) for i in range(self.count())
                if self.item(i).isSelected() and not self.item(i).isHidden()]

    def selected_items(self) -> list:
        return self.selected_boards()

    def filter(self, text: str):
        text = text.casefold().strip()
        for i in range(self.count()):
            item = self.item(i)
            item.setHidden(bool(text) and text not in self.board_for(item).name.casefold())


def _menu_action(menu: QMenu, text: str, slot: Callable[[], object], enabled: bool = True):
    a = menu.addAction(text)
    a.setEnabled(enabled)
    a.triggered.connect(lambda _checked=False: slot())
    return a


# --- start screen -----------------------------------------------------------

SCENES_TAB, CLIPS_TAB = 0, 1


class SceneGrid(QListWidget):
    # Thumbnail grid of a project's scenes.

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setIconSize(THUMB_SIZE)
        self.setGridSize(GRID_SIZE)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._scenes: dict[str, Scene] = {}

    def set_scenes(self, scenes: list[Scene], clips: dict[str, ClipInfo],
                   boards: Optional[dict[str, BoardInfo]] = None):
        keep = {s.id for s in self.selected_scenes()}
        self.clear()
        self._scenes = {s.id: s for s in scenes}
        for s in scenes:
            in_view = scene_items(s, clips, boards)
            item = QListWidgetItem(scene_icon(in_view, s.rows, s.cols), f"{s.name}\n{scene_summary(s)}")
            item.setData(ROLE_ID, s.id)
            names = ", ".join(c.name for c in in_view if c) or "no clips yet"
            item.setToolTip(f"<b>{s.name}</b><br>{names}<br>Double-click to open")
            self.addItem(item)
            if s.id in keep:
                item.setSelected(True)

    def scene_for(self, item: QListWidgetItem) -> Scene:
        return self._scenes[item.data(ROLE_ID)]

    def selected_scenes(self) -> list[Scene]:
        return [self.scene_for(self.item(i)) for i in range(self.count())
                if self.item(i).isSelected() and not self.item(i).isHidden()]

    def filter(self, text: str):
        text = text.casefold().strip()
        for i in range(self.count()):
            item = self.item(i)
            item.setHidden(bool(text) and text not in self.scene_for(item).name.casefold())


class LibraryScreen(QWidget):
    # What happens when a clip is opened is decided by the main window
    # (new project / new scene / quick view), so most actions are signals.
    openClip = Signal(object)                # ClipInfo double-clicked or Open
    quickView = Signal(object)               # ClipInfo
    newProjectFromClips = Signal(list)       # [ClipInfo]
    newSceneFromClips = Signal(str, list)    # project id, [ClipInfo]
    openScene = Signal(str, str)             # project id, scene id
    newSceneRequested = Signal(str)          # project id
    importRequested = Signal()
    importBoardsRequested = Signal()
    openBoard = Signal(object)               # BoardInfo double-clicked or Open
    clipsDeleted = Signal(list)              # clip ids about to be deleted
    boardsDeleted = Signal(list)             # board ids about to be deleted
    entryChanged = Signal()                  # a different project / All clips / Boards / tab

    def __init__(self, library: Library, projects: ProjectStore, boards: BoardLibrary,
                 parent=None):
        super().__init__(parent)
        self.library = library
        self.projects = projects
        self.boards = boards
        self._entry: str = str(settings.ui_value("library/entry", ALL_CLIPS) or ALL_CLIPS)
        self._all: list[ClipInfo] = []
        self._boards: list[BoardInfo] = []
        self._project_list: list[Project] = []

        # Left: All clips + projects
        self.sidebar = QListWidget()
        self.sidebar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sidebar.customContextMenuRequested.connect(self._sidebar_menu)
        self.sidebar.currentItemChanged.connect(self._sidebar_changed)
        new_btn = QPushButton("+ New project")
        new_btn.clicked.connect(lambda: self.new_project())

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 4, 8)
        left_layout.addWidget(self.sidebar, 1)
        left_layout.addWidget(new_btn)

        # Right: title, search, buttons, then Scenes | Clips tabs
        self.title = QLabel()
        f = self.title.font()
        f.setPointSize(f.pointSize() + 6)
        f.setBold(True)
        self.title.setFont(f)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(240)
        self.search.textChanged.connect(self._filter)

        self.new_scene_btn = QPushButton("New scene")
        self.new_scene_btn.setToolTip("Start a new scene in this project")
        self.new_scene_btn.clicked.connect(lambda: self._new_scene_clicked())
        self.import_btn = QPushButton("Import clips…")
        self.import_btn.setToolTip("Import video files (Ctrl+I). You can also drag them onto the window.")
        self.import_btn.clicked.connect(lambda: self.importRequested.emit())
        self.import_boards_btn = QPushButton("Import boards…")
        self.import_boards_btn.setToolTip("Import pictures or diagrams (PNG, JPEG, SVG…) "
                                          "to show in scenes and draw on (Ctrl+B)")
        self.import_boards_btn.clicked.connect(lambda: self.importBoardsRequested.emit())
        self.add_btn = QPushButton("Add from library…")
        self.add_btn.setToolTip("Add clips you've already imported to this project")
        self.add_btn.clicked.connect(lambda: self.add_from_library())
        self.open_btn = QPushButton("Open")
        self.open_btn.clicked.connect(lambda: self.open_selected())

        top = QHBoxLayout()
        top.addWidget(self.title, 1)
        top.addWidget(self.search)
        for b in (self.new_scene_btn, self.import_btn, self.import_boards_btn, self.add_btn,
                  self.open_btn):
            top.addWidget(b)

        # Scenes tab
        self.scene_grid = SceneGrid()
        self.scene_grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.scene_grid.customContextMenuRequested.connect(self._scene_menu)
        self.scene_grid.itemActivated.connect(
            lambda item: self.openScene.emit(self._entry, self.scene_grid.scene_for(item).id))
        self.scene_grid.itemSelectionChanged.connect(self._update_buttons)
        self.scenes_empty = _empty_label(
            "No scenes yet.\n\nA scene shows up to 4 clips side by side.\n"
            "Click New scene to start one.")
        self.scene_pages = QStackedWidget()
        self.scene_pages.addWidget(self.scene_grid)
        self.scene_pages.addWidget(self.scenes_empty)

        # Clips tab
        self.grid = ClipGrid()
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._grid_menu)
        self.grid.itemActivated.connect(lambda item: self.openClip.emit(self.grid.clip_for(item)))
        self.grid.itemSelectionChanged.connect(self._update_buttons)
        self.empty = _empty_label("")
        self.pages = QStackedWidget()
        self.pages.addWidget(self.grid)
        self.pages.addWidget(self.empty)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.scene_pages, "Scenes")
        self.tabs.addTab(self.pages, "Clips")
        self.tabs.currentChanged.connect(lambda _i: self._tab_changed())

        # Boards (shown instead of the tabs when "Boards" is chosen)
        self.board_grid = BoardGrid()
        self.board_grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.board_grid.customContextMenuRequested.connect(self._board_menu)
        self.board_grid.itemActivated.connect(
            lambda item: self.openBoard.emit(self.board_grid.board_for(item)))
        self.board_grid.itemSelectionChanged.connect(self._update_buttons)
        self.boards_empty = _empty_label(
            "No boards yet.\n\nBoards are pictures or diagrams — a course map, a start-line "
            "plan, a rules diagram — that you can put in a scene and draw on.\n\n"
            "Click Import boards…, or drag picture files onto the window.")
        self.board_pages = QStackedWidget()
        self.board_pages.addWidget(self.board_grid)
        self.board_pages.addWidget(self.boards_empty)

        self.body = QStackedWidget()
        self.body.addWidget(self.tabs)
        self.body.addWidget(self.board_pages)

        self.footer = QLabel()
        self.footer.setStyleSheet("color: gray;")

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 8, 8, 8)
        right_layout.addLayout(top)
        right_layout.addWidget(self.body, 1)
        right_layout.addWidget(self.footer)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([230, 900])
        split.setChildrenCollapsible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)

    # --- what's selected ----------------------------------------------------
    def current_project_id(self) -> Optional[str]:
        return None if self._entry in LIBRARY_ENTRIES else self._entry

    def on_boards(self) -> bool:
        return self._entry == BOARDS

    def current_project(self) -> Optional[Project]:
        pid = self.current_project_id()
        return next((p for p in self._project_list if p.id == pid), None)

    def entry_title(self) -> str:
        if self.on_boards():
            return "Boards"
        p = self.current_project()
        return p.name if p else "All clips"

    def on_scenes_tab(self) -> bool:
        return self.current_project() is not None and self.tabs.currentIndex() == SCENES_TAB

    def can_rename(self) -> bool:
        # Edit > Rename: a project, or (in Boards) the selected board.
        return self.current_project_id() is not None or (
            self.on_boards() and bool(self.board_grid.selected_boards()))

    def show_boards(self):
        self._set_entry(BOARDS)
        self.refresh()

    def select_project(self, pid: str, tab: int = SCENES_TAB):
        self._set_entry(pid)
        self.refresh()
        self.tabs.setCurrentIndex(tab)

    # --- refreshing ---------------------------------------------------------
    def refresh(self):
        # Re-read the library and projects from disk and redraw.
        self._all = self.library.clips()
        self._boards = self.boards.boards()
        self._project_list = self.projects.all()
        if self._entry not in LIBRARY_ENTRIES and not self.current_project():
            self._set_entry(ALL_CLIPS)  # the remembered project was deleted
        self._fill_sidebar()
        self._show_entry()

    def _fill_sidebar(self):
        existing = {c.id for c in self._all}
        sb = self.sidebar
        sb.blockSignals(True)
        sb.clear()

        all_item = QListWidgetItem(f"All clips  ·  {len(self._all)}")
        all_item.setData(ROLE_ID, ALL_CLIPS)
        all_item.setToolTip("Every clip you've imported")
        f = all_item.font()
        f.setBold(True)
        all_item.setFont(f)
        sb.addItem(all_item)

        boards_item = QListWidgetItem(f"Boards  ·  {len(self._boards)}")
        boards_item.setData(ROLE_ID, BOARDS)
        boards_item.setToolTip("Pictures and diagrams to show in scenes and draw on.\n"
                               "Import them here (Import boards…)")
        boards_item.setFont(f)
        sb.addItem(boards_item)

        header = QListWidgetItem("PROJECTS")
        header.setFlags(Qt.ItemFlag.NoItemFlags)
        hf = header.font()
        hf.setPointSize(max(7, hf.pointSize() - 2))
        hf.setBold(True)
        header.setFont(hf)
        header.setSizeHint(QSize(0, 34))
        header.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        sb.addItem(header)

        current = boards_item if self._entry == BOARDS else all_item
        for p in self._project_list:
            n_clips = sum(1 for cid in p.clip_ids if cid in existing)
            item = QListWidgetItem(f"{p.name}  ·  {len(p.scenes)}")
            item.setData(ROLE_ID, p.id)
            item.setToolTip(f"{p.name}\n{plural(len(p.scenes), 'scene')}, "
                            f"{plural(n_clips, 'clip')}\nRight-click to rename or delete")
            sb.addItem(item)
            if p.id == self._entry:
                current = item
        if not self._project_list:
            hint = QListWidgetItem("No projects yet")
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            hf = hint.font()
            hf.setItalic(True)
            hint.setFont(hf)
            sb.addItem(hint)

        sb.setCurrentItem(current)
        sb.blockSignals(False)

    def _sidebar_changed(self, item: Optional[QListWidgetItem], _previous=None):
        if item is None or item.data(ROLE_ID) is None:
            return
        self._set_entry(item.data(ROLE_ID))
        self.search.clear()
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(SCENES_TAB if self.current_project_id() else CLIPS_TAB)
        self.tabs.blockSignals(False)
        self._show_entry()

    def _set_entry(self, entry: str):
        # Which collection is shown; remembered for next time.
        self._entry = entry
        settings.set_ui_value("library/entry", entry)

    def _show_entry(self):
        project = self.current_project()
        by_id = {c.id: c for c in self._all}
        boards_by_id = {b.id: b for b in self._boards}
        boards = self.on_boards()
        self.body.setCurrentWidget(self.board_pages if boards else self.tabs)
        if boards:
            shown = list(reversed(self._boards))  # newest first
            self.board_grid.set_boards(shown)
            self.board_pages.setCurrentWidget(self.board_grid if shown else self.boards_empty)
            self.footer.setText(f"{plural(len(shown), 'board')} · "
                                f"{format_bytes(self.boards.total_size(shown))}")
        if project:
            clips = [by_id[cid] for cid in project.clip_ids if cid in by_id]
            self.scene_grid.set_scenes(project.scenes, by_id, boards_by_id)
            self.scene_pages.setCurrentWidget(self.scene_grid if project.scenes else self.scenes_empty)
            self.empty.setText(
                "This project has no clips yet.\n\n"
                "Drag videos onto the window, click Import clips…, "
                "or Add from library… to use clips you've already imported.")
            self.footer.setText(
                f"{plural(len(project.scenes), 'scene')} · {plural(len(clips), 'clip')} · "
                f"{format_bytes(self.library.total_size(clips))}")
        else:
            clips = list(reversed(self._all))  # newest first
            self.scene_grid.set_scenes([], by_id)
            self.empty.setText("No clips yet.\n\nDrag videos onto the window, or click Import clips…")
            if not boards:
                self.footer.setText(
                    f"{plural(len(clips), 'clip')} · {format_bytes(self.library.total_size(clips))}")
            if self.tabs.currentIndex() != CLIPS_TAB:
                self.tabs.blockSignals(True)
                self.tabs.setCurrentIndex(CLIPS_TAB)
                self.tabs.blockSignals(False)
        self.tabs.setTabVisible(SCENES_TAB, project is not None)
        self.tabs.tabBar().setVisible(project is not None)
        self.title.setText(self.entry_title())
        self.grid.set_clips(clips)
        self.pages.setCurrentWidget(self.grid if clips else self.empty)
        self._filter(self.search.text())
        self._update_buttons()
        self.entryChanged.emit()

    def _tab_changed(self):
        self._update_buttons()
        self.entryChanged.emit()

    def _filter(self, text: str):
        self.grid.filter(text)
        self.scene_grid.filter(text)
        self.board_grid.filter(text)

    def _update_buttons(self):
        project = self.current_project()
        scenes = self.on_scenes_tab()
        boards = self.on_boards()
        self.new_scene_btn.setVisible(scenes)
        self.import_btn.setVisible(not scenes and not boards)
        self.import_boards_btn.setVisible(boards)
        self.add_btn.setVisible(project is not None and not scenes)
        selected = (self.board_grid.selected_boards() if boards
                    else self.scene_grid.selected_scenes() if scenes
                    else self.grid.selected_clips())
        self.open_btn.setEnabled(bool(selected))
        self.open_btn.setToolTip("Look at the board and draw on it (not saved)" if boards else "")

    # --- opening ------------------------------------------------------------
    def open_selected(self):
        if self.on_boards():
            boards = self.board_grid.selected_boards()
            if boards:
                self.openBoard.emit(boards[0])
        elif self.on_scenes_tab():
            scenes = self.scene_grid.selected_scenes()
            if scenes:
                self.openScene.emit(self._entry, scenes[0].id)
        else:
            clips = self.grid.selected_clips()
            if clips:
                self.openClip.emit(clips[0])

    def _new_scene_clicked(self):
        pid = self.current_project_id()
        if pid:
            self.newSceneRequested.emit(pid)

    def select_all(self):
        grid = (self.board_grid if self.on_boards()
                else self.scene_grid if self.on_scenes_tab() else self.grid)
        grid.setFocus()
        grid.selectAll()

    # --- clip actions -------------------------------------------------------
    def add_to_project(self, clips: list[ClipInfo], pid: str):
        self.projects.add_clips(pid, [c.id for c in clips])
        self.refresh()

    def add_to_new_project(self, clips: list[ClipInfo]):
        p = self.new_project(select=False)
        if p:
            self.add_to_project(clips, p.id)

    def remove_from_project(self, clips: list[ClipInfo]):
        pid = self.current_project_id()
        if not (pid and clips):
            return
        ids = [c.id for c in clips]
        used = self.projects.scenes_using(pid, ids)
        if used:
            what = f"“{clips[0].name}”" if len(clips) == 1 else plural(len(clips), "clip")
            answer = QMessageBox.question(
                self, "Remove from project",
                f"Remove {what} from this project?\n\n"
                f"It's also taken out of: {', '.join(s.name for s in used)}.\n"
                "The clip stays in the library (All clips).",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.projects.remove_clips(pid, ids)
        self.refresh()

    def delete_from_library(self, clips: list[ClipInfo]):
        if not clips:
            return
        used_in = sorted({p.name for c in clips for p in self.projects.projects_using(c.id)})
        what = f"“{clips[0].name}”" if len(clips) == 1 else plural(len(clips), "clip")
        text = (f"Delete {what} from the library?\n\n"
                f"This frees {format_bytes(self.library.total_size(clips))}. "
                "The original video files are not touched, so you can import them again later.")
        if used_in:
            text += "\n\nAlso removes from: " + ", ".join(used_in)
        answer = QMessageBox.question(
            self, "Delete from library", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        ids = [c.id for c in clips]
        self.clipsDeleted.emit(ids)  # lets the player let go of them first
        for cid in ids:
            self.projects.forget_clip(cid)
            self.library.remove(cid)
        self.refresh()

    def add_from_library(self):
        project = self.current_project()
        if not project:
            return
        available = [c for c in reversed(self._all) if c.id not in project.clip_ids]
        if not available:
            QMessageBox.information(
                self, "Add from library",
                "Every imported clip is already in this project." if self._all
                else "The library is empty. Import some clips first.")
            return
        dialog = AddClipsDialog(project.name, available, self)
        if dialog.exec() and dialog.chosen:
            self.add_to_project(dialog.chosen, project.id)

    # --- Edit menu ----------------------------------------------------------
    def rename_selected(self):
        if self.on_boards():
            boards = self.board_grid.selected_boards()
            if boards:
                self.rename_board(boards[0].id)
            return
        if self.on_scenes_tab() and not self.sidebar.hasFocus():
            scenes = self.scene_grid.selected_scenes()
            if scenes:
                self.rename_scene(scenes[0].id)
                return
        self.rename_project()

    def delete_selected(self):
        # Edit > Delete: a project if the project list has focus; otherwise
        # the selected scenes, or the selected clips (removed from this
        # project, or deleted from the library when viewing All clips).
        if self.on_boards():
            self.delete_boards(self.board_grid.selected_boards())
        elif self.sidebar.hasFocus() and self.current_project_id():
            self.delete_project()
        elif self.on_scenes_tab():
            self.delete_scenes([s.id for s in self.scene_grid.selected_scenes()])
        elif self.current_project_id():
            self.remove_from_project(self.grid.selected_clips())
        else:
            self.delete_from_library(self.grid.selected_clips())

    # --- boards -------------------------------------------------------------
    def rename_board(self, bid: str):
        board = self.boards.get(bid)
        if not board:
            return
        name, ok = QInputDialog.getText(self, "Rename board", "Board name:",
                                        QLineEdit.EchoMode.Normal, board.name)
        if ok:
            try:
                self.boards.rename(bid, name)
            except ValueError as e:
                QMessageBox.warning(self, "Rename board", str(e))
            self.refresh()

    def delete_boards(self, boards: list[BoardInfo]):
        if not boards:
            return
        used = sorted({f"{p.name} › {sc.name}" for b in boards
                       for p, sc in self.projects.scenes_using_board(b.id)})
        what = f"the board “{boards[0].name}”" if len(boards) == 1 else plural(len(boards), "board")
        text = (f"Delete {what}?\n\nThe original picture files are not touched, "
                "so you can import them again later.")
        if used:
            text += ("\n\nIt's also taken out of these scenes, with its drawings:\n"
                     + "\n".join(used[:8]) + ("\n…" if len(used) > 8 else ""))
        answer = QMessageBox.question(
            self, "Delete board", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        ids = [b.id for b in boards]
        self.boardsDeleted.emit(ids)  # lets the player let go of them first
        for bid in ids:
            self.projects.forget_board(bid)
            self.boards.remove(bid)
        self.refresh()

    # --- scenes -------------------------------------------------------------
    def rename_scene(self, sid: str):
        pid = self.current_project_id()
        scene = self.projects.get_scene(pid, sid) if pid else None
        if not scene:
            return
        name, ok = QInputDialog.getText(self, "Rename scene", "Scene name:",
                                        QLineEdit.EchoMode.Normal, scene.name)
        if ok:
            try:
                self.projects.rename_scene(pid, sid, name)
            except ValueError as e:
                QMessageBox.warning(self, "Rename scene", str(e))
            self.refresh()

    def delete_scenes(self, sids: list[str]):
        pid = self.current_project_id()
        project = self.projects.get(pid) if pid else None
        scenes = [s for s in (project.scenes if project else []) if s.id in sids]
        if not scenes:
            return
        what = f"the scene “{scenes[0].name}”" if len(scenes) == 1 else plural(len(scenes), "scene")
        answer = QMessageBox.question(
            self, "Delete scene", f"Delete {what}?\n\nIts clips stay in the project.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            for s in scenes:
                self.projects.delete_scene(pid, s.id)
            self.refresh()

    # --- projects -----------------------------------------------------------
    def new_project(self, select: bool = True) -> Optional[Project]:
        name, ok = QInputDialog.getText(self, "New project", "Project name:",
                                        QLineEdit.EchoMode.Normal, self.projects.unique_name())
        if not ok:
            return None
        try:
            p = self.projects.create(name)
        except ValueError as e:
            QMessageBox.warning(self, "New project", str(e))
            return None
        if select:
            self.select_project(p.id)
        else:
            self.refresh()
        return p

    def rename_project(self, pid: Optional[str] = None):
        p = self.projects.get(pid or self.current_project_id() or "")
        if not p:
            return
        name, ok = QInputDialog.getText(self, "Rename project", "Project name:",
                                        QLineEdit.EchoMode.Normal, p.name)
        if ok:
            try:
                self.projects.rename(p.id, name)
            except ValueError as e:
                QMessageBox.warning(self, "Rename project", str(e))
            self.refresh()

    def delete_project(self, pid: Optional[str] = None):
        p = self.projects.get(pid or self.current_project_id() or "")
        if not p:
            return
        answer = QMessageBox.question(
            self, "Delete project",
            f"Delete the project “{p.name}” and its {plural(len(p.scenes), 'scene')}?\n\n"
            f"Its clips stay in the library, under All clips.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self.projects.delete(p.id)
            if self._entry == p.id:
                self._set_entry(ALL_CLIPS)
            self.refresh()

    # --- right-click menus --------------------------------------------------
    def _grid_menu(self, pos):
        item = self.grid.itemAt(pos)
        if item and not item.isSelected():
            self.grid.clearSelection()
            item.setSelected(True)
        clips = self.grid.selected_clips()
        here = self.current_project()
        menu = QMenu(self)

        if clips:
            these = "this clip" if len(clips) == 1 else "these clips"
            if here:
                _menu_action(menu, f"New scene with {these}",
                             lambda: self.newSceneFromClips.emit(here.id, clips),
                             enabled=len(clips) <= MAX_CLIPS_PER_SCENE)
            else:
                _menu_action(menu, f"Start a new project with {these}",
                             lambda: self.newProjectFromClips.emit(clips))
            _menu_action(menu, "Quick view", lambda: self.quickView.emit(clips[0]))
            menu.addSeparator()
            add_menu = menu.addMenu("Add to project")
            for p in self._project_list:
                if here is None or p.id != here.id:
                    _menu_action(add_menu, p.name, lambda pid=p.id: self.add_to_project(clips, pid),
                                 enabled=not all(c.id in p.clip_ids for c in clips))
            if add_menu.actions():
                add_menu.addSeparator()
            _menu_action(add_menu, "New project…", lambda: self.add_to_new_project(clips))
            if here:
                _menu_action(menu, f"Remove from “{here.name}”", lambda: self.remove_from_project(clips))
            menu.addSeparator()
            _menu_action(menu, "Delete from library…", lambda: self.delete_from_library(clips))
        else:
            _menu_action(menu, "Import clips…", lambda: self.importRequested.emit())
            if here:
                _menu_action(menu, "Add from library…", self.add_from_library)

        menu.exec(self.grid.viewport().mapToGlobal(pos))

    def _scene_menu(self, pos):
        item = self.scene_grid.itemAt(pos)
        if item and not item.isSelected():
            self.scene_grid.clearSelection()
            item.setSelected(True)
        scenes = self.scene_grid.selected_scenes()
        pid = self._entry
        menu = QMenu(self)
        if scenes:
            _menu_action(menu, "Open", lambda: self.openScene.emit(pid, scenes[0].id))
            _menu_action(menu, "Rename…", lambda: self.rename_scene(scenes[0].id))
            _menu_action(menu, "Delete scene…" if len(scenes) == 1 else "Delete scenes…",
                         lambda: self.delete_scenes([s.id for s in scenes]))
            menu.addSeparator()
        _menu_action(menu, "New scene", lambda: self.newSceneRequested.emit(pid))
        menu.exec(self.scene_grid.viewport().mapToGlobal(pos))

    def _board_menu(self, pos):
        item = self.board_grid.itemAt(pos)
        if item and not item.isSelected():
            self.board_grid.clearSelection()
            item.setSelected(True)
        boards = self.board_grid.selected_boards()
        menu = QMenu(self)
        if boards:
            _menu_action(menu, "Quick view", lambda: self.openBoard.emit(boards[0]))
            _menu_action(menu, "Rename…", lambda: self.rename_board(boards[0].id))
            menu.addSeparator()
            _menu_action(menu, "Delete board…" if len(boards) == 1 else "Delete boards…",
                         lambda: self.delete_boards(boards))
        else:
            _menu_action(menu, "Import boards…", lambda: self.importBoardsRequested.emit())
        menu.exec(self.board_grid.viewport().mapToGlobal(pos))

    def _sidebar_menu(self, pos):
        item = self.sidebar.itemAt(pos)
        pid = item.data(ROLE_ID) if item else None
        menu = QMenu(self)
        if pid == BOARDS:
            _menu_action(menu, "Import boards…", lambda: self.importBoardsRequested.emit())
            menu.addSeparator()
        elif pid and pid != ALL_CLIPS:
            _menu_action(menu, "Rename…", lambda: self.rename_project(pid))
            _menu_action(menu, "Delete project…", lambda: self.delete_project(pid))
            menu.addSeparator()
        _menu_action(menu, "New project…", lambda: self.new_project())
        menu.exec(self.sidebar.viewport().mapToGlobal(pos))


def _empty_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    label.setStyleSheet("color: gray; font-size: 13pt;")
    return label


class AddClipsDialog(QDialog):
    # Pick clips from the library to add to a project.

    def __init__(self, project_name: str, clips: list[ClipInfo], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Add clips to “{project_name}”")
        self.resize(820, 560)
        self.chosen: list[ClipInfo] = []

        hint = QLabel("Select one or more clips (Ctrl+click or Shift+click for several).")
        search = QLineEdit()
        search.setPlaceholderText("Search clips")
        search.setClearButtonEnabled(True)
        self.grid = ClipGrid()
        self.grid.set_clips(clips)
        search.textChanged.connect(self.grid.filter)
        self.grid.itemActivated.connect(lambda _item: self.accept())

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.add_btn = self.buttons.addButton("Add", QDialogButtonBox.ButtonRole.AcceptRole)
        self.add_btn.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.grid.itemSelectionChanged.connect(
            lambda: self.add_btn.setEnabled(bool(self.grid.selected_clips())))

        top = QHBoxLayout()
        top.addWidget(hint, 1)
        top.addWidget(search)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.grid, 1)
        layout.addWidget(self.buttons)

    def accept(self):
        self.chosen = self.grid.selected_clips()
        if self.chosen:
            super().accept()
