"""
Checklist node panel.

Controls: status selector, "Is Finding" toggle, notes editor,
and the attachment pane.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from hackmind.db import node_repo
from hackmind.db.database import Database
from hackmind.models.types import Node, NodeStatus
from hackmind.ui.widgets.attachment_pane import AttachmentPane
from hackmind.ui.widgets.note_editor import NoteEditor

_STATUS_OPTIONS = [
    (NodeStatus.NOT_STARTED,    "Not Started"),
    (NodeStatus.IN_PROGRESS,    "In Progress"),
    (NodeStatus.COMPLETE,       "Complete"),
    (NodeStatus.VULNERABLE,     "Vulnerable"),
    (NodeStatus.NOT_APPLICABLE, "N/A"),
]


class ChecklistPanel(QWidget):
    tree_changed = pyqtSignal()

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._node: Node | None = None
        self._loading = False

        self._title = QLabel()
        self._title.setWordWrap(True)
        font = self._title.font()
        font.setPointSize(14)
        font.setBold(True)
        self._title.setFont(font)

        self._guidance = QTextBrowser()
        self._guidance.setMaximumHeight(120)
        self._guidance.setOpenExternalLinks(True)

        # Status row
        self._status_combo = QComboBox()
        for status, label in _STATUS_OPTIONS:
            self._status_combo.addItem(label, userData=status)
        self._status_combo.currentIndexChanged.connect(self._on_status_changed)

        # Finding toggle
        self._finding_check = QCheckBox("Mark as Finding")
        self._finding_check.setObjectName("findingCheck")
        self._finding_check.stateChanged.connect(self._on_finding_changed)

        form = QFormLayout()
        form.addRow("Status:", self._status_combo)
        form.addRow("", self._finding_check)

        # Notes
        notes_group = QGroupBox("Notes")
        self._note_editor = NoteEditor(db)
        notes_layout = QVBoxLayout(notes_group)
        notes_layout.addWidget(self._note_editor)

        # Attachments
        attachments_group = QGroupBox("Attachments")
        self._attachment_pane = AttachmentPane(db)
        attachments_layout = QVBoxLayout(attachments_group)
        attachments_layout.addWidget(self._attachment_pane)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addWidget(self._guidance)
        layout.addLayout(form)
        layout.addWidget(notes_group, stretch=2)
        layout.addWidget(attachments_group, stretch=1)

    def load(self, node: Node) -> None:
        self._loading = True
        self._node = node
        self._title.setText(node.title)
        self._guidance.setPlainText(node.content or "")
        self._guidance.setVisible(bool(node.content))

        # Set status combo without triggering the change handler
        for i, (status, _) in enumerate(_STATUS_OPTIONS):
            if status == node.status:
                self._status_combo.setCurrentIndex(i)
                break

        self._finding_check.setChecked(node.is_finding)
        self._note_editor.load(node.id)
        self._attachment_pane.load(node.id)
        self._loading = False

    def flush(self) -> None:
        """Save any pending note edits immediately."""
        self._note_editor.flush()

    def _on_status_changed(self, _index: int) -> None:
        if self._loading or self._node is None:
            return
        status = self._status_combo.currentData()
        node_repo.set_status(self._db, self._node.id, status)
        self._node.status = status
        self.tree_changed.emit()

    def _on_finding_changed(self, _state: int) -> None:
        if self._loading or self._node is None:
            return
        is_finding = self._finding_check.isChecked()
        node_repo.set_finding(self._db, self._node.id, is_finding)
        self._node.is_finding = is_finding
        self.tree_changed.emit()
