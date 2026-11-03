# projects.py
# Projects, scenes and clips:
#
#   Project  a piece of work, e.g. "Race day 3"
#     clips    the project's clips (ids of clips in the shared library)
#     scenes   saved views of 1-4 of those clips, e.g. "Start" with the bow
#              and drone cameras side by side, synced on the gun
#
#   <data>/projects/<project id>/project.json
#
# A project only stores clip ids, so the same clip can be in many projects
# without copying any footage, and deleting a project never deletes clips.
# Each project has its own folder so later per-project data (drawings,
# markers, timers) can sit beside project.json.

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from . import paths
from . import timer as timer_mod
from .drawings import Drawing

# 1: clips only.  2: + scenes (version-1 files load fine, with no scenes).
FORMAT_VERSION = 2
META_FILE = "project.json"
MAX_CLIPS_PER_SCENE = 4
# Default (rows, columns) for each number of views
DEFAULT_LAYOUTS = {1: (1, 1), 2: (1, 2), 3: (1, 3), 4: (2, 2)}


def valid_layout(rows: int, cols: int) -> bool:
    return rows >= 1 and cols >= 1 and rows * cols <= MAX_CLIPS_PER_SCENE


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class SceneSlot:
    # One view in a scene.
    clip_id: str
    offset: str = "0"                    # sync: seconds added to the scene clock (exact fraction)
    crop: Optional[list[float]] = None   # zoomed area [x, y, width, height] in video pixels
    drawings: list[Drawing] = field(default_factory=list)  # "Hold" drawings on this view

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SceneSlot":
        known = {f.name for f in fields(cls)}
        slot = cls(**{k: v for k, v in d.items() if k in known})
        loaded = (Drawing.from_dict(x) for x in slot.drawings if isinstance(x, dict))
        slot.drawings = [x for x in loaded if x is not None]
        return slot


@dataclass
class Scene:
    id: str
    name: str
    views: int = 1                                           # 1-4 views on screen (= rows × cols)
    rows: int = 0                                            # layout: 0 = default for `views`
    cols: int = 0
    slots: list[Optional[SceneSlot]] = field(default_factory=list)  # one per view; None = empty (+)
    time: str = "0"                                          # where the scene clock was left
    active: int = 0                                          # selected view
    timer: Optional[dict] = None                             # {"mode": "dn"|"up"|"du", "zero": scene time}
    created_at: str = ""
    modified_at: str = ""

    def clip_ids(self) -> list[str]:
        return [s.clip_id for s in self.slots if s is not None]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Scene":
        known = {f.name for f in fields(cls)}
        scene = cls(**{k: v for k, v in d.items() if k in known})
        scene.slots = [SceneSlot.from_dict(s) if isinstance(s, dict) else None for s in scene.slots]
        rows, cols = int(scene.rows or 0), int(scene.cols or 0)
        views = max(1, min(MAX_CLIPS_PER_SCENE, int(scene.views)))
        if not valid_layout(rows, cols) or rows * cols != views:
            rows, cols = DEFAULT_LAYOUTS[views]  # older file, or the two disagree
        scene.rows, scene.cols, scene.views = rows, cols, rows * cols
        scene.slots = (scene.slots + [None] * scene.views)[:scene.views]
        scene.active = max(0, min(int(scene.active), scene.views - 1))
        parsed = timer_mod.parse(scene.timer)
        scene.timer = {"mode": parsed[0], "zero": str(parsed[1])} if parsed else None
        return scene


@dataclass
class Project:
    id: str
    name: str
    clip_ids: list[str] = field(default_factory=list)   # in the order added
    scenes: list[Scene] = field(default_factory=list)   # in the order created
    created_at: str = ""
    modified_at: str = ""
    version: int = FORMAT_VERSION
    # Not saved: where this project's folder is right now.
    folder: str = field(default="", compare=False)

    @property
    def path(self) -> Path:
        return Path(self.folder)

    def scene(self, sid: str) -> Optional[Scene]:
        return next((s for s in self.scenes if s.id == sid), None)

    def save(self):
        self.path.mkdir(parents=True, exist_ok=True)
        self.version = FORMAT_VERSION
        data = {k: v for k, v in asdict(self).items() if k != "folder"}
        tmp = self.path / (META_FILE + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.path / META_FILE)  # never leaves a half-written file

    @classmethod
    def load(cls, folder: Path) -> Optional["Project"]:
        try:
            data = json.loads((Path(folder) / META_FILE).read_text())
        except (OSError, ValueError):
            return None
        known = {f.name for f in fields(cls)} - {"folder"}
        try:
            project = cls(**{k: v for k, v in data.items() if k in known})
            project.scenes = [Scene.from_dict(s) for s in project.scenes]
        except (TypeError, ValueError, AttributeError):
            return None
        if project.version > FORMAT_VERSION:
            return None  # made by a newer version of the app: leave it alone
        project.folder = str(Path(folder))
        return project


