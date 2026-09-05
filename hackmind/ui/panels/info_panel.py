"""
Info node panel — right-pane context for the selected node.

For checklist/question nodes the center pane already shows the guidance
content, so this panel shows compact metadata instead (no duplication).
For info/asset nodes the content is shown here (it has no center view).
"""

from PyQt6.QtWidgets import (
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from hackmind.ui.themes import title_point_size
from hackmind.models.types import Node, NodeType
from hackmind.db import node_repo


class InfoPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._title = QLabel()
        self._title.setWordWrap(True)
        font = self._title.font()
        font.setPointSize(title_point_size())
        font.setBold(True)
        self._title.setFont(font)

        self._meta = QLabel()
        self._meta.setWordWrap(True)
        self._meta.setObjectName("mutedLabel")

        self._body = QTextBrowser()
        self._body.setOpenExternalLinks(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addWidget(self._meta)
        layout.addWidget(self._body, stretch=1)

    def load(self, node: Node) -> None:
        self._title.setText(node.title)

        # Metadata line: type · status · finding flag · severity · scope tags
        severity = next(
            (t for t in node.scope_tags if t.lower() in node_repo.SEVERITY_TAGS), None
        )
        other_tags = [
            t for t in node.scope_tags if t.lower() not in node_repo.SEVERITY_TAGS
        ]
        parts = [node.type.value.replace("_", " ").capitalize()]
        if node.is_finding:
            parts.append(f"Finding — {severity or 'info'}")
        elif node.status != "not_started" or node.type == NodeType.CHECKLIST:
            parts.append(str(node.status.value).replace("_", " ").capitalize())
        if other_tags:
            parts.append(" ".join(f"#{t}" for t in other_tags))
        self._meta.setText(" · ".join(parts))

        # Content: only when the center pane doesn't already show it.
        if node.type in (NodeType.CHECKLIST, NodeType.QUESTION):
            self._body.hide()
            self._body.setPlainText("")
        else:
            self._body.show()
            self._body.setPlainText(node.content or "")
