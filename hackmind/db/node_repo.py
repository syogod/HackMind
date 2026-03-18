"""
CRUD operations for nodes, question answers, and notes.

Notes live in their own table but are logically part of a node, so they
are managed here rather than a separate repo.

Soft-deletion
-------------
When a user changes their answer to a question node, the children spawned
by the previous answer are soft-deleted (soft_deleted = 1) rather than
removed. This lets the user revert to the original answer and recover all
their notes and statuses.

Soft-deleted nodes are excluded from normal queries. They are restored as
a unit when the original answer is re-selected.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from hackmind.db.database import Database
from hackmind.models.types import Node, NodeStatus, NodeType, Note, QuestionAnswer


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_node(row) -> Node:
    return Node(
        id=row["id"],
        project_id=row["project_id"],
        parent_id=row["parent_id"],
        template_node_id=row["template_node_id"],
        template_id=row["template_id"],
        type=NodeType(row["type"]),
        title=row["title"],
        content=row["content"],
        status=NodeStatus(row["status"]),
        is_finding=bool(row["is_finding"]),
        soft_deleted=bool(row["soft_deleted"]),
        position=row["position"],
        scope_tags=json.loads(row["scope_tags"] or "[]"),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------

def insert_node(db: Database, node: Node) -> Node:
    """Insert a node. Sets created_at on the object."""
    now = _now()
    node.created_at = datetime.fromisoformat(now)
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO nodes
                (id, project_id, parent_id, template_node_id, template_id,
                 type, title, content, status, is_finding, soft_deleted,
                 position, scope_tags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node.id, node.project_id, node.parent_id,
                node.template_node_id, node.template_id,
                node.type.value, node.title,
                node.content, node.status.value,
                int(node.is_finding), int(node.soft_deleted),
                node.position, json.dumps(node.scope_tags), now,
            ),
        )
    return node


def get_node(db: Database, node_id: str) -> Optional[Node]:
    """Return the node with the given ID, or None if not found (including soft-deleted nodes)."""
    row = db.conn.execute(
        "SELECT * FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    return _row_to_node(row) if row else None


def get_children(
    db: Database,
    parent_id: str,
    include_soft_deleted: bool = False,
) -> list[Node]:
    """Return direct children of a node, ordered by position."""
    if include_soft_deleted:
        rows = db.conn.execute(
            "SELECT * FROM nodes WHERE parent_id = ? ORDER BY position",
            (parent_id,),
        ).fetchall()
    else:
        rows = db.conn.execute(
            "SELECT * FROM nodes WHERE parent_id = ? AND soft_deleted = 0 ORDER BY position",
            (parent_id,),
        ).fetchall()
    return [_row_to_node(r) for r in rows]


def get_project_nodes(
    db: Database,
    project_id: str,
    include_soft_deleted: bool = False,
) -> list[Node]:
    """
    Return all nodes for a project as a flat list (ordered by position).
    The caller is responsible for building the tree structure from parent_id links.
    Soft-deleted nodes are excluded by default.
    """
    if include_soft_deleted:
        rows = db.conn.execute(
            "SELECT * FROM nodes WHERE project_id = ? ORDER BY position",
            (project_id,),
        ).fetchall()
    else:
        rows = db.conn.execute(
            "SELECT * FROM nodes WHERE project_id = ? AND soft_deleted = 0 ORDER BY position",
            (project_id,),
        ).fetchall()
    return [_row_to_node(r) for r in rows]


def get_project_progress(
    db: Database,
    project_id: str,
    oos_tags: set[str] | None = None,
) -> dict[str, int]:
    """
    Return completion counts for the project progress bar.

    Counts checklist and question nodes only (assets and info sections are
    containers, not individual work items).

    Rules:
    - Checklist COMPLETE or VULNERABLE  → counts as complete
    - Checklist NOT_APPLICABLE          → excluded from both total and complete
    - Question with a recorded answer   → counts as complete
    - Question with no answer           → counts as incomplete
    - Nodes whose scope_tags intersect oos_tags are excluded entirely so
      hidden OOS items don't drag down the percentage.

    Returns {"total": int, "complete": int}.
    """
    rows = db.conn.execute(
        """
        SELECT id, type, status, scope_tags
          FROM nodes
         WHERE project_id = ? AND soft_deleted = 0
           AND type IN ('checklist', 'question')
        """,
        (project_id,),
    ).fetchall()

    answered: set[str] = set(
        r["node_id"]
        for r in db.conn.execute(
            """
            SELECT qa.node_id
              FROM question_answers qa
              JOIN nodes n ON qa.node_id = n.id
             WHERE n.project_id = ? AND n.soft_deleted = 0
            """,
            (project_id,),
        ).fetchall()
    )

    total = 0
    complete = 0

    for row in rows:
        # Skip nodes whose scope_tags are entirely out of scope.
        if oos_tags:
            node_tags = json.loads(row["scope_tags"] or "[]")
            if oos_tags.intersection(node_tags):
                continue

        if row["type"] == "checklist":
            if row["status"] == "not_applicable":
                continue  # intentionally excluded
            total += 1
            if row["status"] in ("complete", "vulnerable"):
                complete += 1
        else:  # question
            total += 1
            if row["id"] in answered:
                complete += 1

    return {"total": total, "complete": complete}


def get_findings(db: Database, project_id: str) -> list[Node]:
    """Return all checklist nodes marked as findings for a project."""
    rows = db.conn.execute(
        """
        SELECT * FROM nodes
         WHERE project_id = ?
           AND is_finding = 1
           AND soft_deleted = 0
         ORDER BY created_at
        """,
        (project_id,),
    ).fetchall()
    return [_row_to_node(r) for r in rows]


# ---------------------------------------------------------------------------
# Status and finding flag
# ---------------------------------------------------------------------------

def set_status(db: Database, node_id: str, status: NodeStatus) -> None:
    with db.conn:
        db.conn.execute(
            "UPDATE nodes SET status = ? WHERE id = ?",
            (status.value, node_id),
        )


def set_finding(db: Database, node_id: str, is_finding: bool) -> None:
    with db.conn:
        db.conn.execute(
            "UPDATE nodes SET is_finding = ? WHERE id = ?",
            (int(is_finding), node_id),
        )


# ---------------------------------------------------------------------------
# Soft-delete / restore subtrees
# ---------------------------------------------------------------------------

def soft_delete_subtree(db: Database, root_node_id: str) -> None:
    """
    Mark a node and all its descendants as soft_deleted = 1.
    Uses a recursive CTE to find all descendants in one query.
    """
    with db.conn:
        db.conn.execute(
            """
            WITH RECURSIVE subtree(id) AS (
                SELECT id FROM nodes WHERE id = ?
                UNION ALL
                SELECT n.id FROM nodes n
                  JOIN subtree s ON n.parent_id = s.id
            )
            UPDATE nodes SET soft_deleted = 1
             WHERE id IN (SELECT id FROM subtree)
            """,
            (root_node_id,),
        )


def delete_node_subtree(db: Database, root_node_id: str) -> None:
    """
    Permanently delete a node and all its descendants (including soft-deleted ones).
    Related rows in question_answers, notes, and attachments are removed via
    the ON DELETE CASCADE foreign keys defined in the schema.
    """
    with db.conn:
        db.conn.execute(
            """
            WITH RECURSIVE subtree(id) AS (
                SELECT id FROM nodes WHERE id = ?
                UNION ALL
                SELECT n.id FROM nodes n
                  JOIN subtree s ON n.parent_id = s.id
            )
            DELETE FROM nodes WHERE id IN (SELECT id FROM subtree)
            """,
            (root_node_id,),
        )


def restore_subtree(db: Database, root_node_id: str) -> None:
    """
    Restore a previously soft-deleted node and all its descendants.
    Called when a user reverts a question to its original answer.
    """
    with db.conn:
        db.conn.execute(
            """
            WITH RECURSIVE subtree(id) AS (
                SELECT id FROM nodes WHERE id = ?
                UNION ALL
                SELECT n.id FROM nodes n
                  JOIN subtree s ON n.parent_id = s.id
            )
            UPDATE nodes SET soft_deleted = 0
             WHERE id IN (SELECT id FROM subtree)
            """,
            (root_node_id,),
        )


# ---------------------------------------------------------------------------
# Question answers
# ---------------------------------------------------------------------------

def clear_answer(db: Database, node_id: str) -> None:
    """Remove the answer record for a question node."""
    with db.conn:
        db.conn.execute(
            "DELETE FROM question_answers WHERE node_id = ?", (node_id,)
        )


def set_answer(db: Database, node_id: str, option_key: str) -> None:
    """
    Record or replace the answer to a question node.
    Uses UPSERT so re-answering is idempotent on the DB level.
    The engine layer is responsible for soft-deleting / restoring subtrees.
    """
    now = _now()
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO question_answers (id, node_id, option_key, answered_at)
            VALUES (lower(hex(randomblob(16))), ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE
               SET option_key = excluded.option_key,
                   answered_at = excluded.answered_at
            """,
            (node_id, option_key, now),
        )


