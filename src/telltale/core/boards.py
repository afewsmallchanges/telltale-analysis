# boards.py
# Boards: still images or diagrams (course maps, start-line plans, rule
# diagrams…) that can go in a scene's view and be drawn on, like a clip.
#
#   <data>/boards/<board id>/
#       board.json       this record
#       image.png        the picture, cleaned up (see below)
#       thumb.jpg        small preview for the library
#
# On import every picture is stored as a PNG: transparent areas become white
# (diagrams are usually drawn on white), and very large pictures are scaled
# down so they stay quick to draw. The original file is never changed.
#
# Like clips, a board's id comes from the file's contents, so a renamed or
# moved file is recognised instead of being imported twice.
#
# No Qt in here. OpenCV reads PNG, JPEG, BMP, WebP, TIFF and (OpenCV 4.11+)
# GIF; for anything else, such as SVG, the app passes a `fallback` reader
# that uses Qt.

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from . import paths
from .ingest import ImportFailed

__all__ = ["BoardInfo", "BoardLibrary", "board_id", "load_image", "IMAGE_EXTENSIONS",
           "ImportFailed"]

# Bump when the folder layout or import settings change (re-import needed).
FORMAT_VERSION = 1
META_FILE = "board.json"
IMAGE_FILE = "image.png"
THUMB_FILE = "thumb.jpg"
THUMB_WIDTH = 320
MAX_SIDE = 4096          # longer side, in pixels, after import

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif", ".svg"}

# A reader for formats OpenCV can't open: path -> RGBA picture (H × W × 4,
# uint8), or None if it can't read it either.
Fallback = Callable[[Path], Optional[np.ndarray]]


@dataclass
class BoardInfo:
    id: str
    name: str               # shown in the library; starts as the file name without extension
    source: str             # where the original was last seen
    width: int
    height: int
    imported_at: str = ""
    version: int = FORMAT_VERSION
    # Not saved: where this board's folder is right now.
    folder: str = field(default="", compare=False)

    @property
    def path(self) -> Path:
        return Path(self.folder)

    @property
    def image_path(self) -> Path:
        return self.path / IMAGE_FILE

    @property
    def thumb_path(self) -> Path:
        return self.path / THUMB_FILE

    def save(self):
        data = {k: v for k, v in asdict(self).items() if k != "folder"}
        tmp = self.path / (META_FILE + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.path / META_FILE)  # never leaves a half-written file

    @classmethod
    def load(cls, folder: Path) -> Optional["BoardInfo"]:
        # None if the folder isn't a complete, current-version board.
        try:
            data = json.loads((Path(folder) / META_FILE).read_text())
        except (OSError, ValueError):
            return None
        known = {f.name for f in fields(cls)} - {"folder"}
        try:
            info = cls(**{k: v for k, v in data.items() if k in known})
        except TypeError:
            return None
        if info.version != FORMAT_VERSION or not (Path(folder) / IMAGE_FILE).is_file():
            return None
        info.folder = str(Path(folder))
        return info


