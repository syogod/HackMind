"""
CRUD operations for per-project scope settings.

Out-of-scope tags are stored as individual rows in project_scope_tags.
Any node whose scope_tags list intersects the project's OOS tags is hidden
from the tree view.
"""

import json

from hackmind.db.database import Database


def get_oos_tags(db: Database, project_id: str) -> set[str]:
    """Return the set of out-of-scope tag strings for a project."""
    rows = db.conn.execute(
        "SELECT tag FROM project_scope_tags WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    return {r["tag"] for r in rows}


def set_oos_tags(db: Database, project_id: str, tags: set[str]) -> None:
    """Replace the full set of out-of-scope tags for a project."""
    with db.conn:
        db.conn.execute(
            "DELETE FROM project_scope_tags WHERE project_id = ?",
            (project_id,),
        )
        for tag in tags:
            db.conn.execute(
                "INSERT INTO project_scope_tags (project_id, tag) VALUES (?, ?)",
                (project_id, tag),
            )


def get_all_project_tags(db: Database, project_id: str) -> set[str]:
    """Return every unique scope tag present on any node in the project."""
    rows = db.conn.execute(
        "SELECT scope_tags FROM nodes WHERE project_id = ? AND soft_deleted = 0",
        (project_id,),
    ).fetchall()
    tags: set[str] = set()
    for row in rows:
        raw = row["scope_tags"]
        if raw and raw != "[]":
            tags.update(json.loads(raw))
    return tags
