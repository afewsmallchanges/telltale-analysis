# Importing clips into the library, and frame-accurate access afterwards.

import json
import random
import shutil
import threading
from fractions import Fraction

import pytest
from videogen import make_clip, read_index

from telltale.core.clip import FORMAT_VERSION, ClipInfo
from telltale.core.frames import FrameSource
from telltale.core.library import ImportCancelled, ImportFailed, clip_id


@pytest.mark.parametrize("w, h, fps, n, exact_rate", [
    (1280, 720, "50", 400, Fraction(50)),
    (641, 361, "30000/1001", 240, Fraction(30000, 1001)),  # odd size, NTSC rate
    (1920, 1080, "60000/1001", 150, Fraction(60000, 1001)),
])
def test_every_frame_is_exact(library, videos, w, h, fps, n, exact_rate):
    src = make_clip(videos / "clip.mp4", w, h, fps, n)
    seen = []
    info = library.import_clip(src, progress=seen.append)

    assert (info.frame_count, info.width, info.height) == (n, w, h)
    assert info.rate == exact_rate
    assert seen[-1] == 1.0

    fs = FrameSource(info, cache_mb=0)  # cache off: every request really decodes
    for i in range(n):                                      # forwards
        assert read_index(fs.frame(i)) == i
    for i in range(n - 1, -1, -1):                          # backwards
        assert read_index(fs.frame(i)) == i
    rnd = random.Random(1)
    for i in (rnd.randrange(n) for _ in range(200)):        # random jumps
        assert read_index(fs.frame(i)) == i
    assert read_index(fs.frame(-5)) == 0                    # clamped
    assert read_index(fs.frame(10**6)) == n - 1


def test_folder_contents_and_audio(library, videos):
    with_audio = library.import_clip(make_clip(videos / "a.mp4", 640, 360, "25", 50, audio=True))
    silent = library.import_clip(make_clip(videos / "b.mp4", 640, 360, "25", 50))

    assert with_audio.has_audio and with_audio.audio_path.stat().st_size > 1000
    assert not silent.has_audio and silent.audio_path is None
    for info in (with_audio, silent):
        assert info.thumb_path.stat().st_size > 0
        saved = json.loads((info.path / "clip.json").read_text())
        assert saved["id"] == info.id and "folder" not in saved
        assert info.path.name == info.id


def test_reopening_is_instant_and_recognises_moved_files(library, videos):
    src = make_clip(videos / "race3.mp4", 640, 360, "25", 50)
    first = library.import_clip(src)

    moved = videos / "elsewhere" / "renamed.mp4"
    moved.parent.mkdir()
    src.rename(moved)
    again = library.import_clip(moved)

    assert again.id == first.id and again.path == first.path
    assert again.source == str(moved.resolve())
    assert ClipInfo.load(first.path).source == str(moved.resolve())  # saved
    assert len(library.clips()) == 1


def test_different_videos_get_different_ids(videos):
    a = make_clip(videos / "a.mp4", 640, 360, "25", 50)
    b = make_clip(videos / "b.mp4", 640, 360, "25", 51)
    assert clip_id(a) != clip_id(b)
    shutil.copy(a, videos / "copy.mp4")
    assert clip_id(a) == clip_id(videos / "copy.mp4")


def test_old_format_is_imported_again(library, videos):
    src = make_clip(videos / "a.mp4", 640, 360, "25", 50)
    info = library.import_clip(src)
    meta = info.path / "clip.json"
    data = json.loads(meta.read_text())
    data["version"] = FORMAT_VERSION - 1
    meta.write_text(json.dumps(data))

    assert library.find(src) is None
    assert library.import_clip(src).version == FORMAT_VERSION


def test_list_size_and_remove(library, videos):
    a = library.import_clip(make_clip(videos / "a.mp4", 640, 360, "25", 30))
    b = library.import_clip(make_clip(videos / "b.mp4", 640, 360, "25", 40))
    assert {c.id for c in library.clips()} == {a.id, b.id}
    assert library.size_on_disk(a.id) > 0
    library.remove(a.id)
    assert [c.id for c in library.clips()] == [b.id]


def test_cancel_leaves_nothing_behind(library, videos):
    src = make_clip(videos / "big.mp4", 1920, 1080, "50", 300)
    stop = threading.Event()
    with pytest.raises(ImportCancelled):
        library.import_clip(src, progress=lambda p: p > 0.05 and stop.set(), cancel=stop)
    assert list(library.root.iterdir()) == []


def test_bad_files(library, videos):
    with pytest.raises(ImportFailed):
        library.import_clip(videos / "missing.mp4")
    junk = videos / "junk.mp4"
    junk.write_bytes(b"not a video" * 1000)
    with pytest.raises(ImportFailed):
        library.import_clip(junk)
    assert list(library.root.iterdir()) == []
