# storage.py
# Unloading and loading projects, to save disk space.
#
# Unloading a project deletes the frames of its clips (by far the biggest
# part of a clip, see clip.py) but keeps everything else: the project, its
# scenes, sync, zoom, drawings and thumbnails. Loading makes the frames again
# from the original videos, so it needs them to still exist (they can be
# found again if they were moved).
#
# Clips can be shared between projects, so a clip's frames are only deleted
# when no *loaded* project uses it. Clips that aren't in any project are
# never touched by unloading.

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .clip import ClipInfo
from .library import Library
from .projects import ProjectStore


@dataclass
class UnloadPlan:
    pid: str
    free: list[ClipInfo] = field(default_factory=list)          # frames to delete
    kept: list[ClipInfo] = field(default_factory=list)          # used by other loaded projects
    no_original: list[ClipInfo] = field(default_factory=list)   # in `free`, original not found
    bytes: int = 0                                               # space it frees


def plan_unload(projects: ProjectStore, library: Library, pid: str) -> UnloadPlan:
    # What unloading project `pid` would do (nothing is changed).
    project = projects.get(pid)
    if project is None:
        raise KeyError(f"No project with id {pid}")
    plan = UnloadPlan(pid)
    keep = projects.loaded_clip_ids(except_pid=pid)
    for cid in project.all_clip_ids():
        info = library.get(cid)
        if info is None or not info.has_frames:
            continue
        if cid in keep:
            plan.kept.append(info)
        else:
            plan.free.append(info)
            plan.bytes += library.frames_bytes(info)
            if not Path(info.source).is_file():
                plan.no_original.append(info)
    return plan


def unload(projects: ProjectStore, library: Library, plan: UnloadPlan) -> int:
    # Carry out a plan from plan_unload. Returns the bytes freed.
    freed = 0
    keep = projects.loaded_clip_ids(except_pid=plan.pid)  # re-checked, in case things changed
    for info in plan.free:
        if info.id not in keep:
            freed += library.unload_clip(info.id)
    projects.set_unloaded(plan.pid, True)
    return freed


def clips_to_load(projects: ProjectStore, library: Library, pid: str) -> list[ClipInfo]:
    # The project's clips whose frames need making again before it's used.
    project = projects.get(pid)
    if project is None:
        return []
    found = (library.get(cid) for cid in project.all_clip_ids())
    return [c for c in found if c is not None and not c.has_frames]
