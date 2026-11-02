# ingest.py
# Turns a video file into a clip folder: one JPEG per frame, plus the audio
# and a thumbnail. (Library.import_clip decides where the folder goes.)
#
# Why one JPEG per frame: normal H.264/H.265 footage only stores a complete
# picture every few seconds, so stepping *backwards* one frame means decoding
# everything since that picture (~250 ms at 1080p). With each frame in its
# own file, showing any frame is one JPEG decode (~6 ms at 1080p), in either
# direction. The cost is disk space: ~100-300 KB per 1080p frame.

from __future__ import annotations

import subprocess
import threading
from fractions import Fraction
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from . import ffmpeg
from .clip import AUDIO_FILE, FRAME_PATTERN, FRAMES_DIR, THUMB_FILE

JPEG_QUALITY = 3      # FFmpeg -q:v scale, 2 (best) .. 31 (worst)
AUDIO_BITRATE = "192k"
THUMB_WIDTH = 320

ProgressCallback = Callable[[float], None]


class ImportCancelled(Exception):
    pass


class ImportFailed(Exception):
    pass


def build_command(src: Path, dest: Path, rate: Fraction, with_audio: bool, exe: str) -> list[str]:
    cmd = [exe, "-hide_banner", "-nostdin", "-y",
           "-progress", "pipe:1", "-nostats",
           "-i", str(src)]

    # Video -> frames/000000.jpg ... at an exact, constant frame rate, so
    # "frame N" always means the same moment in time.
    cmd += ["-map", "0:v:0"]
    cmd += ["-fps_mode", "cfr"] if ffmpeg.major_version(exe) >= 5 else ["-vsync", "cfr"]
    cmd += ["-r", f"{rate.numerator}/{rate.denominator}",
            "-c:v", "mjpeg", "-q:v", str(JPEG_QUALITY), "-pix_fmt", "yuvj420p",
            "-start_number", "0",
            str(dest / FRAMES_DIR / FRAME_PATTERN)]

    # Audio -> audio.m4a (kept for real-time playback with sound, later)
    if with_audio:
        cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", AUDIO_BITRATE,
                str(dest / AUDIO_FILE)]
    return cmd


def extract(
    src: Path,
    dest: Path,
    rate: Fraction,
    with_audio: bool,
    duration: Optional[float] = None,
    progress: Optional[ProgressCallback] = None,
    cancel: Optional[threading.Event] = None,
) -> tuple[int, int, int]:
    # Fills the (empty) folder `dest`. Returns (frame_count, width, height).
    # `progress` gets values 0.0-1.0; setting `cancel` raises ImportCancelled.
    # On failure, `dest` may be left half-filled: the caller deletes it.
    exe = ffmpeg.ffmpeg_exe()
    (dest / FRAMES_DIR).mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        build_command(src, dest, rate, with_audio, exe),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    # Drain stderr on a side thread so FFmpeg never blocks on a full pipe.
    err_lines: list[str] = []
    drain = threading.Thread(target=lambda: err_lines.extend(proc.stderr), daemon=True)
    drain.start()

    try:
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.terminate()
                proc.wait()
                raise ImportCancelled()
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and duration and progress:
                try:
                    progress(min(int(value) / 1e6 / duration, 0.99))
                except ValueError:
                    pass
        proc.wait()
        drain.join(timeout=2)
    finally:
        if proc.poll() is None:
            proc.kill()

    if proc.returncode != 0:
        tail = "".join(err_lines[-15:]).strip()
        raise ImportFailed(f"FFmpeg could not import {src.name}:\n{tail}")

    frames = sorted((dest / FRAMES_DIR).glob("*.jpg"))
    if not frames:
        raise ImportFailed(f"No video frames found in {src.name}")
    width, height = jpeg_size(frames[0])
    make_thumbnail(frames[len(frames) // 10], dest / THUMB_FILE)
    return len(frames), width, height


def make_thumbnail(frame: Path, out: Path):
    # Small preview for the library, taken 10% in (skips black starts).
    img = cv2.imdecode(np.fromfile(frame, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return
    h, w = img.shape[:2]
    small = cv2.resize(img, (THUMB_WIDTH, max(1, round(h * THUMB_WIDTH / w))),
                       interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if ok:
        buf.tofile(out)


def jpeg_size(path: Path) -> tuple[int, int]:
    # Read width/height from a JPEG header without decoding it.
    with open(path, "rb") as f:
        data = f.read(65536)
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            return w, h
        i += 2 + length
    raise ImportFailed(f"Could not read frame size from {path.name}")