def get_answer(db: Database, node_id: str) -> Optional[QuestionAnswer]:
    row = db.conn.execute(
        "SELECT * FROM question_answers WHERE node_id = ?", (node_id,)
    ).fetchone()
    if row is None:
        return None
    return QuestionAnswer(
        id=row["id"],
        node_id=row["node_id"],
        option_key=row["option_key"],
        answered_at=datetime.fromisoformat(row["answered_at"]),
    )


def get_answers_for_project(db: Database, project_id: str) -> dict[str, str]:
    """
    Return a mapping of {node_id: option_key} for all answered question nodes
    in a project. Useful for loading full project state in one query.
    """
    rows = db.conn.execute(
        """
        SELECT qa.node_id, qa.option_key
          FROM question_answers qa
          JOIN nodes n ON qa.node_id = n.id
         WHERE n.project_id = ?
        """,
        (project_id,),
    ).fetchall()
    return {r["node_id"]: r["option_key"] for r in rows}


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def get_note(db: Database, node_id: str) -> Note:
    """
    Return the note for a node. Creates an empty note row if none exists.
    Always returns a Note object — callers don't need to handle None.
    """
    row = db.conn.execute(
        "SELECT * FROM notes WHERE node_id = ?", (node_id,)
    ).fetchone()
    if row:
        return Note(
            id=row["id"],
            node_id=row["node_id"],
            content=row["content"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
    # Create an empty note on first access
    note = Note(node_id=node_id, content="")
    _create_note(db, note)
    return note


def save_note(db: Database, node_id: str, content: str) -> None:
    """Upsert note content for a node."""
    now = _now()
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO notes (id, node_id, content, updated_at)
            VALUES (lower(hex(randomblob(16))), ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE
               SET content = excluded.content,
                   updated_at = excluded.updated_at
            """,
            (node_id, content, now),
        )


def _create_note(db: Database, note: Note) -> None:
    now = _now()
    note.updated_at = datetime.fromisoformat(now)
    with db.conn:
        db.conn.execute(
            "INSERT INTO notes (id, node_id, content, updated_at) VALUES (?, ?, ?, ?)",
            (note.id, note.node_id, note.content, now),
        )