class ProjectStore:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else paths.projects_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    # --- reading ------------------------------------------------------------
    def all(self) -> list[Project]:
        # Every project, sorted by name.
        found = []
        for folder in self.root.iterdir():
            if folder.is_dir():
                p = Project.load(folder)
                if p:
                    found.append(p)
        return sorted(found, key=lambda p: (p.name.casefold(), p.created_at))

    def get(self, pid: str) -> Optional[Project]:
        return Project.load(self.root / pid)

    def get_scene(self, pid: str, sid: str) -> Optional[Scene]:
        p = self.get(pid)
        return p.scene(sid) if p else None

    def projects_using(self, clip_id: str) -> list[Project]:
        return [p for p in self.all() if clip_id in p.clip_ids]

    def scenes_using(self, pid: str, clip_ids: Iterable[str]) -> list[Scene]:
        ids = set(clip_ids)
        p = self.get(pid)
        return [s for s in p.scenes if ids & set(s.clip_ids())] if p else []

    def unique_name(self, base: str = "New project") -> str:
        taken = {p.name.casefold() for p in self.all()}
        return _unique(base, taken)

    # --- projects -----------------------------------------------------------
    def create(self, name: str, clip_ids: Iterable[str] = ()) -> Project:
        name = _clean_name(name)
        pid = uuid.uuid4().hex[:12]
        now = _now()
        p = Project(id=pid, name=name, clip_ids=list(dict.fromkeys(clip_ids)),
                    created_at=now, modified_at=now, folder=str(self.root / pid))
        p.save()
        return p

    def rename(self, pid: str, name: str) -> Project:
        return self._change(pid, lambda p: setattr(p, "name", _clean_name(name)))

    def delete(self, pid: str):
        # Removes the project only; its clips stay in the library.
        shutil.rmtree(self.root / pid, ignore_errors=True)

    # --- the project's clips ------------------------------------------------
    def add_clips(self, pid: str, clip_ids: Iterable[str]) -> Project:
        def add(p: Project):
            for cid in clip_ids:
                if cid not in p.clip_ids:
                    p.clip_ids.append(cid)
        return self._change(pid, add)

    def remove_clips(self, pid: str, clip_ids: Iterable[str]) -> Project:
        # Also takes them out of the project's scenes (their views become empty).
        drop = set(clip_ids)

        def remove(p: Project):
            p.clip_ids = [c for c in p.clip_ids if c not in drop]
            for scene in p.scenes:
                scene.slots = [None if (s and s.clip_id in drop) else s for s in scene.slots]
        return self._change(pid, remove)

    def forget_clip(self, clip_id: str):
        # Call when a clip is deleted from the library.
        for p in self.projects_using(clip_id):
            self.remove_clips(p.id, [clip_id])

    # --- scenes -------------------------------------------------------------
    def create_scene(self, pid: str, clip_ids: Iterable[str] = (),
                     name: Optional[str] = None) -> Scene:
        # New scene, named "Scene N" unless a name is given. Its clips are
        # added to the project too.
        ids = list(dict.fromkeys(clip_ids))[:MAX_CLIPS_PER_SCENE]
        made: list[Scene] = []

        def add(p: Project):
            for cid in ids:
                if cid not in p.clip_ids:
                    p.clip_ids.append(cid)
            now = _now()
            rows, cols = DEFAULT_LAYOUTS[max(1, len(ids))]
            scene = Scene(
                id=uuid.uuid4().hex[:12],
                name=_clean_name(name) if name else _unique(
                    "Scene", {s.name.casefold() for s in p.scenes}, start_with_number=True),
                views=rows * cols,
                rows=rows,
                cols=cols,
                slots=[SceneSlot(cid) for cid in ids] or [None],
                created_at=now,
                modified_at=now,
            )
            p.scenes.append(scene)
            made.append(scene)
        self._change(pid, add)
        return made[0]

    def save_scene(self, pid: str, scene: Scene) -> Project:
        # Store the scene's current state (clips, sync, zoom, position).
        def put(p: Project):
            for i, s in enumerate(p.scenes):
                if s.id == scene.id:
                    scene.modified_at = _now()
                    p.scenes[i] = scene
                    for cid in scene.clip_ids():
                        if cid not in p.clip_ids:
                            p.clip_ids.append(cid)
                    return
            raise KeyError(f"No scene with id {scene.id}")
        return self._change(pid, put)

    def rename_scene(self, pid: str, sid: str, name: str) -> Project:
        def rename(p: Project):
            s = p.scene(sid)
            if s is None:
                raise KeyError(f"No scene with id {sid}")
            s.name = _clean_name(name)
        return self._change(pid, rename)

    def delete_scene(self, pid: str, sid: str) -> Project:
        # The scene's clips stay in the project.
        return self._change(pid, lambda p: setattr(
            p, "scenes", [s for s in p.scenes if s.id != sid]))

    def _change(self, pid: str, edit) -> Project:
        p = self.get(pid)
        if p is None:
            raise KeyError(f"No project with id {pid}")
        edit(p)
        p.modified_at = _now()
        p.save()
        return p


def _unique(base: str, taken: set[str], start_with_number: bool = False) -> str:
    # "New project", "New project 2"...  or "Scene 1", "Scene 2"...
    if not start_with_number and base.casefold() not in taken:
        return base
    n = 1 if start_with_number else 2
    while f"{base} {n}".casefold() in taken:
        n += 1
    return f"{base} {n}"


def _clean_name(name: str) -> str:
    name = " ".join(name.split())  # trim, and no line breaks or double spaces
    if not name:
        raise ValueError("A name can't be empty.")
    return name[:120]
