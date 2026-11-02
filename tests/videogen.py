# videogen.py
# Makes test videos whose frame number is drawn in the picture as 16
# black/white blocks, so a test can check it got exactly the right frame.
# Encoded like normal camera footage (long GOP, B-frames), optionally with
# a test tone as audio.

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from telltale.core.ffmpeg import ffmpeg_exe

BITS, BLOCK = 16, 32


def make_clip(path: Path, w: int, h: int, fps: str, n_frames: int, audio: bool = False) -> Path:
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", fps, "-i", "-"]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                "-c:a", "aac", "-shortest"]
    even = w % 2 == 0 and h % 2 == 0
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-g", "250", "-bf", "3",
            "-pix_fmt", "yuv420p" if even else "yuv444p", str(path)]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    yy, xx = np.mgrid[0:h, 0:w]
    rng = np.random.default_rng(0)
    for i in range(n_frames):
        frame = np.empty((h, w, 3), np.uint8)
        frame[..., 0] = (xx + i * 7) % 256
        frame[..., 1] = (yy + i * 3) % 256
        frame[..., 2] = 128
        frame = np.clip(frame + rng.integers(-12, 12, frame.shape), 0, 255).astype(np.uint8)
        for b in range(BITS):
            frame[0:BLOCK, b * BLOCK:(b + 1) * BLOCK] = 255 if (i >> b) & 1 else 0
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    assert proc.wait() == 0
    return path


def read_index(rgb: np.ndarray) -> int:
    # The frame number drawn by make_clip.
    n = 0
    for b in range(BITS):
        cell = rgb[BLOCK // 4: 3 * BLOCK // 4,
                   b * BLOCK + BLOCK // 4: (b + 1) * BLOCK - BLOCK // 4]
        if cell.mean() > 128:
            n |= 1 << b
    return n
