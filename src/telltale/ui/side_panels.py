# side_panels.py
# The player's side panels: Tools (left) and Clip Library (right).

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import icon
from .jog_wheel import JogWheel

PANEL_WIDTH = 190
TOOL_SIZE = 64


def _panel_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    f = label.font()
    f.setPointSize(f.pointSize() + 1)
    f.setBold(True)
    label.setFont(f)
    return label


DRAW_COLOURS = [  # swatches under the tools
    ("#ff3b30", "Red"), ("#ffd60a", "Yellow"), ("#34c759", "Green"),
    ("#0a84ff", "Blue"), ("#ffffff", "White"), ("#111111", "Black"),
]
TOOLS = [  # (tool id, icon, tooltip)
    ("line", "line", "Line — drag from one end to the other (laylines, start lines…)"),
    ("arrow", "arrow", "Straight arrow — drag from the tail to the point"),
    ("bendy", "bendy", "Bendy arrow — draw the path, as many bends as you like"),
    ("ellipse", "ellipse", "Circle / ellipse — drag across it; hold Shift for a circle"),
    ("pen", "pen", "Pen — draw freehand"),
]
SEGMENT_STYLE = """
    QToolButton { border: 1px solid #55555c; padding: 4px 0; background: #2a2a2f; }
    QToolButton:checked { background: #7a2cf0; color: white; border-color: #7a2cf0; }
    QToolButton:hover:!checked { background: #36363c; }
"""


def _segmented(parent: QWidget, options: list[tuple[str, str, str]], on_pick) -> tuple[QHBoxLayout, dict]:
    # A row of joined buttons where exactly one is chosen. Each row gets its
    # own QButtonGroup, so choosing in one row never clears another row.
    row = QHBoxLayout()
    row.setSpacing(0)
    group = QButtonGroup(parent)
    group.setExclusive(True)
    buttons = {}
    for value, text, tip in options:
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(True)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        b.setStyleSheet(SEGMENT_STYLE)
        b.clicked.connect(lambda _c=False, v=value: on_pick(v))
        group.addButton(b)
        row.addWidget(b)
        buttons[value] = b
    return row, buttons