def board_id(src: Path) -> str:
    # Hash of the whole file (pictures are small enough to read in full).
    h = hashlib.sha1()
    with open(src, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def load_image(board: BoardInfo) -> np.ndarray:
    # The board's picture as an RGB array (H × W × 3), ready to show.
    bgr = cv2.imdecode(np.fromfile(board.image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise IOError(f"Could not read the picture for board “{board.name}”")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def to_bgr(img: np.ndarray, rgba_order: bool = False) -> np.ndarray:
    # Any decoded picture -> 3-channel BGR. Grey stays grey; transparent
    # areas are laid over white. `rgba_order`: channels are R,G,B(,A).
    if img.dtype == np.uint16:          # 16-bit PNG / TIFF
        img = (img // 257).astype(np.uint8)
    elif img.dtype != np.uint8:         # floating-point TIFF
        scale = 255.0 if float(img.max()) <= 1.0 else 1.0
        img = np.clip(img * scale, 0, 255).astype(np.uint8)
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    channels = img.shape[2]
    if channels == 1:
        return cv2.cvtColor(img[:, :, 0], cv2.COLOR_GRAY2BGR)
    if channels == 2:                   # grey + transparency
        img = np.dstack([img[:, :, 0]] * 3 + [img[:, :, 1]])
        channels = 4
    if channels == 4:
        colour = img[:, :, :3].astype(np.float32)
        alpha = img[:, :, 3:4].astype(np.float32) / 255.0
        img = (colour * alpha + 255.0 * (1.0 - alpha)).round().astype(np.uint8)
    else:
        img = img[:, :, :3]
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if rgba_order else np.ascontiguousarray(img)


class BoardLibrary:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else paths.boards_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    # --- looking boards up ----------------------------------------------------
    def get(self, bid: str) -> Optional[BoardInfo]:
        return BoardInfo.load(self.root / bid)

    def find(self, src: Path | str) -> Optional[BoardInfo]:
        # The imported copy of `src`, if there is one.
        src = Path(src).resolve()
        info = self.get(board_id(src))
        if info and info.source != str(src):
            info.source = str(src)  # the original was moved or renamed
            info.save()
        return info

    def boards(self) -> list[BoardInfo]:
        # Every board, oldest first.
        found = []
        for folder in self.root.iterdir():
            if folder.is_dir() and not folder.name.endswith(".part"):
                info = BoardInfo.load(folder)
                if info:
                    found.append(info)
        return sorted(found, key=lambda b: b.imported_at)

    def total_size(self, boards: Optional[list[BoardInfo]] = None) -> int:
        return sum(_folder_bytes(b.path) for b in (boards if boards is not None else self.boards()))

    # --- changing -------------------------------------------------------------
    def rename(self, bid: str, name: str) -> BoardInfo:
        info = self.get(bid)
        if info is None:
            raise KeyError(f"No board with id {bid}")
        name = " ".join(name.split())[:120]
        if not name:
            raise ValueError("A name can't be empty.")
        info.name = name
        info.save()
        return info

    def remove(self, bid: str):
        shutil.rmtree(self.root / bid, ignore_errors=True)

    # --- importing --------------------------------------------------------------
    def import_board(self, src: Path | str, fallback: Optional[Fallback] = None) -> BoardInfo:
        # Import a picture (or return the existing import). Quick, so the app
        # calls it directly rather than from a background thread.
        src = Path(src).resolve()
        if not src.is_file():
            raise ImportFailed(f"File not found: {src}")
        existing = self.find(src)
        if existing:
            return existing

        bgr = _decode(src, fallback)
        h, w = bgr.shape[:2]
        if max(w, h) > MAX_SIDE:
            scale = MAX_SIDE / max(w, h)
            bgr = cv2.resize(bgr, (max(1, round(w * scale)), max(1, round(h * scale))),
                             interpolation=cv2.INTER_AREA)
            h, w = bgr.shape[:2]

        bid = board_id(src)
        final = self.root / bid
        work = self.root / f"{bid}.part"
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(final, ignore_errors=True)  # an old-format import
        try:
            work.mkdir(parents=True)
            _write(work / IMAGE_FILE, ".png", bgr)
            tw = THUMB_WIDTH
            thumb = cv2.resize(bgr, (tw, max(1, round(h * tw / w))),
                               interpolation=cv2.INTER_AREA if w > tw else cv2.INTER_LINEAR)
            _write(work / THUMB_FILE, ".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 88])
            info = BoardInfo(
                id=bid,
                name=src.stem,
                source=str(src),
                width=w,
                height=h,
                imported_at=datetime.now().isoformat(timespec="microseconds"),
                folder=str(work),
            )
            info.save()
            work.rename(final)
        except BaseException:
            shutil.rmtree(work, ignore_errors=True)
            raise
        info.folder = str(final)
        return info


def _decode(src: Path, fallback: Optional[Fallback]) -> np.ndarray:
    img = None
    if src.suffix.lower() != ".svg":
        img = cv2.imdecode(np.fromfile(src, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if img is not None:
            return to_bgr(img)
    if fallback is not None:
        rgba = fallback(src)
        if rgba is not None and rgba.size:
            return to_bgr(rgba, rgba_order=True)
    raise ImportFailed(f"{src.name} isn't a picture that can be opened "
                       "(PNG, JPEG, BMP, WebP, TIFF, GIF or SVG).")


def _write(path: Path, ext: str, img: np.ndarray, params: Optional[list] = None):
    ok, buf = cv2.imencode(ext, img, params or [])
    if not ok:
        raise ImportFailed(f"Could not save {path.name}")
    buf.tofile(path)


def _folder_bytes(folder: Path) -> int:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
