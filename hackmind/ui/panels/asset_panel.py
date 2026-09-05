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
    QVBoxLayout,
    QWidget,
)


from hackmind.ui.themes import title_point_size
from hackmind.db import node_repo, template_repo
from hackmind.engine import tree_engine
from hackmind.models.types import Node, NodeStatus
from hackmind.ui.app_state import AppState
from hackmind.ui.version_utils import group_by_name, latest_per_name


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
        font.setPointSize(title_point_size())
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

        # Summary line — child asset / progress overview
        self._summary = QLabel()
        self._summary.setObjectName("mutedLabel")

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
        layout.addWidget(self._summary)
        layout.addWidget(add_group)
        layout.addStretch()
        layout.addLayout(delete_row)

    def load(self, node: Node) -> None:
        self._node = node
        self._title.setText(node.title)
        self._name_input.clear()
        self._refresh_template_combo()
        # "Target Scope" is the project root — don't allow deleting it
        self._delete_btn.setVisible(node.parent_id is not None)
        children = node_repo.get_children(self._state.db, node.id)
        n_children = len(children)
        remaining = sum(
            1 for c in children
            if c.type.value == "checklist"
            and c.status not in (NodeStatus.COMPLETE, NodeStatus.VULNERABLE, NodeStatus.NOT_APPLICABLE)
        )
        parts = [f"{n_children} sub-node{'s' if n_children != 1 else ''}"]
        if remaining:
            parts.append(f"{remaining} checks remaining")
        self._summary.setText(" · ".join(parts))
        # Notes and attachments are shown in the right pane (single shared editor).

    def _refresh_template_combo(self) -> None:
        previous_id = self._template_combo.currentData()
        self._template_combo.clear()
        self._template_combo.addItem("— no template —", None)

        all_templates = template_repo.list_templates(self._state.db)
        templates = [t for t in all_templates if t.get("tier", "asset") == "asset"]

        if self._all_versions_chk.isChecked():
            first_group = True
            for name, versions in group_by_name(templates).items():
                if not first_group:
                    self._template_combo.insertSeparator(self._template_combo.count())
                first_group = False
                for i, t in enumerate(versions):
                    label = f"{t['name']} v{t['version']}"
                    if i > 0:
                        label += "  (older)"
                    self._template_combo.addItem(label, t["id"])
        else:
            for t in latest_per_name(templates):
                self._template_combo.addItem(f"{t['name']} v{t['version']}", t["id"])

        if previous_id:
            idx = self._template_combo.findData(previous_id)
            if idx >= 0:
                self._template_combo.setCurrentIndex(idx)

    def flush(self) -> None:
        pass  # No editors here — notes live in the right pane.

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
