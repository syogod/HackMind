"""
Tests for db/attachment_repo.py
"""

from hackmind.db.attachment_repo import (
    delete_attachment,
    get_attachment,
    get_attachments_for_node,
    insert_attachment,
)
from hackmind.db.database import Database
from hackmind.models.types import Attachment, Node, Project

PNG_1PX = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd4n\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_attachment(node_id: str, filename="screenshot.png") -> Attachment:
    return Attachment(
        node_id=node_id,
        filename=filename,
        mime_type="image/png",
        data=PNG_1PX,
    )


# ---------------------------------------------------------------------------
# Insert
# ---------------------------------------------------------------------------

def test_insert_attachment_persists(
    db: Database, project: Project, root_node: Node
) -> None:
    a = insert_attachment(db, _make_attachment(root_node.id))
    row = db.conn.execute(
        "SELECT * FROM attachments WHERE id = ?", (a.id,)
    ).fetchone()
    assert row is not None
    assert row["filename"] == "screenshot.png"


def test_insert_attachment_sets_created_at(
    db: Database, root_node: Node
) -> None:
    a = insert_attachment(db, _make_attachment(root_node.id))
    assert a.created_at is not None


def test_insert_attachment_stores_data(
    db: Database, root_node: Node
) -> None:
    a = insert_attachment(db, _make_attachment(root_node.id))
    fetched = get_attachment(db, a.id)
    assert fetched.data == PNG_1PX


# ---------------------------------------------------------------------------
# Get list (without data)
# ---------------------------------------------------------------------------

def test_get_attachments_for_node_returns_all(
    db: Database, root_node: Node
) -> None:
    insert_attachment(db, _make_attachment(root_node.id, filename="a.png"))
    insert_attachment(db, _make_attachment(root_node.id, filename="b.png"))
    attachments = get_attachments_for_node(db, root_node.id)
    assert len(attachments) == 2
    filenames = {a.filename for a in attachments}
    assert filenames == {"a.png", "b.png"}


def test_get_attachments_for_node_excludes_data_by_default(
    db: Database, root_node: Node
) -> None:
    insert_attachment(db, _make_attachment(root_node.id))
    attachments = get_attachments_for_node(db, root_node.id, include_data=False)
    assert attachments[0].data == b""


def test_get_attachments_for_node_includes_data_when_requested(
    db: Database, root_node: Node
) -> None:
    insert_attachment(db, _make_attachment(root_node.id))
    attachments = get_attachments_for_node(db, root_node.id, include_data=True)
    assert attachments[0].data == PNG_1PX


def test_get_attachments_empty_for_node_with_no_attachments(
    db: Database, root_node: Node
) -> None:
    assert get_attachments_for_node(db, root_node.id) == []


def test_get_attachments_only_returns_for_given_node(
    db: Database, project: Project, root_node: Node
) -> None:
    from hackmind.db.node_repo import insert_node
    from hackmind.models.types import NodeType
    other_node = insert_node(db, __import__('hackmind.models.types', fromlist=['Node']).Node(
        project_id=project.id, type=NodeType.CHECKLIST, title="Other"
    ))
    insert_attachment(db, _make_attachment(root_node.id, filename="mine.png"))
    insert_attachment(db, _make_attachment(other_node.id, filename="theirs.png"))

    attachments = get_attachments_for_node(db, root_node.id)
    assert len(attachments) == 1
    assert attachments[0].filename == "mine.png"


# ---------------------------------------------------------------------------
# Get single
# ---------------------------------------------------------------------------

def test_get_attachment_returns_full_data(
    db: Database, root_node: Node
) -> None:
    a = insert_attachment(db, _make_attachment(root_node.id))
    fetched = get_attachment(db, a.id)
    assert fetched is not None
    assert fetched.data == PNG_1PX
    assert fetched.filename == "screenshot.png"


def test_get_attachment_returns_none_for_missing(db: Database) -> None:
    assert get_attachment(db, "nonexistent") is None


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_attachment_removes_row(
    db: Database, root_node: Node
) -> None:
    a = insert_attachment(db, _make_attachment(root_node.id))
    delete_attachment(db, a.id)
    assert get_attachment(db, a.id) is None


def test_delete_attachment_does_not_affect_others(
    db: Database, root_node: Node
) -> None:
    a1 = insert_attachment(db, _make_attachment(root_node.id, filename="keep.png"))
    a2 = insert_attachment(db, _make_attachment(root_node.id, filename="delete.png"))
    delete_attachment(db, a2.id)
    assert get_attachment(db, a1.id) is not None
