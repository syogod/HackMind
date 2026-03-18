"""
Scope settings dialog.

Shows every scope tag that appears on any node in the current project and
lets the user mark categories as out of scope.  Nodes whose scope_tags
list intersects the active OOS tags are hidden from the tree view.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from hackmind.db import scope_repo
from hackmind.db.database import Database


_TAG_LABELS: dict[str, str] = {
    "brute_force":       "Brute Force / Credential Stuffing",
    "clickjacking":      "Clickjacking",
    "csrf":              "CSRF (Non-Sensitive Endpoints)",
    "dos":               "Denial of Service (DoS)",
    "missing_headers":   "Missing Security Headers",
    "open_redirect":     "Open Redirect",
    "rate_limiting":     "Rate Limiting",
    "self_xss":          "Self-XSS",
    "social_engineering":"Social Engineering",
    "version_disclosure":"Version / Banner Disclosure",
    "physical":          "Physical Security",
}


def _format_tag(tag: str) -> str:
    """Return a human-readable label for a scope tag."""
    return _TAG_LABELS.get(tag, tag.replace("_", " ").title())


class ScopeDialog(QDialog):
    def __init__(self, db: Database, project_id: str, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._project_id = project_id
        self.setWindowTitle("Scope Settings")
        self.setMinimumWidth(360)

        self._checkboxes: dict[str, QCheckBox] = {}

        all_tags = scope_repo.get_all_project_tags(db, project_id)
        oos_tags = scope_repo.get_oos_tags(db, project_id)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        if not all_tags:
            layout.addWidget(
                QLabel(
                    "No scope tags are defined in this project's template.\n\n"
                    "Add scope_tags: [tag1, tag2] to nodes in a template YAML\n"
                    "to enable this feature."
                )
            )
        else:
            hint = QLabel(
                "Check categories to mark them as out of scope.\n"
                "Nodes tagged with a checked category will be hidden in the tree."
            )
            hint.setWordWrap(True)
            layout.addWidget(hint)

            scroll_widget = QWidget()
            scroll_layout = QVBoxLayout(scroll_widget)
            scroll_layout.setContentsMargins(4, 4, 4, 4)
            scroll_layout.setSpacing(4)

            for tag in sorted(all_tags):
                cb = QCheckBox(_format_tag(tag))
                cb.setProperty("scopeTag", tag)
                cb.setChecked(tag in oos_tags)
                self._checkboxes[tag] = cb
                scroll_layout.addWidget(cb)

            scroll_layout.addStretch()

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(scroll_widget)
            scroll.setMaximumHeight(320)
            layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        new_oos = {tag for tag, cb in self._checkboxes.items() if cb.isChecked()}
        scope_repo.set_oos_tags(self._db, self._project_id, new_oos)
        self.accept()
