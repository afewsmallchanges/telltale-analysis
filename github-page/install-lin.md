## Linux Install Instructions

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
telltale                      # opens the library (start screen)
telltale path/to/clip.mp4     # imports and plays a clip straight away
```


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