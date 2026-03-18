"""
CRUD operations for node attachments.

Attachments are stored as BLOBs in the database.
For MVP this keeps everything in one file. If the DB grows too large,
a future migration can move data to a project attachments/ folder.
"""

from datetime import datetime, timezone
from typing import Optional

from hackmind.db.database import Database
from hackmind.models.types import Attachment


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_attachment(row, include_data: bool = True) -> Attachment:
    return Attachment(
        id=row["id"],
        node_id=row["node_id"],
        filename=row["filename"],
        mime_type=row["mime_type"],
        data=bytes(row["data"]) if include_data else b"",
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def insert_attachment(db: Database, attachment: Attachment) -> Attachment:
    """Persist a new attachment. Sets created_at on the object."""
    now = _now()
    attachment.created_at = datetime.fromisoformat(now)
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO attachments (id, node_id, filename, mime_type, data, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                attachment.id, attachment.node_id, attachment.filename,
                attachment.mime_type, attachment.data, now,
            ),
        )
    return attachment


def get_attachments_for_node(
    db: Database,
    node_id: str,
    include_data: bool = False,
) -> list[Attachment]:
    """
    Return all attachments for a node.

    Set include_data=False (the default) when building thumbnail lists —
    it avoids loading potentially large BLOBs just to show filenames.
    Set include_data=True when the user clicks to view an attachment.
    """
    if include_data:
        rows = db.conn.execute(
            "SELECT * FROM attachments WHERE node_id = ? ORDER BY created_at",
            (node_id,),
        ).fetchall()
    else:
        rows = db.conn.execute(
            "SELECT id, node_id, filename, mime_type, created_at, NULL as data"
            " FROM attachments WHERE node_id = ? ORDER BY created_at",
            (node_id,),
        ).fetchall()
    return [_row_to_attachment(r, include_data=include_data) for r in rows]


def get_attachment(db: Database, attachment_id: str) -> Optional[Attachment]:
    """Return a single attachment with full data (for viewing)."""
    row = db.conn.execute(
        "SELECT * FROM attachments WHERE id = ?", (attachment_id,)
    ).fetchone()
    return _row_to_attachment(row, include_data=True) if row else None


def delete_attachment(db: Database, attachment_id: str) -> None:
    """Permanently delete a single attachment by ID. The BLOB data is not recoverable."""
    with db.conn:
        db.conn.execute(
            "DELETE FROM attachments WHERE id = ?", (attachment_id,)
        )
