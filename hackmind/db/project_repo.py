"""
CRUD operations for projects.
"""

from datetime import datetime, timezone
from typing import Optional

from hackmind.db.database import Database
from hackmind.models.types import Project


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_project(row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        target_name=row["target_name"],
        template_id=row["template_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def create_project(db: Database, project: Project) -> Project:
    """Persist a new project. Sets created_at and updated_at on the object."""
    now = _now()
    project.created_at = datetime.fromisoformat(now)
    project.updated_at = datetime.fromisoformat(now)
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO projects (id, name, target_name, template_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project.id, project.name, project.target_name,
             project.template_id, now, now),
        )
    return project


def list_projects(db: Database) -> list[Project]:
    """Return all projects, newest first."""
    rows = db.conn.execute(
        "SELECT * FROM projects ORDER BY created_at DESC"
    ).fetchall()
    return [_row_to_project(r) for r in rows]


def get_project(db: Database, project_id: str) -> Optional[Project]:
    """Return the project with the given ID, or None if not found."""
    row = db.conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    return _row_to_project(row) if row else None


def update_project(db: Database, project: Project) -> None:
    """Persist changes to name or target_name. Updates updated_at."""
    now = _now()
    project.updated_at = datetime.fromisoformat(now)
    with db.conn:
        db.conn.execute(
            """
            UPDATE projects
               SET name = ?, target_name = ?, updated_at = ?
             WHERE id = ?
            """,
            (project.name, project.target_name, now, project.id),
        )


def delete_project(db: Database, project_id: str) -> None:
    """
    Delete a project and all its nodes (cascade handles children).
    This is permanent — callers should confirm with the user first.
    """
    with db.conn:
        db.conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
