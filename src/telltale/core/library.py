# library.py
# The clip library: every imported clip lives in its own folder under paths.library_dir(), named by its clip id (see clip.py for the layout).
#
# A clip's frames can be deleted to save space (unload_clip) and made again
# from the original video later (reload_clip); see core/storage.py for when.


# A clip's id comes from the contents of the original file, not its name or location, so a renamed or moved file is recognised instead of being imported a second time.

from __future__ import annotations

import hashlib
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import ffmpeg, ingest, paths, timebase
from .clip import AUDIO_FILE, FRAMES_DIR, THUMB_FILE, ClipInfo
from .ingest import ImportCancelled, ImportFailed, ProgressCallback

__all__ = ["Library", "clip_id", "ImportCancelled", "ImportFailed", "WrongFile"]

_SAMPLE = 1024 * 1024  # bytes read from each end of the file for the id


class WrongFile(ImportFailed):
    # The file given to reload a clip isn't the video it was imported from.
    pass


def clip_id(src: Path) -> str:
    # Hash of the file size plus its first and last 1 MB. Video files carry
    # timestamps and an index at the start or end, so two different
    # recordings never match, and reading 2 MB is instant even for huge files.
    size = src.stat().st_size
    h = hashlib.sha1(str(size).encode())
    with open(src, "rb") as f:
        h.update(f.read(_SAMPLE))
        if size > _SAMPLE:
            f.seek(max(_SAMPLE, size - _SAMPLE))
            h.update(f.read(_SAMPLE))
    return h.hexdigest()[:16]


