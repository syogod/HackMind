"""
New project creation dialog.

Collects: project name, target name, and an optional engagement template
(filtered to tier == "engagement").  Returns a Project on accept so the
caller can persist it and call instantiate_project.
"""

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from hackmind.db import template_repo
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

        self._engagement_combo = QComboBox()
        self._populate_engagement_combo()

        form = QFormLayout()
        form.addRow("Project Name:", self._name)
        form.addRow("Target:", self._target)
        form.addRow("Engagement Type:", self._engagement_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _populate_engagement_combo(self) -> None:
        self._engagement_combo.addItem("— no template —", "")
        templates = template_repo.list_templates(self._db)
        for t in templates:
            if t.get("tier") == "engagement":
                self._engagement_combo.addItem(f"{t['name']} v{t['version']}", t["id"])

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
            template_id=self._engagement_combo.currentData() or "",
        )
        self.accept()
