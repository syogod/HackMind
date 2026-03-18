"""
New project creation dialog.

Collects: project name and target name.
Returns a Project on accept so the caller can persist it and call
instantiate_project.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from hackmind.db.database import Database
from hackmind.models.types import Project


class NewProjectDialog(QDialog):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self.created_project: Project | None = None

        self.setWindowTitle("New Project")
        self.setMinimumWidth(400)

        self._name = QLineEdit()
        self._name.setPlaceholderText("e.g., ACME Corp Bug Bounty")

        self._target = QLineEdit()
        self._target.setPlaceholderText("e.g., acme.com")

        form = QFormLayout()
        form.addRow("Project Name:", self._name)
        form.addRow("Target:", self._target)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        name = self._name.text().strip()
        target = self._target.text().strip()

        if not name:
            QMessageBox.warning(self, "Validation", "Project name is required.")
            return
        if not target:
            QMessageBox.warning(self, "Validation", "Target name is required.")
            return

        self.created_project = Project(
            name=name,
            target_name=target,
            template_id="",   # no project-level template
        )
        self.accept()
