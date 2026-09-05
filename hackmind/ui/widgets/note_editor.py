"""
Auto-saving note editor widget.

Debounces saves: waits for the configured auto-save delay (default 800 ms)
after the last keystroke before writing to the DB, so we don't hammer
SQLite on every character. The delay is read from settings on each keystroke
so changes made in the Settings dialog take effect immediately.
"""

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QTextEdit,
    QTextBrowser,
    QVBoxLayout,
    QSplitter,
    QWidget,
)
try:
    from markdown_it import MarkdownIt
    _HAS_MARKDOWN_IT = True
except ImportError:
    _HAS_MARKDOWN_IT = False

from hackmind.db import node_repo
from hackmind.db.database import Database


class NoteEditor(QWidget):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._node_id: str | None = None
        self._md = MarkdownIt("gfm-like") if _HAS_MARKDOWN_IT else None
        self.setAcceptDrops(True)

        # UI Components
        self._editor = QTextEdit()
        self._editor.setPlaceholderText("Add notes here (Markdown supported)…")
        self._editor.textChanged.connect(self._on_text_changed)

        self._preview = QTextBrowser()
        self._preview.setOpenExternalLinks(True)
        # Add basic CSS for markdown preview
        self._preview.setHtml("<em>Preview area</em>")

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.addWidget(self._editor)
        self._splitter.addWidget(self._preview)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._splitter)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save)

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_preview)

    def load(self, node_id: str) -> None:
        """Load the note for the given node, replacing the editor content."""
        self.flush()
        self._node_id = node_id
        note = node_repo.get_note(self._db, node_id)
        
        self._editor.blockSignals(True)
        self._editor.setPlainText(note.content if note else "")
        self._editor.blockSignals(False)
        self._render_preview()

    def set_text(self, text: str) -> None:
        """Set editor content and update preview."""
        self._editor.setPlainText(text)
        self._render_preview()

    def flush(self) -> None:
        """Force an immediate save, e.g., before switching nodes."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save()

    def _on_text_changed(self) -> None:
        from hackmind import settings as _settings
        self._save_timer.start(_settings.autosave_delay_ms())
        self._render_timer.start(200) # Faster feedback for preview

    def _save(self) -> None:
        if self._node_id is not None:
            node_repo.save_note(self._db, self._node_id, self._editor.toPlainText())

    def _render_preview(self) -> None:
        content = self._editor.toPlainText()
        if _HAS_MARKDOWN_IT and self._md:
            html = self._md.render(content)
            css = """
            <style>
                body { font-family: sans-serif; line-height: 1.5; color: #333; padding: 10px; }
                code { background-color: #f4f4f4; padding: 2px 4px; border-radius: 3px; font-family: monospace; }
                pre { background-color: #f4f4f4; padding: 10px; border-radius: 5px; overflow-x: auto; }
                pre code { background-color: transparent; padding: 0; }
                h1, h2, h3 { border-bottom: 1px solid #eee; padding-bottom: 5px; }
                blockquote { border-left: 4px solid #ddd; padding-left: 10px; color: #777; }
                table { border-collapse: collapse; width: 100%; }
                th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                th { background-color: #f2f2f2; }
            </style>
            """
            self._preview.setHtml(css + html)
        else:
            self._preview.setMarkdown(content)

    # Drag and Drop for attachments
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        if self._node_id is None:
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
                    node_id=self._node_id,
                    filename=file_path.name,
                    mime_type=mime_type or "application/octet-stream",
                    data=data
                )
                attachment_repo.insert_attachment(self._db, att)
        
        event.acceptProposedAction()
