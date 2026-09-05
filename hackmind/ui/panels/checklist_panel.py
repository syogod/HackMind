"""
Checklist node panel.

Controls: status selector, "Is Finding" toggle, notes editor,
and the attachment pane.
"""

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QScrollArea,
)

from hackmind.ui.themes import title_point_size
from hackmind.db import node_repo
from hackmind.db.database import Database
from hackmind.models.types import Node, NodeStatus

_STATUS_OPTIONS = [
    (NodeStatus.NOT_STARTED,    "Not Started"),
    (NodeStatus.IN_PROGRESS,    "In Progress"),
    (NodeStatus.COMPLETE,       "Complete"),
    (NodeStatus.VULNERABLE,     "Vulnerable"),
    (NodeStatus.NOT_APPLICABLE, "N/A"),
]


class CollapsibleSection(QWidget):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self._is_expanded = True
        
        self._toggle_btn = QPushButton(f"▼ {title}")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(True)
        self._toggle_btn.setStyleSheet("text-align: left; font-weight: bold; padding: 5px;")
        self._toggle_btn.clicked.connect(self.toggle)
        
        self._content_area = QWidget()
        self._content_layout = QVBoxLayout(self._content_area)
        self._content_layout.setContentsMargins(15, 5, 0, 5)
        self._content_layout.setSpacing(5)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._toggle_btn)
        main_layout.addWidget(self._content_area)
        
    def add_widget(self, widget: QWidget) -> None:
        self._content_layout.addWidget(widget)
        
    def toggle(self) -> None:
        self._is_expanded = not self._is_expanded
        self._content_area.setVisible(self._is_expanded)
        self._toggle_btn.setText(f"{'▼' if self._is_expanded else '▶'} {self._toggle_btn.text()[2:]}")


