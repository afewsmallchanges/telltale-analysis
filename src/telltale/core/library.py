# library.py
# The clip library: every imported clip lives in its own folder under
# paths.library_dir(), named by its clip id (see clip.py for the layout).
#
# A clip's id comes from the contents of the original file, not its name or
# location, so a renamed or moved file is recognised instead of being
# imported a second time.

from __future__ import annotations

import hashlib
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import ffmpeg, ingest, paths, timebase
from .clip import ClipInfo
from .ingest import ImportCancelled, ImportFailed, ProgressCallback

__all__ = ["Library", "clip_id", "ImportCancelled", "ImportFailed"]

_SAMPLE = 1024 * 1024  # bytes read from each end of the file for the id


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
        return sum(f.stat().st_size for f in (self.root / cid).rglob("*") if f.is_file())

    def remove(self, cid: str):
        shutil.rmtree(self.root / cid, ignore_errors=True)

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
                imported_at=datetime.now().isoformat(timespec="seconds"),
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
