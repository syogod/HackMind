"""
Template creation and editing dialog.

A standalone editor for building and modifying methodology templates.
Opening or saving here never touches an open project.

Layout
------
  Top toolbar   — file operations (New / Open / Save / Export)
  Metadata bar  — name, version, author, description
  Node toolbar  — add node types, add option, delete, reorder
  QSplitter
    Left  : QTreeWidget — full structure: nodes + option rows + option children
    Right : QStackedWidget — empty hint | node editor | option editor
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from hackmind.db import template_repo
from hackmind.db.database import Database
from hackmind.engine.template_loader import TemplateValidationError, load_template_from_string
from hackmind.models.types import NodeType, Template, TemplateNode, TemplateOption

# ---------------------------------------------------------------------------
# Tree item roles / kind constants
# ---------------------------------------------------------------------------
_ROLE_KIND = Qt.ItemDataRole.UserRole       # "node" | "option"
_ROLE_DATA = Qt.ItemDataRole.UserRole + 1   # TemplateNode  |  (TemplateOption, TemplateNode)

_KIND_NODE = "node"
_KIND_OPT  = "option"

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
_TYPE_PREFIX: dict[NodeType, str] = {
    NodeType.INFO:      "• ",
    NodeType.CHECKLIST: "○ ",
    NodeType.QUESTION:  "? ",
}
_TYPE_LABELS: dict[NodeType, str] = {
    NodeType.INFO:      "Info Section",
    NodeType.CHECKLIST: "Checklist Item",
    NodeType.QUESTION:  "Question",
}


def _node_text(node: TemplateNode) -> str:
    return _TYPE_PREFIX.get(node.type, "  ") + node.title


def _option_text(opt: TemplateOption) -> str:
    return f"→ {opt.label}  [{opt.key}]"


# ---------------------------------------------------------------------------
# YAML serialiser — TemplateNode objects → YAML string
# ---------------------------------------------------------------------------

class _LiteralDumper(yaml.Dumper):
    pass


def _lit_str(dumper: yaml.Dumper, data: str) -> yaml.ScalarNode:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_LiteralDumper.add_representer(str, _lit_str)


def _tnode_to_dict(node: TemplateNode) -> dict:
    d: dict = {"id": node.id, "type": node.type.value, "title": node.title}
    if node.content:
        d["content"] = node.content
    if node.type == NodeType.QUESTION:
        d["options"] = [
            {
                "label": opt.label,
                "key": opt.key,
                "children": [_tnode_to_dict(c) for c in opt.children],
            }
            for opt in node.options
        ]
    else:
        if node.children:
            d["children"] = [_tnode_to_dict(c) for c in node.children]
    return d


def _to_yaml(name: str, version: str, author: str, description: str, nodes: list[TemplateNode]) -> str:
    doc: dict = {"name": name, "version": version, "author": author}
    if description:
        doc["description"] = description
    doc["nodes"] = [_tnode_to_dict(n) for n in nodes]
    return yaml.dump(doc, Dumper=_LiteralDumper, allow_unicode=True, sort_keys=False, default_flow_style=False)


# ===========================================================================
# Node editor widget (right panel — node selected)
# ===========================================================================

class _NodeEditorWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._node: TemplateNode | None = None

        self._type_label = QLabel()
        font = self._type_label.font()
        font.setBold(True)
        self._type_label.setFont(font)

        self._title_input = QLineEdit()

        self._content_input = QPlainTextEdit()
        self._content_input.setPlaceholderText("Optional — guidance, steps, or notes for testers")
        self._content_input.setMinimumHeight(180)

        self._apply_btn = QPushButton("Apply Changes")

        form = QFormLayout()
        form.addRow("Type:", self._type_label)
        form.addRow("Title:", self._title_input)
        form.addRow(QLabel("Content:"))
        form.addRow(self._content_input)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addLayout(form)
        layout.addWidget(self._apply_btn)
        layout.addStretch()

    def load(self, node: TemplateNode) -> None:
        self._node = node
        self._type_label.setText(_TYPE_LABELS.get(node.type, node.type.value))
        self._title_input.setText(node.title)
        self._content_input.setPlainText(node.content)

    def apply_to_node(self) -> bool:
        if self._node is None:
            return False
        title = self._title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "Validation", "Title is required.")
            return False
        self._node.title = title
        self._node.content = self._content_input.toPlainText().strip()
        return True

    @property
    def apply_btn(self) -> QPushButton:
        return self._apply_btn


# ===========================================================================
# Option editor widget (right panel — option item selected)
# ===========================================================================

class _OptionEditorWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._opt: TemplateOption | None = None
        self._parent_node: TemplateNode | None = None

        self._label_input = QLineEdit()
        self._key_input = QLineEdit()
        self._key_input.setPlaceholderText('Short identifier, e.g. "yes" or "no"')

        self._apply_btn = QPushButton("Apply Changes")

        hint = QLabel(
            "The key is a stable identifier used internally. "
            "It must be unique within this question and should not contain spaces."
        )
        hint.setWordWrap(True)
        hint.setObjectName("hintLabel")

        form = QFormLayout()
        form.addRow("Label:", self._label_input)
        form.addRow("Key:", self._key_input)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(self._apply_btn)
        layout.addStretch()

    def load(self, opt: TemplateOption, parent_node: TemplateNode) -> None:
        self._opt = opt
        self._parent_node = parent_node
        self._label_input.setText(opt.label)
        self._key_input.setText(opt.key)

    def apply_to_option(self) -> bool:
        if self._opt is None or self._parent_node is None:
            return False
        label = self._label_input.text().strip()
        key = self._key_input.text().strip()
        if not label:
            QMessageBox.warning(self, "Validation", "Label is required.")
            return False
        if not key:
            QMessageBox.warning(self, "Validation", "Key is required.")
            return False
        other_keys = {o.key for o in self._parent_node.options if o is not self._opt}
        if key in other_keys:
            QMessageBox.warning(self, "Validation", f"Key '{key}' is already used by another option in this question.")
            return False
        self._opt.label = label
        self._opt.key = key
        return True

    @property
    def apply_btn(self) -> QPushButton:
        return self._apply_btn


# ===========================================================================
# Main dialog
# ===========================================================================

class TemplateEditorDialog(QDialog):
    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._modified = False
        self._root_nodes: list[TemplateNode] = []

        self.setWindowTitle("Template Editor")
        self.resize(1150, 740)
        self.setMinimumSize(800, 500)

        self._build_ui()
        self._new_template()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(4)
        outer.addLayout(self._build_file_toolbar())
        outer.addLayout(self._build_metadata_bar())
        outer.addLayout(self._build_node_toolbar())
        outer.addWidget(self._build_splitter(), stretch=1)

    def _build_file_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._btn_new       = QPushButton("New")
        self._btn_open_lib  = QPushButton("Open from Library…")
        self._btn_open_file = QPushButton("Open from File…")
        self._btn_save_lib  = QPushButton("Save to Library")
        self._btn_export    = QPushButton("Export to File…")

        row.addWidget(self._btn_new)
        row.addWidget(self._btn_open_lib)
        row.addWidget(self._btn_open_file)
        row.addWidget(QLabel("|"))
        row.addWidget(self._btn_save_lib)
        row.addWidget(self._btn_export)
        row.addStretch()

        self._btn_new.clicked.connect(self._new_template)
        self._btn_open_lib.clicked.connect(self._open_from_library)
        self._btn_open_file.clicked.connect(self._open_from_file)
        self._btn_save_lib.clicked.connect(self._save_to_library)
        self._btn_export.clicked.connect(self._export_to_file)
        return row

    def _build_metadata_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._meta_name    = QLineEdit()
        self._meta_version = QLineEdit()
        self._meta_version.setFixedWidth(70)
        self._meta_author  = QLineEdit()
        self._meta_desc    = QLineEdit()

        self._meta_name.setPlaceholderText("Template name")
        self._meta_version.setPlaceholderText("1.0.0")
        self._meta_author.setPlaceholderText("Author")
        self._meta_desc.setPlaceholderText("Short description (optional)")

        row.addWidget(QLabel("Name:"))
        row.addWidget(self._meta_name, stretch=2)
        row.addWidget(QLabel("Version:"))
        row.addWidget(self._meta_version)
        row.addWidget(QLabel("Author:"))
        row.addWidget(self._meta_author, stretch=1)
        row.addWidget(QLabel("Desc:"))
        row.addWidget(self._meta_desc, stretch=2)

        for field in (self._meta_name, self._meta_version, self._meta_author, self._meta_desc):
            field.textChanged.connect(self._mark_modified)
        return row

    def _build_node_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._btn_add_info      = QPushButton("+ Info Section")
        self._btn_add_checklist = QPushButton("+ Checklist Item")
        self._btn_add_question  = QPushButton("+ Question")
        self._btn_add_option    = QPushButton("+ Option")
        self._btn_delete        = QPushButton("Delete")
        self._btn_up            = QPushButton("↑")
        self._btn_down          = QPushButton("↓")

        self._btn_delete.setObjectName("dangerButton")
        self._btn_up.setFixedWidth(30)
        self._btn_down.setFixedWidth(30)

        for btn in (self._btn_add_info, self._btn_add_checklist, self._btn_add_question,
                    self._btn_add_option, self._btn_delete, self._btn_up, self._btn_down):
            row.addWidget(btn)
        row.addStretch()

        self._btn_add_info.clicked.connect(lambda: self._add_node(NodeType.INFO))
        self._btn_add_checklist.clicked.connect(lambda: self._add_node(NodeType.CHECKLIST))
        self._btn_add_question.clicked.connect(lambda: self._add_node(NodeType.QUESTION))
        self._btn_add_option.clicked.connect(self._add_option)
        self._btn_delete.clicked.connect(self._delete_selected)
        self._btn_up.clicked.connect(self._move_up)
        self._btn_down.clicked.connect(self._move_down)
        return row

    def _build_splitter(self) -> QSplitter:
        # -- Left: tree --
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setAnimated(True)
        self._tree.currentItemChanged.connect(self._on_selection_changed)

        # -- Right: stacked editor --
        self._stack = QStackedWidget()

        hint_lbl = QLabel("Select a node in the tree to edit it,\nor use the toolbar to add new nodes.")
        hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_lbl.setObjectName("hintLabel")
        self._stack.addWidget(hint_lbl)          # page 0 — nothing selected

        self._node_editor = _NodeEditorWidget()
        self._node_editor.apply_btn.clicked.connect(self._apply_node_changes)
        self._stack.addWidget(self._node_editor)  # page 1 — node selected

        self._option_editor = _OptionEditorWidget()
        self._option_editor.apply_btn.clicked.connect(self._apply_option_changes)
        self._stack.addWidget(self._option_editor)  # page 2 — option selected

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._tree)
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        return splitter

    # ------------------------------------------------------------------
    # Template file operations
    # ------------------------------------------------------------------

    def _new_template(self) -> None:
        if not self._confirm_discard():
            return
        self._root_nodes = []
        self._tree.clear()
        self._meta_name.setText("New Template")
        self._meta_version.setText("1.0.0")
        self._meta_author.setText("")
        self._meta_desc.setText("")
        self._stack.setCurrentIndex(0)
        self._modified = False
        self._refresh_toolbar_states()

    def _open_from_library(self) -> None:
        if not self._confirm_discard():
            return
        templates = template_repo.list_templates(self._db)
        if not templates:
            QMessageBox.information(self, "No Templates", "No templates in the library yet.\nImport one from a file first.")
            return
        names = [f"{t['name']} v{t['version']}" for t in templates]
        choice, ok = QInputDialog.getItem(self, "Open Template", "Select a template:", names, 0, False)
        if not ok:
            return
        selected = templates[names.index(choice)]
        raw = template_repo.get_template_raw(self._db, selected["id"])
        if raw is None:
            QMessageBox.critical(self, "Error", "Could not load template data.")
            return
        try:
            template = load_template_from_string(raw)
        except TemplateValidationError as exc:
            QMessageBox.critical(self, "Load Error", str(exc))
            return
        self._load_template(template)

    def _open_from_file(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Template File", "", "YAML files (*.yaml *.yml);;All files (*)"
        )
        if not path:
            return
        try:
            raw = Path(path).read_text(encoding="utf-8")
            template = load_template_from_string(raw)
        except (OSError, TemplateValidationError) as exc:
            QMessageBox.critical(self, "Load Error", str(exc))
            return
        self._load_template(template)

    def _save_to_library(self) -> None:
        raw, template = self._validate_and_build()
        if raw is None or template is None:
            return
        template_repo.store_template(self._db, template, raw)
        self._modified = False
        QMessageBox.information(
            self, "Saved",
            f"'{template.name}' v{template.version} saved to the template library."
        )

    def _export_to_file(self) -> None:
        raw, template = self._validate_and_build()
        if raw is None or template is None:
            return
        default_name = re.sub(r"[^\w\-. ]", "_", template.name) + ".yaml"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Template File", default_name, "YAML files (*.yaml *.yml)"
        )
        if not path:
            return
        Path(path).write_text(raw, encoding="utf-8")
        self._modified = False
        QMessageBox.information(self, "Exported", f"Template saved to:\n{path}")

    # ------------------------------------------------------------------
    # Load a parsed Template into the editor
    # ------------------------------------------------------------------

    def _load_template(self, template: Template) -> None:
        self._tree.clear()
        self._root_nodes = list(template.nodes)
        self._meta_name.setText(template.name)
        self._meta_version.setText(template.version)
        self._meta_author.setText(template.author if template.author != "unknown" else "")
        self._meta_desc.setText(template.description)
        for node in self._root_nodes:
            self._make_node_item(node, self._tree.invisibleRootItem())
        self._tree.expandAll()
        self._stack.setCurrentIndex(0)
        self._modified = False
        self._refresh_toolbar_states()

    # ------------------------------------------------------------------
    # Tree item construction
    # ------------------------------------------------------------------

    def _make_node_item(self, node: TemplateNode, parent: QTreeWidgetItem) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent)
        item.setText(0, _node_text(node))
        item.setData(0, _ROLE_KIND, _KIND_NODE)
        item.setData(0, _ROLE_DATA, node)
        if node.type == NodeType.QUESTION:
            for opt in node.options:
                self._make_option_item(opt, node, item)
        else:
            for child in node.children:
                self._make_node_item(child, item)
        return item

    def _make_option_item(
        self, opt: TemplateOption, parent_node: TemplateNode, parent_item: QTreeWidgetItem
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent_item)
        item.setText(0, _option_text(opt))
        item.setData(0, _ROLE_KIND, _KIND_OPT)
        item.setData(0, _ROLE_DATA, (opt, parent_node))
        for child in opt.children:
            self._make_node_item(child, item)
        return item

    # ------------------------------------------------------------------
    # Selection handling
    # ------------------------------------------------------------------

    def _on_selection_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            self._stack.setCurrentIndex(0)
        elif current.data(0, _ROLE_KIND) == _KIND_NODE:
            self._node_editor.load(current.data(0, _ROLE_DATA))
            self._stack.setCurrentIndex(1)
        elif current.data(0, _ROLE_KIND) == _KIND_OPT:
            opt, parent_node = current.data(0, _ROLE_DATA)
            self._option_editor.load(opt, parent_node)
            self._stack.setCurrentIndex(2)
        self._refresh_toolbar_states()

    def _refresh_toolbar_states(self) -> None:
        item = self._tree.currentItem()
        kind = item.data(0, _ROLE_KIND) if item else None
        in_question_ctx = (
            item is not None and (
                (kind == _KIND_NODE and item.data(0, _ROLE_DATA).type == NodeType.QUESTION)
                or kind == _KIND_OPT
            )
        )
        self._btn_add_option.setEnabled(in_question_ctx)
        has_selection = item is not None
        self._btn_delete.setEnabled(has_selection)
        self._btn_up.setEnabled(has_selection)
        self._btn_down.setEnabled(has_selection)

    # ------------------------------------------------------------------
    # Apply edits
    # ------------------------------------------------------------------

    def _apply_node_changes(self) -> None:
        item = self._tree.currentItem()
        if item is None or item.data(0, _ROLE_KIND) != _KIND_NODE:
            return
        if self._node_editor.apply_to_node():
            item.setText(0, _node_text(item.data(0, _ROLE_DATA)))
            self._mark_modified()

    def _apply_option_changes(self) -> None:
        item = self._tree.currentItem()
        if item is None or item.data(0, _ROLE_KIND) != _KIND_OPT:
            return
        if self._option_editor.apply_to_option():
            opt, _ = item.data(0, _ROLE_DATA)
            item.setText(0, _option_text(opt))
            self._mark_modified()

    # ------------------------------------------------------------------
    # Add node
    # ------------------------------------------------------------------

    def _add_node(self, node_type: NodeType) -> None:
        default_opts = (
            [TemplateOption(label="Yes", key="yes"), TemplateOption(label="No", key="no")]
            if node_type == NodeType.QUESTION
            else []
        )
        new_node = TemplateNode(
            id=self._new_node_id(node_type),
            type=node_type,
            title=f"New {_TYPE_LABELS[node_type]}",
            content="",
            options=default_opts,
        )

        current = self._tree.currentItem()

        if current is None:
            # Nothing selected — append at root.
            self._root_nodes.append(new_node)
            new_item = self._make_node_item(new_node, self._tree.invisibleRootItem())

        elif current.data(0, _ROLE_KIND) == _KIND_NODE:
            parent_node: TemplateNode = current.data(0, _ROLE_DATA)
            if parent_node.type == NodeType.QUESTION:
                QMessageBox.information(
                    self, "Cannot Add Here",
                    "A question node's children live inside its options.\n"
                    "Select one of its option rows (→ …) to add children there."
                )
                return
            parent_node.children.append(new_node)
            new_item = self._make_node_item(new_node, current)
            self._tree.expandItem(current)

        elif current.data(0, _ROLE_KIND) == _KIND_OPT:
            opt, _ = current.data(0, _ROLE_DATA)
            opt.children.append(new_node)
            new_item = self._make_node_item(new_node, current)
            self._tree.expandItem(current)

        else:
            return

        self._tree.setCurrentItem(new_item)
        self._mark_modified()

    # ------------------------------------------------------------------
    # Add option
    # ------------------------------------------------------------------

    def _add_option(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return

        # Resolve the question node and its tree item.
        if item.data(0, _ROLE_KIND) == _KIND_NODE:
            q_node: TemplateNode = item.data(0, _ROLE_DATA)
            q_item = item
        elif item.data(0, _ROLE_KIND) == _KIND_OPT:
            q_item = item.parent()
            if q_item is None:
                return
            q_node = q_item.data(0, _ROLE_DATA)
        else:
            return

        if q_node.type != NodeType.QUESTION:
            return

        existing_keys = {o.key for o in q_node.options}
        n = len(q_node.options) + 1
        key = f"option_{n}"
        while key in existing_keys:
            n += 1
            key = f"option_{n}"

        new_opt = TemplateOption(label=f"Option {n}", key=key)
        q_node.options.append(new_opt)

        new_item = self._make_option_item(new_opt, q_node, q_item)
        self._tree.setCurrentItem(new_item)
        self._tree.expandItem(q_item)
        self._mark_modified()

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def _delete_selected(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return

        reply = QMessageBox.question(
            self, "Delete",
            "Delete this item and all its children?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        kind = item.data(0, _ROLE_KIND)
        if kind == _KIND_NODE:
            node: TemplateNode = item.data(0, _ROLE_DATA)
            self._node_parent_list(item).remove(node)
        elif kind == _KIND_OPT:
            opt, parent_node = item.data(0, _ROLE_DATA)
            parent_node.options.remove(opt)

        parent_item = item.parent()
        if parent_item is None:
            self._tree.takeTopLevelItem(self._tree.indexOfTopLevelItem(item))
        else:
            parent_item.removeChild(item)

        self._stack.setCurrentIndex(0)
        self._mark_modified()

    # ------------------------------------------------------------------
    # Reorder (move up / down)
    # ------------------------------------------------------------------

    def _move_up(self) -> None:
        self._shift(-1)

    def _move_down(self) -> None:
        self._shift(1)

    def _shift(self, direction: int) -> None:
        item = self._tree.currentItem()
        if item is None:
            return

        kind = item.data(0, _ROLE_KIND)
        parent_item = item.parent()

        if kind == _KIND_NODE:
            data_list = self._node_parent_list(item)
            obj = item.data(0, _ROLE_DATA)
        elif kind == _KIND_OPT:
            if parent_item is None:
                return
            q_node: TemplateNode = parent_item.data(0, _ROLE_DATA)
            data_list = q_node.options
            obj, _ = item.data(0, _ROLE_DATA)
        else:
            return

        idx = data_list.index(obj)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(data_list):
            return

        # Swap in data model.
        data_list[idx], data_list[new_idx] = data_list[new_idx], data_list[idx]

        # Swap in tree.
        if parent_item is None:
            self._tree.takeTopLevelItem(idx)
            self._tree.insertTopLevelItem(new_idx, item)
        else:
            parent_item.removeChild(item)
            parent_item.insertChild(new_idx, item)

        self._tree.setCurrentItem(item)
        self._mark_modified()

    # ------------------------------------------------------------------
    # Validation and YAML generation
    # ------------------------------------------------------------------

    def _validate_and_build(self) -> tuple[str | None, Template | None]:
        name    = self._meta_name.text().strip()
        version = self._meta_version.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Template name is required.")
            return None, None
        if not version:
            QMessageBox.warning(self, "Validation", "Version is required.")
            return None, None
        if not self._root_nodes:
            QMessageBox.warning(self, "Validation", "Add at least one node before saving.")
            return None, None

        raw = _to_yaml(
            name=name,
            version=version,
            author=self._meta_author.text().strip() or "unknown",
            description=self._meta_desc.text().strip(),
            nodes=self._root_nodes,
        )
        try:
            template = load_template_from_string(raw)
        except TemplateValidationError as exc:
            QMessageBox.critical(self, "Validation Error", str(exc))
            return None, None
        return raw, template

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _node_parent_list(self, item: QTreeWidgetItem) -> list:
        """Return the list (root_nodes / parent.children / opt.children) containing this node."""
        parent = item.parent()
        if parent is None:
            return self._root_nodes
        pk = parent.data(0, _ROLE_KIND)
        if pk == _KIND_NODE:
            return parent.data(0, _ROLE_DATA).children
        if pk == _KIND_OPT:
            opt, _ = parent.data(0, _ROLE_DATA)
            return opt.children
        return []

    def _all_ids(self) -> set[str]:
        """Collect every node ID in the current in-memory template tree."""
        ids: set[str] = set()
        def _walk(nodes: list[TemplateNode]) -> None:
            for n in nodes:
                ids.add(n.id)
                for opt in n.options:
                    _walk(opt.children)
                _walk(n.children)
        _walk(self._root_nodes)
        return ids

    def _new_node_id(self, node_type: NodeType) -> str:
        """
        Generate a unique node ID using a type-based prefix and an incrementing
        counter, e.g. 'check_1', 'q_2'. Avoids collisions with existing IDs.
        """
        prefix = {NodeType.INFO: "info", NodeType.CHECKLIST: "check", NodeType.QUESTION: "q"}[node_type]
        existing = self._all_ids()
        i = 1
        while f"{prefix}_{i}" in existing:
            i += 1
        return f"{prefix}_{i}"

    def _mark_modified(self) -> None:
        self._modified = True

    def _confirm_discard(self) -> bool:
        if not self._modified:
            return True
        reply = QMessageBox.question(
            self, "Unsaved Changes",
            "You have unsaved changes. Discard them and continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
