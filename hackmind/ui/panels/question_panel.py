"""
Question node panel.

Displays the question text and one button per answer option.
When an option is selected the tree engine is called, then
tree_changed is emitted so the main window refreshes the tree.

Bootstrap questions (template_node_id == ASSET_TYPE_NODE_ID) are handled
specially: the options are the DB-stored templates rather than YAML options.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from hackmind.db import node_repo, template_repo
from hackmind.engine import tree_engine
from hackmind.engine.tree_engine import ASSET_TYPE_NODE_ID
from hackmind.ui.app_state import AppState
from hackmind.models.types import Node


class QuestionPanel(QWidget):
    tree_changed = pyqtSignal()

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

        self._answered_label = QLabel()
        self._answered_label.setStyleSheet("color: #5cb85c; font-style: italic;")
        self._answered_label.hide()

        self._options_widget = QWidget()
        self._options_layout = QVBoxLayout(self._options_widget)
        self._options_layout.setSpacing(8)

        self._clear_btn = QPushButton("Clear Answer")
        self._clear_btn.setObjectName("dangerButton")
        self._clear_btn.clicked.connect(self._clear)
        self._clear_btn.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addWidget(self._answered_label)
        layout.addWidget(self._options_widget)
        layout.addWidget(self._clear_btn)
        layout.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

    def load(self, node: Node) -> None:
        self._node = node
        self._title.setText(node.title)
        self._rebuild_options()

    def _is_bootstrap(self) -> bool:
        return (
            self._node is not None
            and self._node.template_node_id == ASSET_TYPE_NODE_ID
        )

    def _rebuild_options(self) -> None:
        if self._node is None:
            return

        # Clear previous buttons
        while self._options_layout.count():
            child = self._options_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        answer = node_repo.get_answer(self._state.db, self._node.id)
        current_key = answer.option_key if answer else None

        if self._is_bootstrap():
            self._rebuild_bootstrap_options(current_key)
        else:
            self._rebuild_template_options(current_key)

        if current_key:
            self._clear_btn.show()
        else:
            self._clear_btn.hide()

    def _rebuild_bootstrap_options(self, current_key: str | None) -> None:
        """Show available DB templates as answer choices."""
        templates = template_repo.list_templates(self._state.db)

        if not templates:
            self._options_layout.addWidget(
                QLabel("No templates available. Import a template first.")
            )
            self._answered_label.hide()
            return

        if current_key:
            chosen = next((t for t in templates if t["id"] == current_key), None)
            label = f"{chosen['name']} v{chosen['version']}" if chosen else current_key
            self._answered_label.setText(f"Current template: {label}")
            self._answered_label.show()
        else:
            self._answered_label.hide()

        for t in templates:
            label = f"{t['name']} v{t['version']}"
            btn = QPushButton(label)
            btn.setObjectName("answerBtn")
            btn.setProperty("active", t["id"] == current_key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.clicked.connect(
                lambda checked, tid=t["id"]: self._select_asset_type(tid)
            )
            self._options_layout.addWidget(btn)

    def _rebuild_template_options(self, current_key: str | None) -> None:
        """Show options from the node's YAML template."""
        if self._node is None or self._node.template_id is None:
            return

        raw = template_repo.get_template_raw(self._state.db, self._node.template_id)
        if raw is None:
            return

        from hackmind.engine.template_loader import load_template_from_db_row
        template = load_template_from_db_row(raw)

        tnode = tree_engine._find_template_node(template, self._node.template_node_id)
        if tnode is None:
            return

        if current_key:
            opt = next((o for o in tnode.options if o.key == current_key), None)
            label = opt.label if opt else current_key
            self._answered_label.setText(f"Current answer: {label}")
            self._answered_label.show()
        else:
            self._answered_label.hide()

        for option in tnode.options:
            btn = QPushButton(option.label)
            btn.setObjectName("answerBtn")
            btn.setProperty("active", option.key == current_key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.clicked.connect(lambda checked, key=option.key: self._select(key))
            self._options_layout.addWidget(btn)

    def _select_asset_type(self, db_template_id: str) -> None:
        if self._node is None:
            return
        tree_engine.answer_asset_type(
            self._state.db, self._node.id, db_template_id
        )
        self._rebuild_options()
        self.tree_changed.emit()

    def _select(self, option_key: str) -> None:
        if self._node is None:
            return
        tree_engine.answer_question(
            self._state.db, self._node.id, option_key
        )
        self._rebuild_options()
        self.tree_changed.emit()

    def _clear(self) -> None:
        if self._node is None:
            return
        tree_engine.clear_question(self._state.db, self._node.id)
        self._rebuild_options()
        self.tree_changed.emit()
