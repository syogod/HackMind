"""
CRUD operations for templates.

Templates are stored as their raw YAML source in the database so they can
be re-hydrated or exported later without any data loss. The in-memory
Template object is always produced by the engine/template_loader.
"""

from datetime import datetime, timezone
from typing import Optional

from hackmind.db.database import Database
from hackmind.models.types import Template


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def store_template(db: Database, template: Template, raw_yaml: str) -> None:
    """
    Persist a template and its raw YAML source.
    Replaces any existing template with the same ID.
    """
    now = _now()
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO templates (id, name, version, source_file, data, imported_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE
               SET name        = excluded.name,
                   version     = excluded.version,
                   source_file = excluded.source_file,
                   data        = excluded.data,
                   imported_at = excluded.imported_at
            """,
            (
                template.id, template.name, template.version,
                template.source_file, raw_yaml, now,
            ),
        )


def list_templates(db: Database) -> list[dict]:
    """
    Return lightweight template metadata (no raw YAML) for display in a list.
    Each entry: {id, name, version, source_file, imported_at}
    """
    rows = db.conn.execute(
        "SELECT id, name, version, source_file, imported_at FROM templates ORDER BY imported_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_template_raw(db: Database, template_id: str) -> Optional[str]:
    """Return the raw YAML source for a template, or None if not found."""
    row = db.conn.execute(
        "SELECT data FROM templates WHERE id = ?", (template_id,)
    ).fetchone()
    return row["data"] if row else None


def delete_template(db: Database, template_id: str) -> None:
    """
    Permanently delete a template from the library.
    Does NOT affect existing project nodes — they retain their template_id
    reference, but future calls to get_template_raw will return None for it.
    """
    with db.conn:
        db.conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
