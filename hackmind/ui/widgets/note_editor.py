"""
Auto-saving note editor widget.

Debounces saves: waits for the configured auto-save delay (default 800 ms)
after the last keystroke before writing to the DB, so we don't hammer
SQLite on every character. The delay is read from settings on each keystroke
so changes made in the Settings dialog take effect immediately.
"""

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

from hackmind.db import node_repo
from hackmind.db.database import Database


class NoteEditor(QWidget):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._node_id: str | None = None

        self._editor = QTextEdit()
        self._editor.setPlaceholderText("Add notes here…")
        self._editor.textChanged.connect(self._on_text_changed)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._editor)

    def load(self, node_id: str) -> None:
        """Load the note for the given node, replacing the editor content."""
        self._save_timer.stop()
        self._node_id = node_id
        note = node_repo.get_note(self._db, node_id)
        # Block signals so loading content doesn't trigger auto-save
        self._editor.blockSignals(True)
        self._editor.setPlainText(note.content)
        self._editor.blockSignals(False)

    def flush(self) -> None:
        """Force an immediate save, e.g., before switching nodes."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save()

    def _on_text_changed(self) -> None:
        from hackmind import settings as _settings
        self._save_timer.start(_settings.autosave_delay_ms())

    def _save(self) -> None:
        if self._node_id is not None:
            node_repo.save_note(self._db, self._node_id, self._editor.toPlainText())
