"""
Dialog for exporting the current asset's node tree as a new template.

Pre-fills name/version from the original template (if found) and suggests
a bumped patch version so the export is always a distinct new template.
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


class ExportTemplateDialog(QDialog):
    """
    Collects name, version, author, and description for the exported template.
    On accept, results are available as instance attributes.
    """

    def __init__(
        self,
        suggested_name: str = "",
        suggested_version: str = "1.0.0",
        suggested_author: str = "",
        suggested_description: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export as Template")
        self.setMinimumWidth(460)

        self.result_name: str = ""
        self.result_version: str = ""
        self.result_author: str = ""
        self.result_description: str = ""

        self._name = QLineEdit(suggested_name)
        self._version = QLineEdit(suggested_version)
        self._author = QLineEdit(suggested_author)
        self._description = QPlainTextEdit(suggested_description)
        self._description.setFixedHeight(80)
        self._description.setPlaceholderText("Optional — methodology overview")

        hint = QLabel(
            "This creates a new independent template. "
            "The original template and any open projects using it are unaffected."
        )
        hint.setWordWrap(True)
        hint.setObjectName("hintLabel")

        form = QFormLayout()
        form.addRow("Template name:", self._name)
        form.addRow("Version:", self._version)
        form.addRow("Author:", self._author)
        form.addRow(QLabel("Description:"))
        form.addRow(self._description)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        name = self._name.text().strip()
        version = self._version.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Template name is required.")
            return
        if not version:
            QMessageBox.warning(self, "Validation", "Version is required.")
            return
        self.result_name = name
        self.result_version = version
        self.result_author = self._author.text().strip()
        self.result_description = self._description.toPlainText().strip()
        self.accept()
