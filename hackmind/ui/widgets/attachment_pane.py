"""
Attachment management widget.

Shows a thumbnail grid of files attached to a node.
Images render as scaled previews; other file types show a generic icon.
Double-clicking an item opens a viewer dialog.
"""

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from hackmind.db import attachment_repo
from hackmind.db.database import Database
from hackmind.models.types import Attachment

_IMAGE_TYPES = "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"
_ALL_TYPES = "All files (*)"
_FILTER = f"{_IMAGE_TYPES};;{_ALL_TYPES}"

_THUMB = 80   # thumbnail size in pixels
_GRID  = 110  # grid cell size (thumb + label room)


class AttachmentPane(QWidget):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._node_id: str | None = None

        self._grid = QListWidget()
        self._grid.setViewMode(QListWidget.ViewMode.IconMode)
        self._grid.setIconSize(QSize(_THUMB, _THUMB))
        self._grid.setGridSize(QSize(_GRID, _GRID))
        self._grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._grid.setMovement(QListWidget.Movement.Static)
        self._grid.setUniformItemSizes(True)
        self._grid.setWordWrap(True)
        self._grid.setSpacing(4)
        self._grid.itemDoubleClicked.connect(self._view_attachment)

        btn_attach = QPushButton("Attach File…")
        btn_attach.clicked.connect(self._attach_file)

        btn_delete = QPushButton("Delete")
        btn_delete.clicked.connect(self._delete_selected)

        btn_row = QHBoxLayout()
        btn_row.addWidget(btn_attach)
        btn_row.addWidget(btn_delete)
        btn_row.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._grid)
        layout.addLayout(btn_row)

    def load(self, node_id: str) -> None:
        self._node_id = node_id
        self._refresh()

    def _refresh(self) -> None:
        self._grid.clear()
        if self._node_id is None:
            return
        # Load with data so we can generate image thumbnails.
        attachments = attachment_repo.get_attachments_for_node(
            self._db, self._node_id, include_data=True
        )
        for att in attachments:
            icon = self._make_icon(att)
            # Truncate long filenames so they fit under the thumbnail.
            label = att.filename if len(att.filename) <= 18 else att.filename[:15] + "…"
            item = QListWidgetItem(icon, label)
            item.setData(Qt.ItemDataRole.UserRole, att.id)
            item.setToolTip(att.filename)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
            self._grid.addItem(item)

    def _make_icon(self, att: Attachment) -> QIcon:
        if att.mime_type.startswith("image/") and att.data:
            pixmap = QPixmap()
            pixmap.loadFromData(att.data)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    _THUMB, _THUMB,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                return QIcon(pixmap)
        return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    def _attach_file(self) -> None:
        if self._node_id is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Attach File", "", _FILTER)
        if not path:
            return
        file_path = Path(path)
        data = file_path.read_bytes()
        mime = _guess_mime(file_path.suffix.lower())
        att = Attachment(
            node_id=self._node_id,
            filename=file_path.name,
            mime_type=mime,
            data=data,
        )
        attachment_repo.insert_attachment(self._db, att)
        self._refresh()

    def _delete_selected(self) -> None:
        item = self._grid.currentItem()
        if item is None:
            return
        att_id = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self,
            "Delete Attachment",
            f"Delete '{item.toolTip()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            attachment_repo.delete_attachment(self._db, att_id)
            self._refresh()

    def _view_attachment(self, item: QListWidgetItem) -> None:
        att_id = item.data(Qt.ItemDataRole.UserRole)
        att = attachment_repo.get_attachment(self._db, att_id)
        if att is None:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(att.filename)
        layout = QVBoxLayout(dialog)

        if att.mime_type.startswith("image/"):
            pixmap = QPixmap()
            pixmap.loadFromData(att.data)
            label = QLabel()
            label.setPixmap(
                pixmap.scaled(
                    800, 600,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            scroll = QScrollArea()
            scroll.setWidget(label)
            scroll.setWidgetResizable(True)
            layout.addWidget(scroll)
        else:
            info = QLabel(f"<b>{att.filename}</b><br>{len(att.data):,} bytes")
            info.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(info)

        dialog.resize(820, 640)
        dialog.exec()


def _guess_mime(suffix: str) -> str:
    return {
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif":  "image/gif",
        ".bmp":  "image/bmp",
        ".webp": "image/webp",
        ".pdf":  "application/pdf",
        ".txt":  "text/plain",
    }.get(suffix, "application/octet-stream")
