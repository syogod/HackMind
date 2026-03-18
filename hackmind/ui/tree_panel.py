"""
Left-panel tree view.

ProjectTreeModel (QAbstractItemModel) loads a flat list of nodes from
the DB, assembles them into a parent-child tree in memory, and provides
the QTreeView with display text, colors, and type decorations.

TreePanel wraps the model and view, adds a search box, and emits
node_selected(node_id) when the user clicks a node.
"""

from __future__ import annotations

from PyQt6.QtCore import QModelIndex, QPoint, QSortFilterProxyModel, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from hackmind.db import node_repo, scope_repo
from hackmind.db.database import Database
from hackmind.engine.status import compute_project_statuses
from hackmind.models.types import Node, NodeStatus, NodeType

_ANSWERED_QUESTION_COLOR = "#3d8b3d"  # same green as COMPLETE

# ---------------------------------------------------------------------------
# Status colours (foreground text)
# ---------------------------------------------------------------------------

_STATUS_COLORS: dict[NodeStatus, str] = {
    NodeStatus.NOT_STARTED:    "#888888",
    NodeStatus.IN_PROGRESS:    "#337ab7",
    NodeStatus.COMPLETE:       "#3d8b3d",
    NodeStatus.VULNERABLE:     "#d9534f",
    NodeStatus.NOT_APPLICABLE: "#aaaaaa",
}

# Type prefix shown before the node title
_TYPE_PREFIX: dict[NodeType, str] = {
    NodeType.QUESTION:  "? ",
    NodeType.CHECKLIST: "○ ",
    NodeType.ASSET:     "◎ ",
    NodeType.INFO:      "• ",
}

_FINDING_SUFFIX = "  ⚑"


# ---------------------------------------------------------------------------
# Internal tree item
# ---------------------------------------------------------------------------

class _TreeItem:
    __slots__ = ("node", "parent", "children", "derived_status", "is_answered")

    def __init__(self, node: Node, parent: "_TreeItem | None" = None) -> None:
        self.node = node
        self.parent: "_TreeItem | None" = parent
        self.children: list["_TreeItem"] = []
        self.derived_status: NodeStatus = node.status
        self.is_answered: bool = False


from PyQt6.QtCore import QAbstractItemModel


