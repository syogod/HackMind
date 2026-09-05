"""
CRUD operations for node attachments.

Attachments are stored on the file system in a hidden .attachments/ directory,
decoupled from the SQLite database to prevent bloat and I/O lag.
"""

import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from hackmind.db.database import Database
from hackmind.models.types import Attachment


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_attachment(db: Database, row, include_data: bool = True) -> Attachment:
    rel_path = row["relative_path"]
    data = b""
    if include_data and rel_path:
        # Resolve path relative to the database location
        full_path = db.attachments_dir / rel_path
        if full_path.exists():
            data = full_path.read_bytes()

    return Attachment(
        id=row["id"],
        node_id=row["node_id"],
        filename=row["filename"],
        mime_type=row["mime_type"],
        data=data,
        relative_path=rel_path,
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def insert_attachment(db: Database, attachment: Attachment) -> Attachment:
    """
    Persist a new attachment. 
    Writes raw bytes to the file system and saves the relative path in the DB.
    """
    now = _now()
    attachment.created_at = datetime.fromisoformat(now)

    if attachment.data is None:
        raise ValueError("Attachment data is missing.")

    # 1. Resolve storage directory
    # Based on instructions: ~/HackMind Projects/<project_id>/.attachments/
    # But since we use a single DB, we'll store them in a flat structure or 
    # subfolders within the global .attachments/ directory.
    # We'll use the project_id to group them if we can find it.
    # For now, we'll use the global attachments_dir and prefix with UUID for uniqueness.
    
    # We need the project_id to follow the requested structure exactly.
    # Let's find the project_id for this node.
    row = db.conn.execute("SELECT project_id FROM nodes WHERE id = ?", (attachment.node_id,)).fetchone()
    project_id = row["project_id"] if row else "unknown"

    project_attachments_dir = db.attachments_dir / project_id
    project_attachments_dir.mkdir(parents=True, exist_ok=True)

    # 2. Generate unique filename
    unique_name = f"{uuid.uuid4()}_{attachment.filename}"
    full_path = project_attachments_dir / unique_name
    
    # 3. Write raw bytes
    full_path.write_bytes(attachment.data)
    
    # 4. Save relative path (relative to the global attachments_dir)
    attachment.relative_path = str(Path(project_id) / unique_name)

    with db.conn:
        db.conn.execute(
            """
            INSERT INTO attachments (id, node_id, filename, mime_type, relative_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                attachment.id, attachment.node_id, attachment.filename,
                attachment.mime_type, attachment.relative_path, now,
            ),
        )
    return attachment


def get_attachments_for_node(
    db: Database,
    node_id: str,
    include_data: bool = False,
) -> list[Attachment]:
    """Return all attachments for a node."""
    rows = db.conn.execute(
        "SELECT * FROM attachments WHERE node_id = ? ORDER BY created_at",
        (node_id,),
    ).fetchall()
    return [_row_to_attachment(db, r, include_data=include_data) for r in rows]


def get_attachment(db: Database, attachment_id: str) -> Optional[Attachment]:
    """Return a single attachment with full data."""
    row = db.conn.execute(
        "SELECT * FROM attachments WHERE id = ?", (attachment_id,)
    ).fetchone()
    return _row_to_attachment(db, row, include_data=True) if row else None


def delete_attachment(db: Database, attachment_id: str) -> None:
    """Permanently delete an attachment from DB and disk."""
    attachment = get_attachment(db, attachment_id)
    if attachment and attachment.relative_path:
        full_path = db.attachments_dir / attachment.relative_path
        if full_path.exists():
            full_path.unlink()

    with db.conn:
        db.conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
