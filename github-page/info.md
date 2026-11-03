# General Information
Anything I thought was useful and should be put somewhere in a document.

## Where your data lives

| What | Linux | macOS | Windows |
|---|---|---|---|
| Imported clips | `~/.local/share/telltale/library/` | `~/Library/Application Support/telltale/library/` | `%LOCALAPPDATA%\telltale\library\` |
| Projects | `~/.local/share/telltale/projects/` | `~/Library/Application Support/telltale/projects/` | `%LOCALAPPDATA%\telltale\projects\` |
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

Each project is a folder holding `project.json`: its name, the ids of its
clips, and its scenes (which clip is in which view, sync offsets, zoom,
position, layout, timer, and Hold drawings). Projects never contain footage, so deleting one frees no space and
loses no clips. Help → Open data folder opens this location.

**Disk space:** roughly 50 KB per frame at 720p and 100–300 KB per frame at
1080p, so about 0.4–0.9 GB per minute of 1080p at 50 fps. Long race recordings
add up quickly; trimming before import is on the roadmap.


### Controls

| Action | Control |
|---|---|
| Step 1 frame | Scroll wheel (over the picture or main timeline), jog wheel, ← / →, `,` / `.` |
| Step 10 frames | Shift + scroll, Shift + ← / → |
| Nudge selected clip only | Alt + ← / →, or scroll over its coloured bar |
| Play / pause | Space |
| Slow motion | Speed box: 1×, ½×, ¼×, ⅒× |
| Start / end | Home / End |
| Jump | Click or drag the main timeline |
| Split view | Split button (pick rows × columns), or Ctrl+Shift+1…4 |
| New scene | Ctrl+Shift+N |
| Undo last drawing change | Ctrl+Z |
| Delete selected drawing | Delete or Backspace |
| Timer zero at this frame | T |
| Deselect / put the drawing tool down | Esc |
| Library / player | Ctrl+1 / Ctrl+2 |
| Full screen | F11, or F in the player (Esc to leave) |
| Settings | File → Settings (Ctrl+,) |
| All shortcuts | Help → Keyboard shortcuts (F1) |


### Project layout

```
src/telltale/
    app.py              starts the app
    settings.py         user settings (saved between sessions)
    core/               no Qt in here: video handling and data, testable alone
        library.py        the clip library on disk
        sync.py           split view: one master clock, an offset per clip
        drawings.py       drawings: building them from strokes, curves, hold timing
        timer.py          the DN / UP / D/U timer
        projects.py       projects and their scenes (project.json)
        ingest.py         video -> frames + audio + thumbnail
        clip.py           ClipInfo, the record saved as clip.json
        frames.py         FrameSource: frame N -> picture, with a cache
        timebase.py       exact frame rates, frames <-> seconds, timecodes
        ffmpeg.py         finding FFmpeg, reading a video's details
        paths.py          where data is stored on each OS
    ui/                 Qt windows and widgets
        main_window.py    menus, library <-> player, importing, shortcuts
        library_screen.py start screen: projects, Scenes | Clips tabs
        dialogs.py        question / name prompts, the "+" clip picker
        import_worker.py  imports clips on a background thread
        player.py         player screen: layout, views, timeline, transport
        video_pane.py     one view (QGraphicsView): picture, crop, drawing, sync bar
        drawing_layer.py  shows a view's drawings on the picture
        side_panels.py    Tools panel (tools, Quick/Hold, Solid/Dashed, colours, jog) and Scenes panel
        layout_picker.py  the split button's rows × columns grid
        jog_wheel.py      on-screen jog dial
        wheel.py          scroll-to-frames, timeline slider (with the timer's flag)
        icons.py          loads icons/*.svg
        settings_dialog.py  File -> Settings (one tab per group)
        help_dialogs.py   keyboard shortcuts, About
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
renamed/moved files, cancelling an import, the frame-rate maths, and
projects and scenes (sharing clips, saving and restoring scenes, older
project files), drawings (bendy arrows, circles, hold timing, selecting
and moving, saving), the timer (all three modes, exact at 29.97 fps,
saving), and split-view sync (clips at different frame rates staying in
step).

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


### Install Environment
`pip install -e .` installs the app in "editable" mode: the `telltale` command
runs the code in `src/` directly, so your changes take effect without
reinstalling. Re-run it only if `pyproject.toml` changes (e.g. new
dependencies). `python -m telltale` works too.

### How it's organised

- **Project:** a piece of work, e.g. one race day or one training session.
- **Scene:** a saved view of 1–4 of the project's clips side by side, e.g.
  "Start" with the bow camera and the drone synced on the gun. A scene
  remembers its clips, each clip's sync point, any zoom, and where you were.
- **Clip:** one imported video. Clips are stored once in the library; the
  same clip can be in any number of projects and scenes.

### The library (start screen)

The left side lists **All clips** (everything you've imported) and your
**projects**. A project opens on its **Scenes** tab; its **Clips** tab holds
the project's clips.

- **Import clips:** drag video files (or a folder of them) onto the window,
  or click *Import clips…* (Ctrl+I). If a project is open, they're added to
  it too.
- **Open a clip from All clips:** double-click it and choose *Start a new
  project* (which gets a first scene with that clip) or *Quick view* (just
  look; nothing is saved, but you can save it as a project afterwards).
- **Open a clip from a project's Clips tab:** choose *New scene with this
  clip* or *Quick view*.
- **New scene:** *New scene* on the Scenes tab, or Ctrl+Shift+N. It opens
  straight away with a **+** to add clips.
- **Add clips you've already imported to a project:** *Add from library…* on
  the Clips tab, or right-click clips → *Add to project*.
- **Rename or delete** a project (right-click it in the list) or a scene
  (right-click it, or select it and press F2 / Delete).
- **Remove / delete clips:** in a project's Clips tab, Delete removes the clip
  from the project and its scenes (it asks first if a scene uses it). In
  *All clips* it deletes the imported copy everywhere; your original video
  file is never touched.

### The player

```
 Tools         video (1–4 views)  [crop][split]   Scenes
 jog wheel                                         (click to switch,
 transport     main timeline                        + for a new one)
```

- **Scenes (right):** the project's scenes. Click one to switch to it,
  **+** to start a new one, right-click to rename or delete.
  *File → Return to Projects* (or Ctrl+1) goes back to the start screen,
  from a scene or a quick view.
- **Adding clips:** an empty view shows **+**. Click it to pick a clip from
  this project or the full library (up to 4 clips per scene). The same clip
  can go in two views, e.g. to compare two tacks from one camera.
- **Jog wheel (left):** drag it round to step frames, clockwise = forward.
  Works with touch screens. It also turns by itself while the video plays or
  is scrubbed. How far to turn per frame is in File → Settings.
- **Crop / zoom** (top-right of the video): click, then drag a box over the
  picture to zoom into it. Click again to show the whole picture.
- **Split view** (top-right of the video): pick a layout from the grid —
  rows × columns, up to 4 views (e.g. 1×2 side by side, 2×1 stacked, 2×2,
  1×4). Ctrl+Shift+1…4 gives the usual layout for that many views. Click a
  view to select it.
- **Changing a view's clip:** its ✕ first takes the clip out (the view shows
  **+** again); ✕ on an empty view closes it. Or right-click a view for
  *Replace clip…* / *Remove clip*.
- **Lining clips up:** each view gets its own coloured bar. Drag a clip's bar
  to the matching moment (e.g. the start gun), then use the main timeline,
  jog wheel, arrow keys or Play to move all clips together. To nudge just the
  selected clip a frame at a time, use Alt+← / → or scroll over its bar.
- **Saving:** scenes save themselves as you work; there's no Save button.
- **Drawing (left):** pick a tool — **Line**, **Straight arrow**,
  **Bendy arrow**, **Circle** or **Pen** — and drag on the video. Click the
  tool again (or press Esc) to put it down. The bendy arrow follows the whole
  path you draw, however many times it snakes back and forth. Hold Shift for
  a perfect circle. Pick a colour, and **Solid** or **Dashed**.
  - **Quick:** temporary drawings. They vanish as soon as the frame changes
    and aren't saved.
  - **Hold:** saved with the scene and pinned to the frame they were drawn
    on, staying on screen for a short hold either side (0.5 s by default;
    File → Settings → Drawing).
  - **Clear Drawings** appears at the top of the selected view while it has
    drawings on screen, and removes them — kept away from the tools so it
    isn't hit by accident.
  - **Editing a drawing:** with no tool picked up, click a drawing to select
    it (a dashed box appears). Drag it to move it; press Delete or Backspace
    (or right-click → *Delete drawing*) to remove it; pick a colour or
    Solid / Dashed to restyle it. Esc deselects.
  - **Edit → Undo drawing** (Ctrl+Z) undoes the last drawing change — a new
    drawing, a move, a delete, a restyle or a clear.
    **Edit → Clear All** removes every drawing in the scene.
- **Timer (top of the tools):** click it and pick a mode:
  - **DN** — counts down to the zero frame (and holds at 0:00.00 after it),
  - **UP** — counts up from the zero frame,
  - **D/U** — counts down, then up, with zero at the frame (−0:05.20 … +0:03.12).

  Starting the timer puts its zero at the current frame, shown as an
  **orange flag** on the main timeline. Drag the flag to move the zero, or
  press **T** to put it on the current frame. The button shows the mode and
  time; the time can also be shown on the video (timer menu → *Show timer on
  the video*). Each scene saves its timer. The timer runs on the scene clock,
  so it's exact in split view and with clips at different frame rates.