class _QtTreeModel(QAbstractItemModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._roots: list[_TreeItem] = []
        self._item_map: dict[str, _TreeItem] = {}

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def load(
        self,
        nodes: list[Node],
        statuses: dict[str, NodeStatus],
        answers: set[str],
    ) -> None:
        self.beginResetModel()

        all_items: dict[str, _TreeItem] = {}
        for node in nodes:
            item = _TreeItem(node)
            item.derived_status = statuses.get(node.id, node.status)
            item.is_answered = node.id in answers
            all_items[node.id] = item

        roots: list[_TreeItem] = []
        for node in nodes:
            item = all_items[node.id]
            if node.parent_id is None or node.parent_id not in all_items:
                roots.append(item)
            else:
                parent_item = all_items[node.parent_id]
                item.parent = parent_item
                parent_item.children.append(item)

        def _sort(items: list[_TreeItem]) -> None:
            items.sort(key=lambda x: x.node.position)
            for it in items:
                _sort(it.children)

        _sort(roots)
        self._roots = roots
        self._item_map = all_items

        self.endResetModel()

    def item_for_node(self, node_id: str) -> "_TreeItem | None":
        return self._item_map.get(node_id)

    # ------------------------------------------------------------------
    # QAbstractItemModel required overrides
    # ------------------------------------------------------------------

    def index(self, row: int, col: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, col, parent):
            return QModelIndex()
        siblings = self._roots if not parent.isValid() else parent.internalPointer().children
        if row < len(siblings):
            return self.createIndex(row, col, siblings[row])
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:  # type: ignore[override]
        if not index.isValid():
            return QModelIndex()
        item: _TreeItem = index.internalPointer()
        if item.parent is None:
            return QModelIndex()
        p = item.parent
        grandparent_children = self._roots if p.parent is None else p.parent.children
        row = grandparent_children.index(p)
        return self.createIndex(row, 0, p)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.column() > 0:
            return 0
        if not parent.isValid():
            return len(self._roots)
        return len(parent.internalPointer().children)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item: _TreeItem = index.internalPointer()

        if role == Qt.ItemDataRole.DisplayRole:
            prefix = _TYPE_PREFIX.get(item.node.type, "  ")
            suffix = _FINDING_SUFFIX if item.node.is_finding else ""
            return f"{prefix}{item.node.title}{suffix}"

        if role == Qt.ItemDataRole.ForegroundRole:
            if item.node.type == NodeType.QUESTION and item.is_answered:
                return QColor(_ANSWERED_QUESTION_COLOR)
            hex_color = _STATUS_COLORS.get(item.derived_status, "#000000")
            return QColor(hex_color)

        if role == Qt.ItemDataRole.FontRole:
            if item.node.status == NodeStatus.NOT_APPLICABLE:
                font = QFont()
                font.setStrikeOut(True)
                return font

        if role == Qt.ItemDataRole.UserRole:
            return item.node.id

        if role == Qt.ItemDataRole.ToolTipRole:
            return item.derived_status.label()

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


# ---------------------------------------------------------------------------
# Tree Panel widget
# ---------------------------------------------------------------------------

_TREE_WIDTH_MIN = 240
_TREE_WIDTH_MAX = 480


# ---------------------------------------------------------------------------
# Scope-aware proxy model
# ---------------------------------------------------------------------------

_DONE_STATUSES = frozenset(("complete", "vulnerable", "not_applicable"))


class _ScopeFilterProxy(QSortFilterProxyModel):
    """
    Extends the standard text-search proxy with two extra filters:

    OOS-tag filtering — a row is hidden when its node's scope_tags
    intersect the active out-of-scope set.

    Hide-done filtering — checklist nodes whose status is complete,
    vulnerable, or not_applicable are hidden.  INFO, ASSET, and QUESTION
    nodes are never hidden by this filter (they are containers or branch
    points; hiding them would also hide any incomplete work underneath).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._oos_tags: frozenset[str] = frozenset()
        self._hide_done: bool = False

    def set_oos_tags(self, tags: set[str]) -> None:
        self._oos_tags = frozenset(tags)
        self.invalidateFilter()

    def set_hide_done(self, hide: bool) -> None:
        self._hide_done = hide
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        idx = self.sourceModel().index(source_row, 0, source_parent)
        item = idx.internalPointer()

        if item is not None:
            node = item.node
            # OOS filter — unconditionally hides tagged nodes.
            if self._oos_tags and self._oos_tags.intersection(node.scope_tags):
                return False
            # Hide-done filter — only applies to checklist nodes.
            if self._hide_done and node.type == NodeType.CHECKLIST:
                if node.status.value in _DONE_STATUSES:
                    return False

        return super().filterAcceptsRow(source_row, source_parent)


class TreePanel(QWidget):
    node_selected      = pyqtSignal(str)        # emits node_id
    width_hint_changed = pyqtSignal(int)        # emits ideal panel width
    node_add_requested = pyqtSignal(str, str)   # (parent_node_id, node_type_value)
    export_requested   = pyqtSignal(str)        # emits asset node_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = _QtTreeModel()
        self._last_info_id: str | None = None
        self._db: Database | None = None
        self._project_id: str | None = None

        self._proxy = _ScopeFilterProxy()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterRole(Qt.ItemDataRole.DisplayRole)
        self._proxy.setRecursiveFilteringEnabled(True)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search nodes…")
        self._search.textChanged.connect(self._proxy.setFilterFixedString)

        self._scope_btn = QPushButton("Scope…")
        self._scope_btn.setEnabled(False)
        self._scope_btn.clicked.connect(self._on_scope_clicked)

        self._hide_done_btn = QCheckBox("Hide Completed")
        self._hide_done_btn.setEnabled(False)
        self._hide_done_btn.toggled.connect(self._on_hide_done_toggled)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(4)
        search_row.addWidget(self._search)

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(4)
        filter_row.addWidget(self._scope_btn)
        filter_row.addWidget(self._hide_done_btn)
        filter_row.addStretch()

        self._tree = QTreeView()
        self._tree.setModel(self._proxy)
        self._tree.setHeaderHidden(True)
        self._tree.setAnimated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.selectionModel().currentChanged.connect(self._on_selection)
        self._tree.expanded.connect(self._emit_width_hint)
        self._tree.collapsed.connect(self._emit_width_hint)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)

        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setVisible(False)

        self._progress_label = QLabel()
        self._progress_label.setVisible(False)
        font = self._progress_label.font()
        font.setPointSize(max(7, font.pointSize() - 1))
        self._progress_label.setFont(font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(search_row)
        layout.addLayout(filter_row)
        layout.addWidget(self._tree)
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._progress_label)

    def load(self, db: Database, project_id: str) -> None:
        self._db = db
        self._project_id = project_id
        nodes = node_repo.get_project_nodes(db, project_id)
        statuses = compute_project_statuses(db, project_id)
        answers = set(node_repo.get_answers_for_project(db, project_id).keys())
        self._model.load(nodes, statuses, answers)
        oos = scope_repo.get_oos_tags(db, project_id)
        self._proxy.set_oos_tags(oos)
        self._scope_btn.setEnabled(True)
        self._hide_done_btn.setEnabled(True)
        self._update_scope_button(oos)
        self._update_progress(db, project_id, oos)
        self._tree.expandAll()
        self._collapse_info_nodes()
        self._emit_width_hint()

    def _collapse_info_nodes(self) -> None:
        """Collapse all INFO nodes so the tree opens in a tidy state."""
        def _walk(parent: QModelIndex) -> None:
            for row in range(self._proxy.rowCount(parent)):
                idx = self._proxy.index(row, 0, parent)
                source = self._proxy.mapToSource(idx)
                node_id = self._model.data(source, Qt.ItemDataRole.UserRole)
                item = self._model.item_for_node(node_id)
                if item and item.node.type == NodeType.INFO:
                    self._tree.collapse(idx)
                _walk(idx)
        _walk(QModelIndex())

    def refresh(self, db: Database, project_id: str) -> None:
        """Reload tree data, preserving expansion state, selection, and scroll position."""
        self._db = db
        self._project_id = project_id
        selected_id = self._current_node_id()
        expanded = self._get_expanded_ids()

        # Save scroll position before model reset — beginResetModel/endResetModel
        # inside model.load() causes Qt to reset the viewport to the top.
        vbar = self._tree.verticalScrollBar()
        saved_scroll = vbar.value()

        nodes = node_repo.get_project_nodes(db, project_id)
        statuses = compute_project_statuses(db, project_id)
        answers = set(node_repo.get_answers_for_project(db, project_id).keys())
        self._model.load(nodes, statuses, answers)
        oos = scope_repo.get_oos_tags(db, project_id)
        self._proxy.set_oos_tags(oos)
        self._proxy.set_hide_done(self._hide_done_btn.isChecked())
        self._scope_btn.setEnabled(True)
        self._hide_done_btn.setEnabled(True)
        self._update_scope_button(oos)
        self._update_progress(db, project_id, oos)
        self._restore_expanded(expanded)
        if selected_id:
            self._reselect(selected_id, scroll=False)
        self._emit_width_hint()

        # Restore scroll position after all tree operations are complete.
        vbar.setValue(saved_scroll)

    def clear(self) -> None:
        self._last_info_id = None
        self._db = None
        self._project_id = None
        self._proxy.set_oos_tags(set())
        self._proxy.set_hide_done(False)
        self._scope_btn.setEnabled(False)
        self._hide_done_btn.setEnabled(False)
        self._hide_done_btn.setChecked(False)
        self._progress_bar.setVisible(False)
        self._progress_label.setVisible(False)
        self._model.load([], {}, set())
        self._emit_width_hint()

    def select_node(self, node_id: str) -> None:
        self._reselect(node_id)

    def _on_context_menu(self, pos: QPoint) -> None:
        idx = self._tree.indexAt(pos)
        if not idx.isValid():
            return
        source = self._proxy.mapToSource(idx)
        node_id = self._model.data(source, Qt.ItemDataRole.UserRole)
        item = self._model.item_for_node(node_id)
        if item is None:
            return

        node_type = item.node.type
        # Questions manage their own children via answer flow — skip them.
        if node_type == NodeType.QUESTION:
            return

        menu = QMenu(self)

        if node_type in (NodeType.ASSET, NodeType.INFO, NodeType.CHECKLIST):
            add_checklist = QAction("Add Checklist Item…", self)
            add_checklist.triggered.connect(
                lambda: self.node_add_requested.emit(node_id, "checklist")
            )
            add_info = QAction("Add Info Section…", self)
            add_info.triggered.connect(
                lambda: self.node_add_requested.emit(node_id, "info")
            )
            menu.addAction(add_checklist)
            menu.addAction(add_info)

        if node_type == NodeType.ASSET:
            menu.addSeparator()
            export_action = QAction("Export as Template…", self)
            export_action.triggered.connect(
                lambda: self.export_requested.emit(node_id)
            )
            menu.addAction(export_action)

        if not menu.isEmpty():
            menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _on_hide_done_toggled(self, checked: bool) -> None:
        self._proxy.set_hide_done(checked)

    def _on_scope_clicked(self) -> None:
        if self._db is None or self._project_id is None:
            return
        from hackmind.ui.dialogs.scope_dialog import ScopeDialog
        dialog = ScopeDialog(self._db, self._project_id, self)
        if dialog.exec() == ScopeDialog.DialogCode.Accepted:
            oos_tags = scope_repo.get_oos_tags(self._db, self._project_id)
            self._proxy.set_oos_tags(oos_tags)
            self._update_scope_button(oos_tags)
            self._update_progress(self._db, self._project_id, oos_tags)

    def _update_progress(self, db: Database, project_id: str, oos_tags: set[str]) -> None:
        stats = node_repo.get_project_progress(db, project_id, oos_tags or None)
        total = stats["total"]
        complete = stats["complete"]

        if total == 0:
            self._progress_bar.setVisible(False)
            self._progress_label.setVisible(False)
            return

        pct = int(complete / total * 100)
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(complete)
        self._progress_bar.setVisible(True)

        in_progress_count = self._count_in_progress(db, project_id, oos_tags)
        remaining = total - complete - in_progress_count
        parts = [f"{complete} complete"]
        if in_progress_count:
            parts.append(f"{in_progress_count} in progress")
        if remaining:
            parts.append(f"{remaining} not started")
        self._progress_label.setText(f"  {pct}%  —  " + "  ·  ".join(parts))
        self._progress_label.setVisible(True)

    def _count_in_progress(self, db: Database, project_id: str, oos_tags: set[str]) -> int:
        import json as _json
        rows = db.conn.execute(
            """
            SELECT scope_tags FROM nodes
             WHERE project_id = ? AND soft_deleted = 0
               AND type = 'checklist' AND status = 'in_progress'
            """,
            (project_id,),
        ).fetchall()
        count = 0
        for row in rows:
            if oos_tags:
                tags = _json.loads(row["scope_tags"] or "[]")
                if oos_tags.intersection(tags):
                    continue
            count += 1
        return count

    def _update_scope_button(self, oos_tags: set[str]) -> None:
        if oos_tags:
            self._scope_btn.setText(f"Scope ({len(oos_tags)})")
        else:
            self._scope_btn.setText("Scope…")

    def _on_selection(self, current: QModelIndex, _previous: QModelIndex) -> None:
        source = self._proxy.mapToSource(current)
        if not source.isValid():
            return
        node_id = self._model.data(source, Qt.ItemDataRole.UserRole)
        if not node_id:
            return

        # Collapse the previously auto-expanded Info node if we've moved away from it.
        # Deferred via singleShot to avoid re-entrancy: collapse() fires another
        # currentChanged, which would clobber the visual selection mid-handler.
        if self._last_info_id is not None and node_id != self._last_info_id:
            if not self._is_descendant_of(node_id, self._last_info_id):
                _id = self._last_info_id
                self._last_info_id = None
                QTimer.singleShot(0, lambda: self._collapse_info_node(_id))

        # Auto-expand newly selected Info nodes (tracked for auto-collapse)
        # and Asset nodes (expand only, no auto-collapse)
        item = self._model.item_for_node(node_id)
        if item is not None and item.node.type == NodeType.INFO:
            self._last_info_id = node_id
            self._tree.expand(current)
        elif item is not None and item.node.type == NodeType.ASSET:
            self._tree.expand(current)

        self.node_selected.emit(node_id)

    def _current_node_id(self) -> str | None:
        idx = self._tree.currentIndex()
        if idx.isValid():
            source = self._proxy.mapToSource(idx)
            return self._model.data(source, Qt.ItemDataRole.UserRole)
        return None

    def _get_expanded_ids(self) -> set[str]:
        """Return node IDs of all currently expanded items in the proxy model."""
        expanded: set[str] = set()

        def _walk(parent: QModelIndex) -> None:
            for row in range(self._proxy.rowCount(parent)):
                idx = self._proxy.index(row, 0, parent)
                if self._tree.isExpanded(idx):
                    source = self._proxy.mapToSource(idx)
                    node_id = self._model.data(source, Qt.ItemDataRole.UserRole)
                    if node_id:
                        expanded.add(node_id)
                _walk(idx)

        _walk(QModelIndex())
        return expanded

    def _restore_expanded(self, node_ids: set[str]) -> None:
        """Expand items whose node IDs appear in node_ids."""
        def _walk(parent: QModelIndex) -> None:
            for row in range(self._proxy.rowCount(parent)):
                idx = self._proxy.index(row, 0, parent)
                source = self._proxy.mapToSource(idx)
                node_id = self._model.data(source, Qt.ItemDataRole.UserRole)
                if node_id and node_id in node_ids:
                    self._tree.expand(idx)
                _walk(idx)

        _walk(QModelIndex())

    def _emit_width_hint(self, _index: QModelIndex = QModelIndex()) -> None:
        raw = self._tree.sizeHintForColumn(0)
        if raw <= 0:
            return
        # Add padding for branch indicators, scrollbar, and panel margins
        width = max(_TREE_WIDTH_MIN, min(_TREE_WIDTH_MAX, raw + 48))
        self.width_hint_changed.emit(width)

    def _collapse_info_node(self, node_id: str) -> None:
        idx = self._proxy_index_for_node(node_id)
        if idx.isValid():
            self._tree.collapse(idx)

    def _proxy_index_for_node(self, node_id: str) -> QModelIndex:
        item = self._model.item_for_node(node_id)
        if item is None:
            return QModelIndex()
        path: list[_TreeItem] = []
        cur = item
        while cur is not None:
            path.insert(0, cur)
            cur = cur.parent
        idx = QModelIndex()
        for part in path:
            siblings = self._model._roots if part.parent is None else part.parent.children
            try:
                row = siblings.index(part)
            except ValueError:
                return QModelIndex()
            idx = self._model.index(row, 0, idx)
        return self._proxy.mapFromSource(idx)

    def _is_descendant_of(self, node_id: str, ancestor_id: str) -> bool:
        item = self._model.item_for_node(node_id)
        if item is None:
            return False
        cur = item.parent
        while cur is not None:
            if cur.node.id == ancestor_id:
                return True
            cur = cur.parent
        return False

    def _reselect(self, node_id: str, scroll: bool = True) -> None:
        item = self._model.item_for_node(node_id)
        if item is None:
            return
        # Walk up to build the path from root → item
        path: list[_TreeItem] = []
        cur = item
        while cur is not None:
            path.insert(0, cur)
            cur = cur.parent

        idx = QModelIndex()
        for part in path:
            siblings = self._model._roots if part.parent is None else part.parent.children
            try:
                row = siblings.index(part)
            except ValueError:
                return
            idx = self._model.index(row, 0, idx)
            # Expand each ancestor so the selected item is always visible
            self._tree.expand(self._proxy.mapFromSource(idx))

        proxy_idx = self._proxy.mapFromSource(idx)
        self._tree.setCurrentIndex(proxy_idx)
        if scroll:
            self._tree.scrollTo(proxy_idx)