class ChecklistPanel(QWidget):
    tree_changed = pyqtSignal()

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._node: Node | None = None
        self._loading = False
        self.setAcceptDrops(True)

        # Filter UI
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter by tag or text (e.g., id:IDOR, crit)...")
        self._filter_edit.textChanged.connect(self._on_filter_changed)

        self._title = QLabel()
        self._title.setWordWrap(True)
        font = self._title.font()
        font.setPointSize(title_point_size())
        font.setBold(True)
        self._title.setFont(font)

        self._guidance = QTextBrowser()
        self._guidance.setOpenExternalLinks(True)
        self._guidance.setMaximumHeight(100)

        # Scrollable area for accordions
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._accordions_layout = QVBoxLayout(self._scroll_content)
        self._accordions_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._scroll_content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        layout.addWidget(self._filter_edit)
        layout.addWidget(self._title)
        layout.addWidget(self._guidance)
        layout.addWidget(self._scroll)

    def load(self, node: Node) -> None:
        self._loading = True
        self._node = node
        self._title.setText(node.title)
        self._guidance.setPlainText(node.content or "")
        self._guidance.setVisible(bool(node.content))

        # Clear accordions
        while self._accordions_layout.count():
            item = self._accordions_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Load sub-steps as accordions
        children = node_repo.get_children(self._db, node.id)
        if not children:
            # If no children, just show the node itself as a row? 
            # Or maybe just show its status controls.
            self._add_node_row(node, self._accordions_layout)
        else:
            # Group children by some logic or just list them
            # For now, let's create accordions for categories if we have them, 
            # or just one big one if not.
            main_sec = CollapsibleSection("Sub-steps")
            self._accordions_layout.addWidget(main_sec)
            for child in children:
                self._add_node_row(child, main_sec)

        self._loading = False

    def _add_node_row(self, node: Node, parent_layout_or_sec) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 2, 0, 2)
        
        status_check = QCheckBox()
        status_check.setChecked(node.status == NodeStatus.COMPLETE or node.status == NodeStatus.VULNERABLE)
        status_check.toggled.connect(lambda checked, n=node: self._on_row_toggled(n, checked))
        
        title_label = QLabel(node.title)
        title_label.setWordWrap(True)
        
        status_combo = QComboBox()
        for status, label in _STATUS_OPTIONS:
            status_combo.addItem(label, userData=status)
            if status == node.status:
                status_combo.setCurrentIndex(status_combo.count() - 1)
        status_combo.currentIndexChanged.connect(lambda idx, n=node, cb=status_combo: self._on_row_status_changed(n, cb.currentData()))
        
        finding_check = QCheckBox("Finding")
        finding_check.setChecked(node.is_finding)
        finding_check.toggled.connect(lambda checked, n=node: self._on_row_finding_toggled(n, checked))
        
        severity_combo = QComboBox()
        for sev in ("info", "low", "medium", "high", "critical"):
            severity_combo.addItem(sev.capitalize(), userData=sev)
        current_sev = next(
            (t for t in node.scope_tags if t.lower() in node_repo.SEVERITY_TAGS), "info"
        )
        sev_idx = severity_combo.findData(current_sev)
        severity_combo.setCurrentIndex(sev_idx if sev_idx >= 0 else 0)
        severity_combo.setToolTip("Finding severity (used in the exported report)")
        severity_combo.currentIndexChanged.connect(
            lambda idx, n=node, cb=severity_combo: self._on_row_severity_changed(n, cb.currentData())
        )
        
        row_layout.addWidget(status_check)
        row_layout.addWidget(title_label, stretch=1)
        row_layout.addWidget(severity_combo)
        row_layout.addWidget(status_combo)
        row_layout.addWidget(finding_check)
        
        # Store tags for filtering
        row.setProperty("tags", " ".join(node.scope_tags).lower())
        row.setProperty("title", node.title.lower())
        
        if hasattr(parent_layout_or_sec, "add_widget"):
            parent_layout_or_sec.add_widget(row)
        else:
            parent_layout_or_sec.addWidget(row)

    def _on_filter_changed(self, text: str) -> None:
        text = text.lower()
        def _walk_layout(layout):
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item.widget():
                    w = item.widget()
                    if isinstance(w, CollapsibleSection):
                        # Filter rows inside accordion
                        _walk_layout(w._content_layout)
                    else:
                        tags = w.property("tags") or ""
                        title = w.property("title") or ""
                        visible = not text or text in tags or text in title
                        w.setVisible(visible)
        _walk_layout(self._accordions_layout)

    def _on_row_toggled(self, node: Node, checked: bool) -> None:
        if self._loading: return
        new_status = NodeStatus.COMPLETE if checked else NodeStatus.NOT_STARTED
        self._on_row_status_changed(node, new_status)

    def _on_row_status_changed(self, node: Node, status: NodeStatus) -> None:
        if self._loading: return
        node_repo.set_status(self._db, node.id, status)
        node.status = status
        self.tree_changed.emit()

    def _on_row_finding_toggled(self, node: Node, checked: bool) -> None:
        if self._loading: return
        node_repo.set_finding(self._db, node.id, checked)
        node.is_finding = checked

    def _on_row_severity_changed(self, node: Node, severity: str) -> None:
        if self._loading or severity is None: return
        node_repo.set_severity(self._db, node.id, severity)
        # Keep the in-memory node's tags in sync (replace severity tag).
        node.scope_tags = [
            t for t in node.scope_tags if t.lower() not in node_repo.SEVERITY_TAGS
        ] + [severity]
        self.tree_changed.emit()

    def flush(self) -> None:
        pass # Notes handled in right pane now

    # Drag and Drop for attachments
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        if self._node is None:
            return
        from hackmind.db import attachment_repo
        from hackmind.models.types import Attachment
        import mimetypes
        from pathlib import Path

        for url in event.mimeData().urls():
            file_path = Path(url.toLocalFile())
            if file_path.is_file():
                data = file_path.read_bytes()
                mime_type, _ = mimetypes.guess_type(str(file_path))
                att = Attachment(
                    node_id=self._node.id,
                    filename=file_path.name,
                    mime_type=mime_type or "application/octet-stream",
                    data=data
                )
                attachment_repo.insert_attachment(self._db, att)
        
        # Notify user or refresh UI
        self.tree_changed.emit()
        event.acceptProposedAction()
