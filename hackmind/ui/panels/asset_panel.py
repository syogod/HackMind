"""
Asset node panel.

Displays asset metadata and provides a form to add a child asset
(e.g., a discovered subdomain under the root target).
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)


from hackmind.db import node_repo, template_repo


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def _parse_version(v: str) -> tuple:
    """
    Parse a version string into a tuple of ints for ordering comparisons.
    Non-numeric segments are treated as 0. e.g. "1.2.3" → (1, 2, 3).
    """
    parts = []
    for p in v.strip().split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _latest_per_name(templates: list[dict]) -> list[dict]:
    """Return one entry per template name — the one with the highest version."""
    best: dict[str, dict] = {}
    for t in templates:
        name = t["name"]
        if name not in best or _parse_version(t["version"]) > _parse_version(best[name]["version"]):
            best[name] = t
    return sorted(best.values(), key=lambda t: t["name"].lower())


def _group_by_name(templates: list[dict]) -> dict[str, list[dict]]:
    """Group templates by name; within each group sort by version descending."""
    groups: dict[str, list[dict]] = {}
    for t in templates:
        groups.setdefault(t["name"], []).append(t)
    return {
        name: sorted(versions, key=lambda t: _parse_version(t["version"]), reverse=True)
        for name, versions in sorted(groups.items(), key=lambda kv: kv[0].lower())
    }
from hackmind.engine import tree_engine
from hackmind.models.types import Node
from hackmind.ui.app_state import AppState
from hackmind.ui.widgets.note_editor import NoteEditor


class AssetPanel(QWidget):
    tree_changed       = pyqtSignal()
    node_deleted       = pyqtSignal()
    node_focus_requested = pyqtSignal(str)   # emits node_id to select

    def __init__(self, state: AppState, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._node: Node | None = None

        self._title = QLabel()
        self._title.setWordWrap(True)
        font = self._title.font()
        font.setPointSize(14)
        font.setBold(True)
        self._title.setFont(font)

        # Add sub-asset group
        add_group = QGroupBox("Add Sub-Asset")
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("e.g., api.example.com")
        self._name_input.returnPressed.connect(self._add_asset)

        self._template_combo = QComboBox()
        self._all_versions_chk = QCheckBox("All versions")
        self._all_versions_chk.toggled.connect(lambda: self._refresh_template_combo())

        template_row = QHBoxLayout()
        template_row.setContentsMargins(0, 0, 0, 0)
        template_row.addWidget(self._template_combo, stretch=1)
        template_row.addWidget(self._all_versions_chk)

        add_btn = QPushButton("Add Asset")
        add_btn.clicked.connect(self._add_asset)

        form = QFormLayout()
        form.addRow("Name:", self._name_input)
        form.addRow("Template:", template_row)
        form.addRow("", add_btn)

        add_layout = QVBoxLayout(add_group)
        add_layout.addLayout(form)

        # Notes
        notes_group = QGroupBox("Notes")
        self._note_editor = NoteEditor(state.db)
        notes_layout = QVBoxLayout(notes_group)
        notes_layout.addWidget(self._note_editor)

        # Delete button
        self._delete_btn = QPushButton("Delete Asset")
        self._delete_btn.setObjectName("dangerButton")
        self._delete_btn.clicked.connect(self._delete_asset)

        delete_row = QHBoxLayout()
        delete_row.addStretch()
        delete_row.addWidget(self._delete_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addWidget(add_group)
        layout.addWidget(notes_group, stretch=1)
        layout.addLayout(delete_row)

    def load(self, node: Node) -> None:
        self._node = node
        self._title.setText(node.title)
        self._name_input.clear()
        self._note_editor.load(node.id)
        self._refresh_template_combo()
        # "Target Scope" is the project root — don't allow deleting it
        self._delete_btn.setVisible(node.parent_id is not None)

    def _refresh_template_combo(self) -> None:
        previous_id = self._template_combo.currentData()
        self._template_combo.clear()
        self._template_combo.addItem("— no template —", None)

        all_templates = template_repo.list_templates(self._state.db)
        templates = [t for t in all_templates if t.get("tier", "asset") == "asset"]

        if self._all_versions_chk.isChecked():
            first_group = True
            for name, versions in _group_by_name(templates).items():
                if not first_group:
                    self._template_combo.insertSeparator(self._template_combo.count())
                first_group = False
                for i, t in enumerate(versions):
                    label = f"{t['name']} v{t['version']}"
                    if i > 0:
                        label += "  (older)"
                    self._template_combo.addItem(label, t["id"])
        else:
            for t in _latest_per_name(templates):
                self._template_combo.addItem(f"{t['name']} v{t['version']}", t["id"])

        if previous_id:
            idx = self._template_combo.findData(previous_id)
            if idx >= 0:
                self._template_combo.setCurrentIndex(idx)

    def flush(self) -> None:
        self._note_editor.flush()

    def _add_asset(self) -> None:
        if self._node is None:
            return
        name = self._name_input.text().strip()
        if not name:
            return
        template_id: str | None = self._template_combo.currentData()
        tree_engine.add_asset(
            self._state.db,
            self._node.project_id,
            self._node.id,
            name,
            template_id=template_id,
        )
        self._name_input.clear()
        self.tree_changed.emit()

    def _delete_asset(self) -> None:
        if self._node is None:
            return
        reply = QMessageBox.question(
            self,
            "Delete Asset",
            f"Delete '{self._node.title}' and all its children?\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        node_repo.delete_node_subtree(self._state.db, self._node.id)
        self._node = None
        self.node_deleted.emit()