class ToolsPanel(QWidget):
    # Drawing tools, Quick | Hold, Solid | Dashed, colours and the jog wheel.
    # Click a tool to draw with it; click it again to put it down.

    toolChanged = Signal(object)    # tool id, or None
    modeChanged = Signal(str)       # "quick" or "hold"
    styleChanged = Signal(str)      # "solid" or "dashed"
    colourChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(PANEL_WIDTH)
        self.tool: Optional[str] = None

        def square(tip: str) -> QToolButton:
            b = QToolButton()
            b.setFixedSize(TOOL_SIZE, TOOL_SIZE)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setToolTip(tip)
            return b

        # Timer: click for DN / UP / D/U; shows the mode and the time.
        self.timer_tool = square("Timer: count down to / up from a frame — click for options. "
                                 "Drag the orange flag on the timeline to move its zero.")
        self.timer_tool.setText("Timer\n—")
        self.timer_tool.setCheckable(True)
        self.timer_tool.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.timer_tool.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        tf = QFont("monospace")
        tf.setStyleHint(QFont.StyleHint.Monospace)
        tf.setPointSize(9)
        tf.setBold(True)
        self.timer_tool.setFont(tf)

        self.tool_buttons: dict[str, QToolButton] = {}
        for tool_id, icon_name, tip in TOOLS:
            b = square(tip)
            b.setCheckable(True)
            b.setIcon(icon(icon_name))
            b.setIconSize(QSize(40, 40))
            b.clicked.connect(lambda checked, t=tool_id: self.set_tool(t if checked else None))
            self.tool_buttons[tool_id] = b

        grid = QGridLayout()
        grid.setSpacing(10)
        order = [self.timer_tool, self.tool_buttons["line"],
                 self.tool_buttons["arrow"], self.tool_buttons["bendy"],
                 self.tool_buttons["ellipse"], self.tool_buttons["pen"]]
        for i, b in enumerate(order):
            grid.addWidget(b, i // 2, i % 2, Qt.AlignmentFlag.AlignCenter)

        modes, self.mode_buttons = _segmented(self, [
            ("quick", "Quick", "Quick: temporary drawings — they vanish when the frame changes "
                               "and aren't saved"),
            ("hold", "Hold", "Hold: saved with the scene and shown on their frame, with a short "
                             "hold either side (File → Settings → Drawing)"),
        ], self.set_mode)
        styles, self.style_buttons = _segmented(self, [
            ("solid", "Solid", "Solid lines"),
            ("dashed", "Dashed", "Dashed lines"),
        ], self.set_style)

        # Colours
        self.colour_buttons: dict[str, QToolButton] = {}
        colour_group = QButtonGroup(self)
        colour_group.setExclusive(True)
        colours = QHBoxLayout()
        colours.setSpacing(4)
        for value, name in DRAW_COLOURS:
            b = QToolButton()
            b.setFixedSize(24, 24)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setToolTip(name)
            b.setStyleSheet(
                f"QToolButton {{ background: {value}; border: 2px solid #4a4a52; border-radius: 12px; }}"
                f"QToolButton:checked {{ border: 3px solid #f2f2f5; }}")
            b.clicked.connect(lambda _c=False, v=value: self.set_colour(v))
            colour_group.addButton(b)
            self.colour_buttons[value] = b
            colours.addWidget(b)

        self.jog = JogWheel()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(8)
        layout.addWidget(_panel_title("Tools"))
        layout.addLayout(grid)
        layout.addSpacing(2)
        layout.addLayout(modes)
        layout.addLayout(styles)
        layout.addLayout(colours)
        layout.addSpacing(2)
        layout.addWidget(self.jog, 1)

        self.mode = "quick"
        self.style = "solid"
        self.colour = DRAW_COLOURS[0][0]

    def set_tool(self, tool: Optional[str]):
        self.tool = tool
        for t, b in self.tool_buttons.items():
            b.setChecked(t == tool)
        self.toolChanged.emit(tool)

    def set_mode(self, mode: str):
        self.mode = mode if mode in self.mode_buttons else "quick"
        self.mode_buttons[self.mode].setChecked(True)
        self.modeChanged.emit(self.mode)

    def set_style(self, style: str):
        self.style = style if style in self.style_buttons else "solid"
        self.style_buttons[self.style].setChecked(True)
        self.styleChanged.emit(self.style)

    def set_colour(self, colour: str):
        if colour not in self.colour_buttons:
            colour = DRAW_COLOURS[0][0]
        self.colour = colour
        self.colour_buttons[colour].setChecked(True)
        self.colourChanged.emit(colour)


class ScenesPanel(QWidget):
    # The project's scenes. Click one to open it; "+" starts a new scene.
    # In quick view (no project) it offers to save what's on screen as a project.

    sceneChosen = Signal(str)
    newSceneRequested = Signal()
    renameSceneRequested = Signal(str)
    deleteSceneRequested = Signal(str)
    saveQuickViewRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(PANEL_WIDTH + 10)

        self.title = _panel_title("Scenes")
        self.subtitle = QLabel()
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setStyleSheet("color: #a0a0a8;")
        self.subtitle.setWordWrap(True)

        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setFlow(QListView.Flow.TopToBottom)
        self.list.setWrapping(False)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setIconSize(QSize(160, 90))
        self.list.setGridSize(QSize(174, 136))
        self.list.setWordWrap(True)
        self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(lambda item: self.sceneChosen.emit(item.data(Qt.ItemDataRole.UserRole)))
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)

        self.add_btn = QPushButton("+")
        f = QFont(self.add_btn.font())
        f.setPointSize(f.pointSize() + 18)
        f.setBold(True)
        self.add_btn.setFont(f)
        self.add_btn.setMinimumHeight(70)
        self.add_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.add_btn.setToolTip("New scene")
        self.add_btn.clicked.connect(lambda _c=False: self.newSceneRequested.emit())

        # Quick view only
        self.quick_note = QLabel("Quick view isn't saved.\nSave it as a project to keep "
                                 "these clips, their sync and zoom.")
        self.quick_note.setWordWrap(True)
        self.quick_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.quick_note.setStyleSheet("color: #a0a0a8;")
        self.save_btn = QPushButton("Save as project…")
        self.save_btn.clicked.connect(lambda _c=False: self.saveQuickViewRequested.emit())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.quick_note)
        layout.addWidget(self.save_btn)
        layout.addStretch(0)
        layout.addWidget(self.add_btn)
        self.set_quick_view(False)

    def set_scenes(self, project_name: str, scenes: list, current: Optional[str],
                   icons: dict):
        # scenes: Scene objects; icons: scene id -> QIcon
        self.set_quick_view(False)
        self.subtitle.setText(project_name)
        self.list.clear()
        for sc in scenes:
            n = len(sc.clip_ids())
            item = QListWidgetItem(icons.get(sc.id) or QIcon(),
                                   f"{sc.name}\n{n} clip{'' if n == 1 else 's'}")
            item.setData(Qt.ItemDataRole.UserRole, sc.id)
            item.setToolTip(f"{sc.name}\nClick to open · right-click to rename or delete")
            self.list.addItem(item)
            if sc.id == current:
                item.setSelected(True)
                self.list.setCurrentItem(item)

    def set_quick_view(self, on: bool):
        self.title.setText("Quick view" if on else "Scenes")
        if on:
            self.subtitle.setText("")
            self.list.clear()
        self.list.setVisible(not on)
        self.add_btn.setVisible(not on)
        self.quick_note.setVisible(on)
        self.save_btn.setVisible(on)

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        menu = QMenu(self)
        if item is not None:
            sid = item.data(Qt.ItemDataRole.UserRole)
            menu.addAction("Open").triggered.connect(lambda _c=False: self.sceneChosen.emit(sid))
            menu.addAction("Rename…").triggered.connect(lambda _c=False: self.renameSceneRequested.emit(sid))
            menu.addAction("Delete scene…").triggered.connect(lambda _c=False: self.deleteSceneRequested.emit(sid))
            menu.addSeparator()
        menu.addAction("New scene").triggered.connect(lambda _c=False: self.newSceneRequested.emit())
        menu.exec(self.list.viewport().mapToGlobal(pos))
