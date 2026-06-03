"""
New project creation dialog.

Collects: project name, target name, and an optional engagement template
(filtered to tier == "engagement").  Returns a Project on accept so the
caller can persist it and call instantiate_project.
"""

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from hackmind.db import template_repo
from hackmind.db.database import Database
from hackmind.models.types import Project
from hackmind.ui.version_utils import group_by_name, latest_per_name


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
        self._all_versions_chk = QCheckBox("All versions")
        self._all_versions_chk.toggled.connect(lambda: self._refresh_engagement_combo())
        self._refresh_engagement_combo()

        engagement_row = QHBoxLayout()
        engagement_row.setContentsMargins(0, 0, 0, 0)
        engagement_row.addWidget(self._engagement_combo, stretch=1)
        engagement_row.addWidget(self._all_versions_chk)

        form = QFormLayout()
        form.addRow("Project Name:", self._name)
        form.addRow("Target:", self._target)
        form.addRow("Engagement Type:", engagement_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _refresh_engagement_combo(self) -> None:
        previous_id = self._engagement_combo.currentData()
        self._engagement_combo.clear()
        self._engagement_combo.addItem("— no template —", "")

        all_templates = template_repo.list_templates(self._db)
        templates = [t for t in all_templates if t.get("tier") == "engagement"]

        if self._all_versions_chk.isChecked():
            first_group = True
            for name, versions in group_by_name(templates).items():
                if not first_group:
                    self._engagement_combo.insertSeparator(self._engagement_combo.count())
                first_group = False
                for i, t in enumerate(versions):
                    label = f"{t['name']} v{t['version']}"
                    if i > 0:
                        label += "  (older)"
                    self._engagement_combo.addItem(label, t["id"])
        else:
            for t in latest_per_name(templates):
                self._engagement_combo.addItem(f"{t['name']} v{t['version']}", t["id"])

        if previous_id:
            idx = self._engagement_combo.findData(previous_id)
            if idx >= 0:
                self._engagement_combo.setCurrentIndex(idx)

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
