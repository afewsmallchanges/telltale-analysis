# help_dialogs.py
# Help menu: keyboard shortcuts and About.

from __future__ import annotations

from importlib import metadata

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QMessageBox, QVBoxLayout

SHORTCUTS = [
    ("Library", [
        ("Open a scene or clip", "Double-click, Enter"),
        ("New project", "Ctrl+N"),
        ("New scene (in the current project)", "Ctrl+Shift+N"),
        ("Import clips", "Ctrl+I"),
        ("Import boards (pictures, diagrams)", "Ctrl+B"),
        ("Rename project or scene", "F2"),
        ("Delete scene / remove clip", "Delete"),
        ("Select all", "Ctrl+A"),
        ("Unload a project (free disk space)", "Right-click it → Unload"),
        ("Load it again", "Right-click → Load, or open one of its scenes"),
    ]),
    ("Player", [
        ("Step 1 frame", "Scroll, jog wheel, ← / →, , / ."),
        ("Step 10 frames", "Shift+scroll, Shift+← / →"),
        ("Play / pause", "Space"),
        ("Start / end", "Home / End"),
        ("Add a clip or board to an empty view", "Click its +"),
        ("Switch scene", "Click it in the Scenes panel"),
        ("Zoom into part of the picture", "Crop button, then drag a box"),
    ]),
    ("Drawing", [
        ("Pick a tool", "Click it; click again (or Esc) to put it down"),
        ("Bendy arrow", "Draw the whole path; it follows every bend"),
        ("Circle instead of ellipse", "Hold Shift while dragging"),
        ("Quick / Hold", "Temporary drawings / saved, pinned to their frame"),
        ("Solid / Dashed", "Line style"),
        ("Clear what's on screen", "Clear Drawings (top of the selected view)"),
        ("Select a drawing", "Click it (with no tool picked up)"),
        ("Move it", "Drag it"),
        ("Delete it", "Delete or Backspace, or right-click → Delete drawing"),
        ("Recolour / restyle it", "Pick a colour or Solid / Dashed while it's selected"),
        ("Undo (drawings, moves, deletes, clears)", "Ctrl+Z, or Undo under the colours"),
        ("Redo what was undone", "Ctrl+Shift+Z or Ctrl+Y, or Redo"),
        ("Deselect / put the tool down", "Esc"),
        ("Remove every drawing in the scene", "Edit → Clear All"),
    ]),
    ("Boards", [
        ("See every board", "Boards, under All clips"),
        ("Import boards", "Import boards… button, Ctrl+B, or drop pictures on the window"),
        ("Put a board in a view", "Click the view's +, then the Boards tab"),
        ("Replace or remove a board", "Right-click the view, or its ✕"),
        ("Draw on a board", "As on a clip; Quick drawings stay until cleared"),
        ("Rename / delete a board", "F2 / Delete in Boards"),
    ]),
    ("Timer", [
        ("Start it / change mode", "Click Timer: DN, UP or D/U"),
        ("DN", "Counts down to the zero frame"),
        ("UP", "Counts up from the zero frame"),
        ("D/U", "Counts down, then up: zero at the frame"),
        ("Move the zero", "Drag the orange flag on the main timeline"),
        ("Zero at this frame", "T (starts the timer if it's off)"),
    ]),
    ("Split view", [
        ("Choose a layout", "Split button, then pick rows × columns"),
        ("1, 2, 3 or 4 views (usual layouts)", "Ctrl+Shift+1…4"),
        ("Select a view", "Click it"),
        ("Remove a clip / close a view", "✕ once empties the view, ✕ again closes it"),
        ("Replace or remove a clip", "Right-click the view"),
        ("Move all clips together", "Main timeline, jog wheel, ← / →"),
        ("Set one clip's sync point", "Drag its coloured bar"),
        ("Nudge the selected clip only", "Alt+← / →, or scroll over its bar"),
    ]),
    ("Anywhere", [
        ("Show library", "Ctrl+1"),
        ("Show player", "Ctrl+2"),
        ("Open clip and play it", "Ctrl+O"),
        ("Full screen", "F11 (or F in the player), Esc to leave"),
        ("Settings", "Ctrl+,"),
        ("This list", "F1"),
        ("Quit", "Ctrl+Q"),
    ]),
]


def app_version() -> str:
    try:
        return metadata.version("telltale-analysis")
    except metadata.PackageNotFoundError:
        return "development"


def show_shortcuts(parent=None):
    rows = []
    for group, items in SHORTCUTS:
        rows.append(f"<tr><td colspan=2 style='padding-top:10px'><b>{group}</b></td></tr>")
        for what, keys in items:
            rows.append(f"<tr><td style='padding-right:24px'>{what}</td><td>{keys}</td></tr>")

    dialog = QDialog(parent)
    dialog.setWindowTitle("Keyboard shortcuts")
    label = QLabel(f"<table>{''.join(rows)}</table>")
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    layout = QVBoxLayout(dialog)
    layout.addWidget(label)
    layout.addWidget(buttons)
    dialog.exec()


def show_about(parent=None, app_title: str = "Telltale Analysis"):
    QMessageBox.about(
        parent,
        f"About {app_title}",
        f"<h3>{app_title}</h3>"
        f"<p>Version {app_version()}</p>"
        "<p>Frame-by-frame video review and analysis for sailing footage.</p>"
        "<p>Free software, licensed under the GNU General Public License v3 or later.</p>"
        "<p>Report issues or suggest new features on the GitHub issues page "
        "<a href='https://github.com/afewsmallchanges/telltale-analysis/issues'>here</a>.</p>",
    )
