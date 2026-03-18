"""
Welcome / home panel.

Shown when no project is open. Displays existing projects and buttons
to open, create, or delete a project.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hackmind.db import project_repo
from hackmind.db.database import Database


class WelcomePanel(QWidget):
    project_opened = pyqtSignal(str)   # emits project_id
    new_project_requested = pyqtSignal()

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db

        heading = QLabel("HackMind")
        heading_font = heading.font()
        heading_font.setPointSize(24)
        heading_font.setBold(True)
        heading.setFont(heading_font)

        subtitle = QLabel("Pentesting Methodology Assistant")
        subtitle.setObjectName("mutedLabel")

        self._project_list = QListWidget()
        self._project_list.itemDoubleClicked.connect(self._open_selected)

        btn_open = QPushButton("Open")
        btn_open.clicked.connect(self._open_selected)

        btn_new = QPushButton("New Project…")
        btn_new.clicked.connect(self.new_project_requested)

        btn_delete = QPushButton("Delete")
        btn_delete.setObjectName("dangerButton")
        btn_delete.clicked.connect(self._delete_selected)

        btn_row = QHBoxLayout()
        btn_row.addWidget(btn_open)
        btn_row.addWidget(btn_new)
        btn_row.addStretch()
        btn_row.addWidget(btn_delete)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(8)
        layout.addWidget(heading)
        layout.addWidget(subtitle)
        layout.addSpacing(16)
        layout.addWidget(QLabel("Recent Projects:"))
        layout.addWidget(self._project_list)
        layout.addLayout(btn_row)

        self.refresh()

    def refresh(self) -> None:
        self._project_list.clear()
        projects = project_repo.list_projects(self._db)
        for p in projects:
            item = QListWidgetItem(f"{p.name}  —  {p.target_name}")
            item.setData(256, p.id)
            self._project_list.addItem(item)
        if projects:
            self._project_list.setCurrentRow(0)

    def _open_selected(self) -> None:
        item = self._project_list.currentItem()
        if item:
            self.project_opened.emit(item.data(256))

    def _delete_selected(self) -> None:
        item = self._project_list.currentItem()
        if item is None:
            return
        project_id = item.data(256)
        name = item.text()
        reply = QMessageBox.question(
            self,
            "Delete Project",
            f"Delete '{name}'?\n\nAll nodes, notes, and attachments will be "
            "permanently removed. This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            project_repo.delete_project(self._db, project_id)
            self.refresh()
