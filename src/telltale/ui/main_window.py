# main_window.py
# The main window: the start screen (library) and the player, the menus
# (File | Edit | View | Help), importing clips, keyboard shortcuts, which
# scene (or quick view) the player is showing, and unloading / loading
# projects (deleting and re-making their frames, core/storage.py).

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QStackedWidget,
)

from ..core import paths, storage, timebase
from ..core.boards import IMAGE_EXTENSIONS, BoardInfo, BoardLibrary, ImportFailed
from ..core.clip import ClipInfo
from ..core.library import Library, clip_id
from ..core.projects import MAX_CLIPS_PER_SCENE, ProjectStore
from . import help_dialogs
from .import_worker import ImportWorker, LoadWorker
from .dialogs import ClipPickerDialog, ask_choice, ask_name
from .library_screen import LibraryScreen, format_bytes, plural, scene_icon, scene_items
from .picture_reader import read_picture
from .player import PlayerScreen
from .settings_dialog import SettingsDialog

APP_TITLE = "Telltale Analysis"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".mts", ".m2ts", ".ts", ".webm", ".mxf", ".m4v", ".lrv", ".insv", ".wmv"}
VIDEO_FILTER = ("Video files (" + " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS)) + ");;All files (*)")
PICTURE_FILTER = ("Pictures and diagrams (" + " ".join(f"*{e}" for e in sorted(IMAGE_EXTENSIONS)) + ");;All files (*)")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        self.library = Library()
        self.projects = ProjectStore()
        self.boards = BoardLibrary()

        # What the player is showing: a saved scene, or an unsaved quick view.
        self.scene_pid: Optional[str] = None
        self.scene_id: Optional[str] = None
        self.quick = False

        h = self.home = LibraryScreen(self.library, self.projects, self.boards)
        h.openClip.connect(self._ask_open_clip)
        h.quickView.connect(self.quick_view)
        h.newProjectFromClips.connect(self.new_project_from_clips)
        h.newSceneFromClips.connect(self.new_scene)
        h.openScene.connect(self.open_scene)
        h.newSceneRequested.connect(lambda pid: self.new_scene(pid))
        h.importRequested.connect(self.import_dialog)
        h.clipsDeleted.connect(self._clips_deleted)
        h.importBoardsRequested.connect(self.import_boards_dialog)
        h.openBoard.connect(self.quick_view)
        h.boardsDeleted.connect(self._boards_deleted)
        h.entryChanged.connect(self._update_state)
        h.loadProjectRequested.connect(lambda pid: self.load_project(pid))
        h.unloadProjectRequested.connect(self.unload_project)

        self.player = PlayerScreen()
        self.player.activeClipChanged.connect(self._active_clip_changed)
        self.player.addClipRequested.connect(self._add_clip_to_view)
        self.player.saveRequested.connect(self._save_scene)
        self.player.drawingSelectionChanged.connect(self._update_state)
        panel = self.player.scenes_panel
        panel.sceneChosen.connect(self._scene_chosen)
        panel.newSceneRequested.connect(lambda: self.scene_pid and self.new_scene(self.scene_pid))
        panel.renameSceneRequested.connect(self._rename_scene)
        panel.deleteSceneRequested.connect(self._delete_scene)
        panel.saveQuickViewRequested.connect(self.save_quick_view)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.player)
        self.setCentralWidget(self.stack)

        # Import state
        self._worker: Optional[ImportWorker] = None
        self._progress: Optional[QProgressDialog] = None
        self._import_project: Optional[str] = None
        self._play_after = False
        self._imported: list[ClipInfo] = []
        self._import_errors: list[tuple[str, str]] = []
        # Loading state (re-making unloaded clips' frames)
        self._after_load: Optional[Callable[[], object]] = None
        self._load_errors: list[tuple[str, str]] = []
        self._load_cancelled = False

        self._build_menus()
        self._build_player_shortcuts()
        # Connected after the menus exist, as it updates them.
        self.stack.currentChanged.connect(lambda _i: self._update_state())
        self.show_library()

    # --- menus --------------------------------------------------------------
    def _action(self, menu: QMenu, text: str, slot: Callable[[], object],
                shortcut: Optional[str | QKeySequence] = None) -> QAction:
        a = QAction(text, self)
        if shortcut is not None:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(lambda _checked=False: slot())
        menu.addAction(a)
        return a

    def _build_menus(self):
        mb = self.menuBar()
        Std = QKeySequence.StandardKey

        file_menu = mb.addMenu("&File")
        self._action(file_menu, "&New project…", self.new_project, "Ctrl+N")
        self._action(file_menu, "New &scene", self._new_scene_here, "Ctrl+Shift+N")
        self._action(file_menu, "&Import clips…", self.import_dialog, "Ctrl+I")
        self._action(file_menu, "Import &boards…", self.import_boards_dialog, "Ctrl+B")
        self._action(file_menu, "&Open clip…", self.open_dialog, Std.Open)
        file_menu.addSeparator()
        self._action(file_menu, "&Settings…", self.open_settings, "Ctrl+,")
        file_menu.addSeparator()
        # Only shown while the player is showing.
        self.act_return = self._action(file_menu, "&Return to Projects", self.show_library)
        self.act_return.setToolTip("Leave this project and go back to the start screen")
        self.act_return_sep = file_menu.addSeparator()
        self._action(file_menu, "&Quit", self.close, Std.Quit)
        file_menu.setToolTipsVisible(True)

        edit_menu = mb.addMenu("&Edit")
        self.act_rename = self._action(edit_menu, "&Rename…", self.home.rename_selected, "F2")
        self.act_delete = self._action(edit_menu, "&Delete", self._delete, "Delete")
        self.act_delete.setToolTip("Player: delete the selected drawing. "
                                   "Scenes tab: delete the selected scenes. "
                                   "Clips tab: remove the selected clips from the project. "
                                   "All clips: delete them from the library.")
        edit_menu.addSeparator()
        self.act_select_all = self._action(edit_menu, "Select &all", self.home.select_all, "Ctrl+A")
        edit_menu.addSeparator()
        self.act_undo_drawing = self._action(edit_menu, "&Undo drawing", self._undo_drawing, "Ctrl+Z")
        self.act_clear_all = self._action(edit_menu, "&Clear All", self._clear_all_drawings)
        self.act_clear_all.setToolTip("Remove every drawing in this scene, on every frame")
        edit_menu.setToolTipsVisible(True)

        view_menu = mb.addMenu("&View")
        self.act_library = self._action(view_menu, "&Library", self.show_library, "Ctrl+1")
        self.act_player = self._action(view_menu, "&Player", self.show_player, "Ctrl+2")
        view_menu.addSeparator()
        self._action(view_menu, "&Full screen", self.toggle_fullscreen, "F11")

        help_menu = mb.addMenu("&Help")
        self._action(help_menu, "&Keyboard shortcuts", lambda: help_dialogs.show_shortcuts(self), "F1")
        self._action(help_menu, "Open &data folder", self.open_data_folder)
        help_menu.addSeparator()
        self._action(help_menu, f"&About {APP_TITLE}", lambda: help_dialogs.show_about(self, APP_TITLE))

        QShortcut(QKeySequence("Escape"), self, activated=self._escape)

    def _build_player_shortcuts(self):
        # Parented to the player screen, so they only work while it's showing
        # (arrow keys etc. stay free for the library's grids).
        p = self.player
        keys = {
            "Space": p.toggle_play,
            "Left": lambda: p.step(-1),
            "Right": lambda: p.step(1),
            ",": lambda: p.step(-1),
            ".": lambda: p.step(1),
            "Shift+Left": lambda: p.step(-10),
            "Shift+Right": lambda: p.step(10),
            # Selected view only (fine-tuning sync in split view)
            "Alt+Left": lambda: p.nudge_active(-1),
            "Alt+Right": lambda: p.nudge_active(1),
            "Alt+Shift+Left": lambda: p.nudge_active(-10),
            "Alt+Shift+Right": lambda: p.nudge_active(10),
            "Home": p.to_start,
            "End": p.to_end,
            "F": self.toggle_fullscreen,
            "Backspace": p.delete_selected_drawing,
            "T": p.set_timer_zero_here,
        }
        for n in range(1, 5):  # Ctrl+Shift+1..4: number of views
            keys[f"Ctrl+Shift+{n}"] = lambda n=n: p.set_view_count(n)
        for seq, slot in keys.items():
            QShortcut(QKeySequence(seq), self.player, activated=slot)

    def _update_state(self):
        on_library = self.stack.currentWidget() is self.home
        self.act_rename.setEnabled(on_library and (self.home.current_project_id() is not None
                                                   or self.home.on_boards()))
        self.act_delete.setEnabled(on_library or self.player.selected_drawing() is not None)
        self.act_select_all.setEnabled(on_library)
        self.act_library.setEnabled(not on_library)
        self.act_undo_drawing.setEnabled(not on_library)
        self.act_clear_all.setEnabled(not on_library)
        # Shown whenever the player is showing (a project scene or a quick view).
        self.act_return.setVisible(not on_library)
        self.act_return_sep.setVisible(not on_library)
        self.act_player.setEnabled(on_library and (self.quick or self.scene_id is not None))
        if on_library:
            title = self.home.entry_title()
        elif self.quick:
            item = self.player.active_item()
            title = f"Quick view — {item.name}" if item else "Quick view"
        else:
            project = self.projects.get(self.scene_pid) if self.scene_pid else None
            scene = project.scene(self.scene_id) if project and self.scene_id else None
            title = f"{scene.name} — {project.name}" if scene else ""
        self.setWindowTitle(f"{title} — {APP_TITLE}" if title else APP_TITLE)

    # --- switching screens --------------------------------------------------
    def show_library(self):
        self.player.pause()
        self.player.flush_save()
        # While you're in the library, scenes can change there; the player
        # reloads its scene when you come back, so it mustn't save meanwhile.
        self.player.saving = False
        self.stack.setCurrentWidget(self.home)
        if self.scene_pid and self.projects.get(self.scene_pid):
            self.home.select_project(self.scene_pid)  # back to this project's scenes
        else:
            self.home.refresh()
        self.home.grid.setFocus()

    def show_player(self):
        if self.quick:
            self._show_player_screen()
        elif self.scene_pid and self.scene_id:
            self.open_scene(self.scene_pid, self.scene_id)

    def _show_player_screen(self):
        self.stack.setCurrentWidget(self.player)
        self.player.setFocus()
        self._update_state()

    # --- scenes -------------------------------------------------------------
    def open_scene(self, pid: str, sid: str):
        self.player.flush_save()
        project = self.projects.get(pid)
        scene = project.scene(sid) if project else None
        if scene is None:
            self.statusBar().showMessage("That scene no longer exists.")
            if (pid, sid) == (self.scene_pid, self.scene_id):
                self._close_scene()
            return
        clips = {c.id: c for c in self.library.clips()}
        # Its clips' frames must be there first: load the project if it's
        # unloaded, or any clip that isn't loaded (opened again afterwards).
        if project.unloaded:
            self.load_project(pid, then=lambda: self.open_scene(pid, sid),
                              asking=f"open “{scene.name}”")
            return
        needed = [clips[cid] for cid in scene.clip_ids() if cid in clips and not clips[cid].has_frames]
        if needed:
            self.ensure_frames(needed, lambda: self.open_scene(pid, sid))
            return
        self.scene_pid, self.scene_id, self.quick = pid, sid, False
        boards = {b.id: b for b in self.boards.boards()}
        self.player.load_scene(scene, clips, boards)
        self._refresh_scenes_panel()
        self._show_player_screen()

    def new_scene(self, pid: str, clips: list[ClipInfo] = ()):
        # A new scene in project `pid`, opened straight away. With no clips
        # it shows one empty view with "+".
        self.player.flush_save()
        try:
            scene = self.projects.create_scene(pid, [c.id for c in clips])
        except KeyError:
            return
        self.open_scene(pid, scene.id)

    def _new_scene_here(self):
        pid = self.scene_pid if self.stack.currentWidget() is self.player else self.home.current_project_id()
        if pid:
            self.new_scene(pid)
        else:
            self.statusBar().showMessage("Open or create a project first, then add scenes to it.")

    def _close_scene(self):
        self.scene_pid = self.scene_id = None
        self.quick = False
        self.player.clear()
        self._update_state()

    def _scene_chosen(self, sid: str):
        if self.scene_pid and sid != self.scene_id:
            self.open_scene(self.scene_pid, sid)

    def _rename_scene(self, sid: str):
        self.player.flush_save()
        scene = self.projects.get_scene(self.scene_pid, sid) if self.scene_pid else None
        if not scene:
            return
        name = ask_name(self, "Rename scene", "Scene name:", scene.name)
        if name is None:
            return
        try:
            self.projects.rename_scene(self.scene_pid, sid, name)
        except ValueError as e:
            QMessageBox.warning(self, "Rename scene", str(e))
        self._refresh_scenes_panel()
        self._update_state()

    def _delete_scene(self, sid: str):
        self.player.flush_save()
        pid = self.scene_pid
        scene = self.projects.get_scene(pid, sid) if pid else None
        if not scene:
            return
        answer = QMessageBox.question(
            self, "Delete scene", f"Delete the scene “{scene.name}”?\n\nIts clips stay in the project.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.projects.delete_scene(pid, sid)
        if sid == self.scene_id:
            remaining = self.projects.get(pid).scenes
            if remaining:
                self.open_scene(pid, remaining[0].id)
            else:
                self._close_scene()
                self.show_library()
                return
        self._refresh_scenes_panel()

    def _save_scene(self):
        # Store what's on screen in the open scene (called shortly after changes).
        if not (self.scene_pid and self.scene_id):
            return
        scene = self.projects.get_scene(self.scene_pid, self.scene_id)
        if scene is None:
            return
        self.player.fill_scene(scene)
        try:
            self.projects.save_scene(self.scene_pid, scene)
        except KeyError:
            return
        self._refresh_scenes_panel()

    def _refresh_scenes_panel(self):
        panel = self.player.scenes_panel
        if self.quick or not self.scene_pid:
            panel.set_quick_view(True)
            return
        project = self.projects.get(self.scene_pid)
        if not project:
            return
        clips = {c.id: c for c in self.library.clips()}
        boards = {b.id: b for b in self.boards.boards()}
        icons = {s.id: scene_icon(scene_items(s, clips, boards), s.rows, s.cols)
                 for s in project.scenes}
        panel.set_scenes(project.name, project.scenes, self.scene_id, icons)

    # --- clips into scenes, projects, quick view ----------------------------
    def _ask_open_clip(self, info: ClipInfo):
        # A clip was opened (double-click / Open / Open clip…): ask what to do.
        on_library = self.stack.currentWidget() is self.home
        pid = self.home.current_project_id() if on_library else self.scene_pid
        if pid:
            choice = ask_choice(self, "Open clip", f"What would you like to do with “{info.name}”?",
                                ["New scene with this clip", "Quick view"])
            if choice == 0:
                self.new_scene(pid, [info])
        else:
            choice = ask_choice(self, "Open clip", f"What would you like to do with “{info.name}”?",
                                ["Start a new project", "Quick view"])
            if choice == 0:
                self.new_project_from_clips([info])
        if choice == 1:
            self.quick_view(info)

    def new_project_from_clips(self, clips: list[ClipInfo]):
        # New project containing `clips`, with a first scene showing up to 4 of them.
        name = ask_name(self, "New project", "Project name:", self.projects.unique_name())
        if name is None:
            return
        try:
            p = self.projects.create(name, [c.id for c in clips])
        except ValueError as e:
            QMessageBox.warning(self, "New project", str(e))
            return
        self.home.select_project(p.id)
        self.new_scene(p.id, clips[:MAX_CLIPS_PER_SCENE])

    def quick_view(self, info: ClipInfo | BoardInfo):
        # Look at a clip or board without a project. Nothing is saved.
        if isinstance(info, ClipInfo) and not info.has_frames:
            answer = QMessageBox.question(
                self, "Clip not loaded",
                f"“{info.name}” isn't loaded: its frames were deleted when its project was "
                "unloaded.\n\nRe-import it from the original video?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes)
            if answer == QMessageBox.StandardButton.Yes:
                self.ensure_frames([info], lambda: self.quick_view(self.library.get(info.id) or info),
                                   "Loading clip")
            return
        self.player.flush_save()
        self.scene_pid = self.scene_id = None
        self.quick = True
        self.player.clear()
        if isinstance(info, BoardInfo):
            self.player.load_board(info, 0)
        else:
            self.player.load_clip(info, 0)
        self._refresh_scenes_panel()
        self._show_player_screen()

    def save_quick_view(self):
        # Turn the quick view into a project with one scene (keeping sync,
        # zoom, boards and drawings).
        if not self.player.has_content():
            return
        clips = [p.clip for p in self.player.panes[:self.player.views_shown] if p.clip]
        name = ask_name(self, "Save as project", "Project name:", self.projects.unique_name())
        if name is None:
            return
        try:
            p = self.projects.create(name, [c.id for c in clips])
        except ValueError as e:
            QMessageBox.warning(self, "Save as project", str(e))
            return
        scene = self.projects.create_scene(p.id)
        self.player.fill_scene(scene)
        self.projects.save_scene(p.id, scene)
        self.home.select_project(p.id)
        self.open_scene(p.id, scene.id)

    def _add_clip_to_view(self, i: int):
        # A view's "+": pick a clip from this project or the full library, or a board.
        all_clips = list(reversed(self.library.clips()))
        boards = list(reversed(self.boards.boards()))  # newest first
        project = self.projects.get(self.scene_pid) if self.scene_pid else None
        if project:
            by_id = {c.id: c for c in all_clips}
            project_clips = [by_id[cid] for cid in project.clip_ids if cid in by_id]
            dialog = ClipPickerDialog(project.name, project_clips, all_clips, boards, self)
        else:
            dialog = ClipPickerDialog(None, None, all_clips, boards, self)
        if not (dialog.exec() and dialog.chosen):
            return
        chosen = dialog.chosen
        if isinstance(chosen, BoardInfo):
            self.player.load_board(chosen, i)  # boards aren't added to the project's clips
            return

        def place():
            info = self.library.get(chosen.id)
            if info is None:
                return
            if project:
                self.projects.add_clips(project.id, [info.id])
            self.player.load_clip(info, i)
        self.ensure_frames([chosen], place, "Loading clip")  # if it was unloaded

    def _active_clip_changed(self):
        self._update_state()
        item = self.player.active_item()
        info = self.player.active_clip()
        if isinstance(item, BoardInfo):
            self.statusBar().showMessage(f"{item.name}   {item.width}×{item.height}   board")
        elif info:
            sound = "" if info.has_audio else "   no audio"
            self.statusBar().showMessage(
                f"{info.name}   {info.width}×{info.height}   "
                f"{timebase.format_rate(info.rate)} fps   {info.frame_count} frames{sound}"
            )
        else:
            self.statusBar().clearMessage()

    def _clips_deleted(self, ids: list):
        self.player.unload_clips(ids)
        self.player.save_timer.stop()  # the library already removed them from scenes
        self._update_state()

    def _boards_deleted(self, ids: list):
        self.player.unload_boards(ids)
        self.player.save_timer.stop()  # already removed from the scenes on disk
        self._update_state()

    # --- unloading / loading projects --------------------------------------
    def unload_project(self, pid: str):
        # Delete the frames of the project's clips to free disk space, after
        # saying how much it frees. Everything else is kept.
        project = self.projects.get(pid)
        if project is None:
            return
        if self._worker is not None:
            self.statusBar().showMessage("Busy importing — try again when it has finished.")
            return
        self.player.flush_save()
        plan = storage.plan_unload(self.projects, self.library, pid)
        if plan.free:
            text = (f"Unload “{project.name}”?\n\n"
                    f"This deletes the imported frames of {plural(len(plan.free), 'clip')}, "
                    f"freeing {format_bytes(plan.bytes)}. The project, its scenes, sync, zoom, "
                    "drawings and thumbnails are all kept, and Load re-imports the frames from "
                    "the original videos.")
            if plan.kept:
                n = len(plan.kept)
                text += (f"\n\n{plural(n, 'clip')} {'is' if n == 1 else 'are'} also used by "
                         f"other loaded projects, so {'its' if n == 1 else 'their'} frames are kept.")
        else:
            text = (f"Unload “{project.name}”?\n\nNo space is freed yet: its clips are also "
                    "used by other loaded projects, so their frames are kept until those "
                    "projects are unloaded too.")
        if plan.no_original:
            names = ", ".join(c.name for c in plan.no_original[:5])
            more = "…" if len(plan.no_original) > 5 else ""
            text += (f"\n\nThe original video can't be found for: {names}{more}. "
                     "To load the project again you'll need to find "
                     f"{'it' if len(plan.no_original) == 1 else 'them'}.")
        answer = QMessageBox.question(
            self, "Unload project", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        # The player lets go of this project's scene, or any clip about to go.
        freeing = {c.id for c in plan.free}
        if self.scene_pid == pid or any(p.clip and p.clip.id in freeing for p in self.player.panes):
            self._close_scene()
        freed = storage.unload(self.projects, self.library, plan)
        self.home.refresh()
        self._update_state()
        self.statusBar().showMessage(f"Unloaded “{project.name}”: freed {format_bytes(freed)}.", 8000)

    def load_project(self, pid: str, then: Optional[Callable[[], object]] = None,
                     asking: Optional[str] = None):
        # Re-import an unloaded project's frames, then call `then`. With
        # `asking` (e.g. "open “Start”"), first asks whether to.
        project = self.projects.get(pid)
        if project is None:
            return
        todo = storage.clips_to_load(self.projects, self.library, pid)
        if asking and todo:
            answer = QMessageBox.question(
                self, "Load project",
                f"“{project.name}” is unloaded. Load it to {asking}?\n\n"
                f"This re-imports {plural(len(todo), 'clip')} from the original videos, "
                "which takes about as long as importing them did.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes)
            if answer != QMessageBox.StandardButton.Yes:
                return

        def loaded():
            self.projects.set_unloaded(pid, False)
            if self.stack.currentWidget() is self.home:
                self.home.refresh()
            self.statusBar().showMessage(f"Loaded “{project.name}”.", 5000)
            if then is not None:
                then()
        self.ensure_frames(todo, loaded, f"Loading “{project.name}”")

    def ensure_frames(self, clips: list[ClipInfo], then: Callable[[], object],
                      title: str = "Loading clips"):
        # Make sure these clips' frames exist, re-importing any that were
        # unloaded (in the background, with a progress dialog), then call
        # `then`. Nothing happens if it's cancelled or a clip can't be loaded.
        missing = [c for c in clips if c is not None and not c.has_frames]
        if not missing:
            then()
            return
        if self._worker is not None:
            self.statusBar().showMessage("Busy importing — try again when it has finished.")
            return
        jobs = []
        for c in missing:
            src = self._find_original(c)
            if src is None:
                self.statusBar().showMessage(
                    f"Not loaded: the original video for “{c.name}” is needed.", 8000)
                return
            jobs.append((c, src))

        self.player.pause()
        self._after_load = then
        self._load_errors = []
        self._load_cancelled = False
        self._progress = QProgressDialog("Preparing…", "Cancel", 0, 1000, self)
        self._progress.setWindowTitle(title)
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(400)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.setValue(0)

        worker = LoadWorker(self.library, jobs, self)
        worker.progress.connect(self._load_progress)
        worker.clipFailed.connect(lambda name, msg: self._load_errors.append((name, msg)))
        worker.cancelled.connect(lambda: setattr(self, "_load_cancelled", True))
        worker.finished.connect(self._load_finished)
        self._progress.canceled.connect(worker.cancel_event.set)
        self._worker = worker
        worker.start()

    def _find_original(self, clip: ClipInfo) -> Optional[Path]:
        # The clip's original video: where it was last seen, or (if it's gone)
        # wherever the user finds it. The file's contents must match the clip.
        def same(path: Path) -> bool:
            try:
                return path.is_file() and clip_id(path) == clip.id
            except OSError:
                return False

        path = Path(clip.source)
        if same(path):
            return path
        folder = path.parent if path.parent.is_dir() else Path.home()
        text = (f"The original video for “{clip.name}” isn't where it was imported from:\n"
                f"{clip.source}\n\nIt's needed to re-import the clip's frames. Find it?")
        while True:
            answer = QMessageBox.question(
                self, "Find the original video", text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes)
            if answer != QMessageBox.StandardButton.Yes:
                return None
            file, _ = QFileDialog.getOpenFileName(self, f"Find “{clip.name}”", str(folder),
                                                  VIDEO_FILTER)
            if not file:
                return None
            if same(Path(file)):
                return Path(file)
            folder = Path(file).parent
            text = (f"{Path(file).name} isn't the same video as “{clip.name}” (its contents "
                    "are different).\n\nFind the original?")

    def _load_progress(self, fraction: float, label: str):
        if self._progress:
            self._progress.setLabelText(f"Re-importing {label}…")
            self._progress.setValue(int(fraction * 1000))

    def _load_finished(self):
        if self._progress:
            self._progress.reset()
            self._progress.deleteLater()
            self._progress = None
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        then, self._after_load = self._after_load, None
        if self.stack.currentWidget() is self.home:
            self.home.refresh()
        if self._load_errors:
            shown = self._load_errors[:5]
            text = "\n\n".join(f"{name}:\n{msg}" for name, msg in shown)
            if len(self._load_errors) > len(shown):
                text += f"\n\n…and {len(self._load_errors) - len(shown)} more."
            QMessageBox.warning(self, "Could not load", text)
            return
        if self._load_cancelled:
            self.statusBar().showMessage("Loading cancelled.", 5000)
            return
        if then is not None:
            then()

    # --- importing ----------------------------------------------------------
    def new_project(self):
        self.show_library()
        self.home.new_project()

    def import_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Import clips", str(Path.home()), VIDEO_FILTER)
        if files:
            self.import_paths([Path(f) for f in files])

    def open_dialog(self):
        file, _ = QFileDialog.getOpenFileName(self, "Open clip", str(Path.home()), VIDEO_FILTER)
        if file:
            self.import_paths([Path(file)], play_after=True)

    def import_paths(self, paths_in: list[Path], play_after: bool = False):
        # Import videos into the library (and into the project being viewed, if
        # any), and pictures as boards. Folders are expanded to the videos and
        # pictures directly inside them.
        found: list[Path] = []
        for p in paths_in:
            if p.is_dir():
                found += sorted(f for f in p.iterdir() if f.is_file()
                                and f.suffix.lower() in VIDEO_EXTENSIONS | IMAGE_EXTENSIONS)
            else:
                found.append(p)
        pictures = [f for f in found if f.suffix.lower() in IMAGE_EXTENSIONS]
        files = [f for f in found if f.suffix.lower() not in IMAGE_EXTENSIONS]
        if pictures:
            self.import_boards(pictures, place=play_after)
        if not files:
            if not pictures:
                self.statusBar().showMessage("No video or picture files found to import.")
            return
        if self._worker is not None:
            self.statusBar().showMessage("Already importing — please wait for it to finish.")
            return

        self.player.pause()
        # New clips also go into the project you're working in, if any.
        on_player = self.stack.currentWidget() is self.player
        self._import_project = self.scene_pid if on_player else self.home.current_project_id()
        self._play_after = play_after
        self._imported = []
        self._import_errors = []

        self._progress = QProgressDialog("Preparing…", "Cancel", 0, 1000, self)
        self._progress.setWindowTitle("Importing clips")
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(400)  # already-imported clips finish instantly
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.setValue(0)

        worker = ImportWorker(self.library, files, self)
        worker.progress.connect(self._import_progress)
        worker.clipReady.connect(self._import_clip_ready)
        worker.clipFailed.connect(lambda name, msg: self._import_errors.append((name, msg)))
        worker.cancelled.connect(lambda: self.statusBar().showMessage("Import cancelled."))
        worker.finished.connect(self._import_finished)
        self._progress.canceled.connect(worker.cancel_event.set)
        self._worker = worker
        worker.start()

    # --- boards ---------------------------------------------------------------
    def import_boards_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Import boards", str(Path.home()),
                                                PICTURE_FILTER)
        if not files:
            return
        imported = self.import_boards([Path(f) for f in files])
        if imported and self.stack.currentWidget() is self.home:
            self.home.show_boards()  # show what was just imported

    def import_boards(self, files: list[Path], place: bool = False) -> list[BoardInfo]:
        # Import pictures as boards. `place`: also put them in the player's
        # empty views (e.g. pictures dropped on the player).
        imported: list[BoardInfo] = []
        errors: list[tuple[str, str]] = []
        progress = None
        if len(files) > 1:
            progress = QProgressDialog("Importing boards…", "Cancel", 0, len(files), self)
            progress.setWindowTitle("Importing boards")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(300)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for k, path in enumerate(files):
                if progress is not None:
                    if progress.wasCanceled():
                        break
                    progress.setLabelText(f"Importing {path.name}…")
                    progress.setValue(k)
                try:
                    imported.append(self.boards.import_board(path, fallback=read_picture))
                except (ImportFailed, OSError) as e:
                    errors.append((path.name, str(e)))
        finally:
            QApplication.restoreOverrideCursor()
            if progress is not None:
                progress.reset()
                progress.deleteLater()

        if self.stack.currentWidget() is self.home:
            self.home.refresh()
        if errors:
            shown = errors[:5]
            text = "\n\n".join(f"{name}:\n{msg}" for name, msg in shown)
            if len(errors) > len(shown):
                text += f"\n\n…and {len(errors) - len(shown)} more."
            QMessageBox.warning(self, "Could not import", text)
        if not imported:
            return imported

        placed = 0
        on_player = self.stack.currentWidget() is self.player
        if place and on_player and (self.scene_id or self.quick):
            for board in imported:
                slots = self.player.open_slots()
                if not slots:
                    break
                self.player.load_board(board, self.player.active
                                       if self.player.active in slots else slots[0])
                placed += 1
        if placed < len(imported):
            self.statusBar().showMessage(
                f"Imported {plural(len(imported), 'board')}. Add one to a scene with a view's +"
                " (Boards tab).", 8000)
        return imported

    def _import_progress(self, fraction: float, label: str):
        if self._progress:
            self._progress.setLabelText(f"Preparing {label} for frame stepping…")
            self._progress.setValue(int(fraction * 1000))

    def _import_clip_ready(self, info: ClipInfo):
        self._imported.append(info)
        if self._import_project:
            try:
                self.projects.add_clips(self._import_project, [info.id])
            except KeyError:
                pass  # project deleted meanwhile

    def _import_finished(self):
        if self._progress:
            self._progress.reset()
            self._progress.deleteLater()
            self._progress = None
        if self._worker:
            self._worker.deleteLater()
            self._worker = None

        if self.stack.currentWidget() is self.home:
            self.home.refresh()

        if self._import_errors:
            shown = self._import_errors[:5]
            text = "\n\n".join(f"{name}:\n{msg}" for name, msg in shown)
            if len(self._import_errors) > len(shown):
                text += f"\n\n…and {len(self._import_errors) - len(shown)} more."
            QMessageBox.warning(self, "Could not import", text)

        if not self._imported:
            return
        if self._play_after:
            self._show_opened(self._imported)
        else:
            project = self.projects.get(self._import_project) if self._import_project else None
            where = f" into “{project.name}”" if project else ""
            self.statusBar().showMessage(f"Imported {plural(len(self._imported), 'clip')}{where}.")

    def _show_opened(self, clips: list[ClipInfo]):
        # After Open clip… or a drop on the player: fill the scene's empty
        # views if there are any, otherwise ask what to do with the clip.
        on_player = self.stack.currentWidget() is self.player
        if on_player and (self.scene_id or self.quick) and self.player.open_slots():
            placed = 0
            for info in clips:
                slots = self.player.open_slots()
                if not slots:
                    break
                self.player.load_clip(info, self.player.active if self.player.active in slots else slots[0])
                placed += 1
            if placed < len(clips) and self.scene_pid:
                self.statusBar().showMessage(
                    f"{plural(len(clips) - placed, 'clip')} added to the project's clips "
                    "(no empty views left in this scene).")
        else:
            self._ask_open_clip(clips[0])

    # --- drag and drop ------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        dropped = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if dropped:
            # Dropped on the player: show it. Dropped on the library: just import.
            self.import_paths(dropped, play_after=self.stack.currentWidget() is self.player)

    # --- drawings -----------------------------------------------------------
    def _undo_drawing(self):
        if not self.player.undo_drawing():
            self.statusBar().showMessage("Nothing to undo.", 3000)

    def _clear_all_drawings(self):
        saved = self.player.saved_drawing_count()
        if saved:
            answer = QMessageBox.question(
                self, "Clear All",
                f"Remove all {plural(saved, 'drawing')} in this scene, on every frame?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.player.clear_all_drawings()

    def _escape(self):
        # Esc: leave full screen; otherwise deselect the drawing, or put down the tool.
        if self.isFullScreen():
            self.leave_fullscreen()
        elif not self.player.deselect_drawing():
            self.player.put_down_tool()

    def _delete(self):
        # Edit > Delete (Delete key): the selected drawing in the player,
        # or the selection on the start screen.
        if self.stack.currentWidget() is self.player:
            self.player.delete_selected_drawing()
        else:
            self.home.delete_selected()

    # --- settings, help, window ---------------------------------------------
    def open_settings(self):
        self.player.pause()
        SettingsDialog(self).exec()

    def open_data_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.data_dir())))

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.leave_fullscreen()
        else:
            for w in (self.menuBar(), self.statusBar()):
                w.hide()
            self.showFullScreen()

    def leave_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            for w in (self.menuBar(), self.statusBar()):
                w.show()

    def closeEvent(self, event):
        self.player.flush_save()
        if self._worker is not None:
            self._worker.cancel_event.set()
            self._worker.wait(5000)
        super().closeEvent(event)
