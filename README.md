# Telltale Analysis

A video playback and analysis application for reviewing sailing footage, with:

1. Frame-by-frame control (scroll wheel or touchpad, forwards and backwards)
2. Drawing on video *(planned)*
3. Side-by-side playback *(planned)*

See [ROADMAP.md](ROADMAP.md) for what's planned.


## Dependencies

Python 3.10 or newer, plus one system library for Qt's X11 support (Wayland
works without it).

### Ubuntu
```bash
sudo apt install python3-venv libxcb-cursor0
```

### Fedora
```bash
sudo dnf install python3 xcb-util-cursor
```

Everything else (Qt, OpenCV, FFmpeg) is installed by `pip` in the next step.


## How to use

First time, from the project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Then, any time:

```bash
source .venv/bin/activate
telltale                      # then Ctrl+O, or drag a clip onto the window
telltale path/to/clip.mp4
```

`pip install -e .` installs the app in "editable" mode: the `telltale` command
runs the code in `src/` directly, so your changes take effect without
reinstalling. Re-run it only if `pyproject.toml` changes (e.g. new
dependencies). `python -m telltale` works too.

### Controls

| Action | Control |
|---|---|
| Step 1 frame | Scroll wheel (over the picture or timeline), ← / →, `,` / `.` |
| Step 10 frames | Shift + scroll, Shift + ← / → |
| Play / pause | Space |
| Slow motion | Speed box: 1×, ½×, ¼×, ⅒× |
| First / last frame | Home / End |
| Jump | Click or drag the timeline |
| Full screen | F (Esc to leave) |
| Scroll settings | Settings → Scroll & touchpad (Ctrl+,) |


## How to use (if you aren't a software person)

1. Open a **Terminal** (search for "Terminal" in your applications).
2. Install the system parts by copying the line for your system from
   *Dependencies* above, pasting it into the terminal and pressing Enter.
   It will ask for your password.
3. Go to the folder where you unzipped or downloaded Telltale, for example:
   ```bash
   cd ~/Downloads/telltale-analysis
   ```
4. Copy and paste these three lines, one at a time (the last one downloads
   a few hundred MB and takes a minute or two):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```
5. Start the app:
   ```bash
   telltale
   ```

Next time, you only need steps 1, 3, the `source .venv/bin/activate` line, and
step 5.

The first time you open a video, Telltale imports it (there's a progress bar).
After that, opening the same video is instant, even if you've renamed or moved
the file.


## Where your data lives

| What | Linux | macOS | Windows |
|---|---|---|---|
| Imported clips | `~/.local/share/telltale/library/` | `~/Library/Application Support/telltale/library/` | `%LOCALAPPDATA%\telltale\library\` |
| Settings | `~/.config/telltale/telltale.conf` | `~/Library/Preferences/com.telltale.telltale.plist` | Registry |

Each imported clip has its own folder:

```
library/<clip id>/
    clip.json     frame rate, size, frame count, original file location
    frames/       000000.jpg, 000001.jpg, ... one picture per frame
    audio.m4a     the clip's sound (if it had any)
    thumb.jpg     preview picture
```

The clip id comes from the video file's contents, not its name, so renamed or
moved files are recognised. Deleting a clip's folder is safe: it is imported
again next time the video is opened.

**Disk space:** roughly 50 KB per frame at 720p and 100–300 KB per frame at
1080p, so about 0.4–0.9 GB per minute of 1080p at 50 fps. Long race recordings
add up quickly; trimming before import is on the roadmap.


## Notes during development

### Project layout

```
src/telltale/
    app.py              starts the app
    settings.py         user settings (saved between sessions)
    core/               no Qt in here: video handling and data, testable alone
        library.py        the clip library on disk
        ingest.py         video -> frames + audio + thumbnail
        clip.py           ClipInfo, the record saved as clip.json
        frames.py         FrameSource: frame N -> picture, with a cache
        timebase.py       exact frame rates, frames <-> seconds, timecodes
        ffmpeg.py         finding FFmpeg, reading a video's details
        paths.py          where data is stored on each OS
    ui/                 Qt windows and widgets
        main_window.py    menus, opening clips, shortcuts
        player.py         picture, timeline, transport buttons, scroll wheel
        settings_dialog.py
        theme.py          dark colour scheme
        icons/            transport button SVGs
tests/                  pytest tests for core/
```

Keeping `core/` free of Qt means it can be tested without a display, and the
same code can serve later features (tracking, other platforms).

### Tests

```bash
pip install -e ".[dev]"     # once, adds pytest
pytest
```

The tests create short videos with the frame number drawn into the picture,
import them, and check that every frame comes back exactly right forwards,
backwards and at random, for several sizes and frame rates (including
29.97 / 59.94 fps). They also check audio extraction, recognising
renamed/moved files, cancelling an import, and the frame-rate maths.

### Frame stepping

Normal H.264/H.265 video only stores a complete picture every few seconds, so
stepping *backwards* means decoding everything since that picture: about
250 ms per step at 1080p. Importing stores each frame as its own JPEG, so any
frame is one decode, about 6 ms at 1080p, in either direction.

### Frame rates

Frame rates are stored exactly (29.97 fps is really 30000/1001). Using the
rounded number would make timers and side-by-side sync drift by 3.6 seconds
an hour. Phone footage with a slightly variable rate (e.g. 29.83) is
converted to the nearest standard rate on import.

### FFmpeg
The environment prefers the copy bundled with the `imageio-ffmpeg` pip package, so the app behaves the same on every distro.
Set IMAGEIO_FFMPEG_EXE to force a specific binary.


## Attribution
Significant Portions of the early part of this project was developed with assistance from Claude Opus 5.5 (High)