class Library:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else paths.library_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    # --- looking clips up ---------------------------------------------------
    def get(self, cid: str) -> Optional[ClipInfo]:
        return ClipInfo.load(self.root / cid)

    def find(self, src: Path | str) -> Optional[ClipInfo]:
        # The imported copy of `src`, if there is one.
        src = Path(src).resolve()
        info = self.get(clip_id(src))
        if info and info.source != str(src):
            info.source = str(src)  # the original was moved or renamed
            info.save()
        return info

    def clips(self) -> list[ClipInfo]:
        # Every imported clip, oldest first.
        found = []
        for folder in self.root.iterdir():
            if folder.is_dir() and not folder.name.endswith(".part"):
                info = ClipInfo.load(folder)
                if info:
                    found.append(info)
        return sorted(found, key=lambda c: c.imported_at)

    def size_on_disk(self, cid: str) -> int:
        # Bytes used by a clip's folder. Measured once, then kept in clip.json.
        info = self.get(cid)
        if info and info.disk_bytes:
            return info.disk_bytes
        total = _folder_bytes(self.root / cid)
        if info:
            info.disk_bytes = total
            info.save()
        return total

    def total_size(self, clips: Optional[list[ClipInfo]] = None) -> int:
        return sum(self.size_on_disk(c.id) for c in (clips if clips is not None else self.clips()))

    def remove(self, cid: str):
        shutil.rmtree(self.root / cid, ignore_errors=True)

    # --- unloading / loading frames -------------------------------------------
    def frames_bytes(self, info: ClipInfo) -> int:
        # Space the clip's frames take up (what unloading it would free).
        if not info.has_frames:
            return 0
        others = sum(f.stat().st_size for f in info.path.iterdir() if f.is_file())
        return max(0, self.size_on_disk(info.id) - others)

    def unload_clip(self, cid: str) -> int:
        # Delete a clip's frames, keeping its record, thumbnail and sound.
        # Returns the bytes freed.
        info = self.get(cid)
        if info is None:
            return 0
        before = self.size_on_disk(cid)
        trash = info.path / (FRAMES_DIR + ".trash")
        shutil.rmtree(trash, ignore_errors=True)
        if info.frames_dir.exists():
            info.frames_dir.rename(trash)  # all at once, so frames/ is never half there
        shutil.rmtree(trash, ignore_errors=True)
        info.disk_bytes = _folder_bytes(info.path)
        info.save()
        return max(0, before - info.disk_bytes)

    def reload_clip(
        self,
        cid: str,
        src: Optional[Path | str] = None,
        progress: Optional[ProgressCallback] = None,
        cancel: Optional[threading.Event] = None,
    ) -> ClipInfo:
        # Make an unloaded clip's frames again from its original video
        # (`src`, or where it was last seen). Frame numbers stay the same, so
        # sync, zoom and drawings in scenes still line up.
        info = self.get(cid)
        if info is None:
            raise ImportFailed("That clip is no longer in the library.")
        src = Path(src or info.source).resolve()
        if not src.is_file():
            raise ImportFailed(f"The original video for {info.name} can't be found:\n{src}")
        if clip_id(src) != cid:
            raise WrongFile(f"{src.name} isn't the video {info.name} was imported from.")
        if info.has_frames:
            if progress:
                progress(1.0)
            return info

        work = self.root / f"{cid}.reload.part"
        shutil.rmtree(work, ignore_errors=True)
        audio = info.has_audio and not (info.path / AUDIO_FILE).is_file()
        try:
            work.mkdir(parents=True)
            count, w, h = ingest.extract(src, work, info.rate, audio, info.duration,
                                         progress, cancel)
            if (w, h) != (info.width, info.height):
                raise ImportFailed(
                    f"{src.name} now gives {w}×{h} pictures instead of "
                    f"{info.width}×{info.height}, so drawings wouldn't line up.")
            shutil.rmtree(info.frames_dir, ignore_errors=True)  # any partial leftovers
            (work / FRAMES_DIR).rename(info.frames_dir)
            for name in ([AUDIO_FILE] if audio else []) + [THUMB_FILE]:
                if (work / name).is_file() and not (info.path / name).is_file():
                    (work / name).rename(info.path / name)
        finally:
            shutil.rmtree(work, ignore_errors=True)

        info.frame_count = count  # normally unchanged
        info.source = str(src)
        info.disk_bytes = _folder_bytes(info.path)
        info.save()
        if progress:
            progress(1.0)
        return info

    # --- importing ----------------------------------------------------------
    def import_clip(
        self,
        src: Path | str,
        progress: Optional[ProgressCallback] = None,
        cancel: Optional[threading.Event] = None,
    ) -> ClipInfo:
        # Import `src`, or return the existing import. Runs for a while on
        # big files, so the app calls this from a background thread.
        src = Path(src).resolve()
        if not src.is_file():
            raise ImportFailed(f"File not found: {src}")

        existing = self.find(src)
        if existing:
            if not existing.has_frames:  # imported before, then unloaded
                return self.reload_clip(existing.id, src, progress, cancel)
            if progress:
                progress(1.0)
            return existing

        cid = clip_id(src)
        final = self.root / cid
        work = self.root / f"{cid}.part"
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(final, ignore_errors=True)  # an old-format import

        info_in = ffmpeg.probe(src)
        rate = timebase.snap_frame_rate(info_in.fps or 25.0)

        try:
            work.mkdir(parents=True)
            try:
                count, w, h = ingest.extract(src, work, rate, info_in.has_audio,
                                             info_in.duration, progress, cancel)
                has_audio = info_in.has_audio
            except ImportFailed:
                if not info_in.has_audio:
                    raise
                # Unusual audio shouldn't stop the video importing: retry without it.
                shutil.rmtree(work)
                work.mkdir(parents=True)
                count, w, h = ingest.extract(src, work, rate, False,
                                             info_in.duration, progress, cancel)
                has_audio = False

            info = ClipInfo(
                id=cid,
                name=src.name,
                source=str(src),
                frame_rate=str(rate),  # "30000/1001" or "50"
                frame_count=count,
                width=w,
                height=h,
                has_audio=has_audio,
                imported_at=datetime.now().isoformat(timespec="microseconds"),  # orders batch imports
                disk_bytes=_folder_bytes(work),
                folder=str(work),
            )
            info.save()
            work.rename(final)
        except BaseException:
            shutil.rmtree(work, ignore_errors=True)
            raise

        info.folder = str(final)
        if progress:
            progress(1.0)
        return info


def _folder_bytes(folder: Path) -> int:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
