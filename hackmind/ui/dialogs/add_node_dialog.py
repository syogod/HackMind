"""
Dialog for adding a manual node during an active pentest.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from hackmind.models.types import NodeType


_TYPE_LABELS = {
    NodeType.CHECKLIST: "Checklist Item",
    NodeType.INFO: "Info Section",
}


class AddNodeDialog(QDialog):
    """
    Collects a title and optional content for a new manual node.
    The node type is fixed at construction time (driven by the context menu).
    """

    def __init__(self, node_type: NodeType, parent=None) -> None:
        super().__init__(parent)
        self.node_type = node_type
        self.result_title: str = ""
        self.result_content: str = ""

        label = _TYPE_LABELS.get(node_type, node_type.value.title())
        self.setWindowTitle(f"Add {label}")
        self.setMinimumWidth(420)

        self._title_input = QLineEdit()
        self._title_input.setPlaceholderText("Short descriptive title")

        content_label = "Guidance / notes" if node_type == NodeType.CHECKLIST else "Description"
        self._content_input = QPlainTextEdit()
        self._content_input.setPlaceholderText("Optional — detail for this node")
        self._content_input.setFixedHeight(120)

        form = QFormLayout()
        form.addRow("Title:", self._title_input)
        form.addRow(QLabel(f"{content_label}:"))
        form.addRow(self._content_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        title = self._title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "Validation", "Title is required.")
            return
        self.result_title = title
        self.result_content = self._content_input.toPlainText().strip()
        self.accept()
