# ffmpeg.py
# Finding FFmpeg and reading basic facts about a video file.
#
# Prefers the FFmpeg bundled with the imageio-ffmpeg pip package, so the app
# behaves the same on every distro. Set IMAGEIO_FFMPEG_EXE to force a
# specific binary.

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class FFmpegMissing(Exception):
    pass


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = shutil.which("ffmpeg")
        if not exe:
            raise FFmpegMissing(
                "FFmpeg not found. Install it with `pip install imageio-ffmpeg` "
                "or your distro's ffmpeg package."
            ) from None
        return exe


_version_cache: dict[str, int] = {}


def major_version(exe: str) -> int:
    if exe not in _version_cache:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True).stdout
        m = re.search(r"ffmpeg version n?(\d+)", out)
        _version_cache[exe] = int(m.group(1)) if m else 7
    return _version_cache[exe]


@dataclass
class ProbeResult:
    duration: Optional[float]   # seconds
    fps: Optional[float]        # as FFmpeg reports it, e.g. 29.97
    has_audio: bool


def probe(src: Path, exe: Optional[str] = None) -> ProbeResult:
    # Reads FFmpeg's description of the file (no ffprobe needed).
    exe = exe or ffmpeg_exe()
    err = subprocess.run(
        [exe, "-hide_banner", "-nostdin", "-i", str(src)],
        capture_output=True,
        text=True,
    ).stderr

    duration = fps = None
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        h, mnt, s = m.groups()
        duration = int(h) * 3600 + int(mnt) * 60 + float(s)

    video_line = next((line for line in err.splitlines() if "Video:" in line), "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", video_line) or re.search(
        r"(\d+(?:\.\d+)?)\s*tbr", video_line
    )
    if m:
        fps = float(m.group(1))

    has_audio = any("Audio:" in line for line in err.splitlines() if "Stream #" in line)
    return ProbeResult(duration, fps, has_audio)
