"""
Info node panel — read-only guidance text.
"""

from PyQt6.QtWidgets import QLabel, QTextBrowser, QVBoxLayout, QWidget

from hackmind.models.types import Node


class InfoPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._title = QLabel()
        self._title.setWordWrap(True)
        font = self._title.font()
        font.setPointSize(14)
        font.setBold(True)
        self._title.setFont(font)

        self._body = QTextBrowser()
        self._body.setOpenExternalLinks(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addWidget(self._body)

    def load(self, node: Node) -> None:
        self._title.setText(node.title)
        self._body.setPlainText(node.content or "")
