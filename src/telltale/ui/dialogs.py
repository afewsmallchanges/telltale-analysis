# dialogs.py
# Small reusable dialogs: a question with several answers, a name prompt,
# and the clip picker used by the "+" in an empty view.

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.clip import ClipInfo
from .library_screen import ClipGrid


def ask_choice(parent, title: str, text: str, choices: list[str]) -> Optional[int]:
    # Returns the index of the chosen answer, or None for Cancel.
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Question)
    for i, label in enumerate(choices):
        b = box.addButton(label, QMessageBox.ButtonRole.AcceptRole)
        b.setProperty("choice", i)
        if i == 0:
            box.setDefaultButton(b)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    clicked = box.clickedButton()
    choice = clicked.property("choice") if clicked is not None else None
    return int(choice) if choice is not None else None


def ask_name(parent, title: str, label: str, default: str) -> Optional[str]:
    name, ok = QInputDialog.getText(parent, title, label, QLineEdit.EchoMode.Normal, default)
    return name if ok else None


class ClipPickerDialog(QDialog):
    # Choose a clip for a view: from this project, or from the full library.

    def __init__(self, project_name: Optional[str], project_clips: Optional[list[ClipInfo]],
                 all_clips: list[ClipInfo], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add a clip")
        self.resize(860, 580)
        self.chosen: Optional[ClipInfo] = None
        self.grids: list[ClipGrid] = []

        self.tabs = QTabWidget()
        if project_clips is not None:
            self.tabs.addTab(self._page(project_clips,
                                        "This project has no clips yet.\n"
                                        "Pick one from the Full library tab."),
                             f"This project ({project_name})")
        self.tabs.addTab(self._page(all_clips, "The library is empty.\n"
                                    "Import clips first (File → Import clips)."),
                         "Full library")
        if project_clips is not None and not project_clips:
            self.tabs.setCurrentIndex(1)
        self.tabs.currentChanged.connect(lambda _i: self._update_button())

        search = QLineEdit()
        search.setPlaceholderText("Search clips")
        search.setClearButtonEnabled(True)
        search.textChanged.connect(lambda t: [g.filter(t) for g in self.grids])

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.add_btn = self.buttons.addButton("Add", QDialogButtonBox.ButtonRole.AcceptRole)
        self.add_btn.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        top = QHBoxLayout()
        top.addWidget(QLabel("Choose a clip to show in this view."), 1)
        top.addWidget(search)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.buttons)

    def _page(self, clips: list[ClipInfo], empty_text: str) -> QWidget:
        grid = ClipGrid()
        grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        grid.set_clips(clips)
        grid.itemActivated.connect(lambda _item: self.accept())
        grid.itemSelectionChanged.connect(self._update_button)
        self.grids.append(grid)
        empty = QLabel(empty_text)
        empty.setStyleSheet("color: gray; font-size: 12pt;")
        stack = QStackedWidget()
        stack.addWidget(grid)
        stack.addWidget(empty)
        stack.setCurrentWidget(grid if clips else empty)
        return stack

    def _current_grid(self) -> ClipGrid:
        return self.grids[self.tabs.currentIndex()]

    def _update_button(self):
        self.add_btn.setEnabled(bool(self._current_grid().selected_clips()))

    def accept(self):
        clips = self._current_grid().selected_clips()
        if clips:
            self.chosen = clips[0]
            super().accept()
