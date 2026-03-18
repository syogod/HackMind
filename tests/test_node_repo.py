"""
Tests for db/node_repo.py

Covers: insert, fetch, status, findings, soft-delete/restore,
        question answers, and notes.
"""

from hackmind.db.database import Database
from hackmind.db.node_repo import (
    get_answer,
    get_answers_for_project,
    get_children,
    get_findings,
    get_node,
    get_note,
    get_project_nodes,
    insert_node,
    restore_subtree,
    save_note,
    set_answer,
    set_finding,
    set_status,
    soft_delete_subtree,
)
from hackmind.models.types import Node, NodeStatus, NodeType, Project
from tests.conftest import make_checklist_node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _question(project_id: str, parent_id=None, title="Q?", position=0) -> Node:
    return Node(
        project_id=project_id,
        parent_id=parent_id,
        type=NodeType.QUESTION,
        title=title,
        position=position,
    )


def _checklist(project_id: str, parent_id=None, title="Check", position=0) -> Node:
    return Node(
        project_id=project_id,
        parent_id=parent_id,
        type=NodeType.CHECKLIST,
        title=title,
        position=position,
    )


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------

def test_insert_and_get_node(db: Database, project: Project) -> None:
    node = insert_node(db, _question(project.id, title="Root question"))
    fetched = get_node(db, node.id)
    assert fetched is not None
    assert fetched.title == "Root question"
    assert fetched.type == NodeType.QUESTION


def test_get_node_returns_none_for_missing(db: Database) -> None:
    assert get_node(db, "does-not-exist") is None


def test_insert_node_sets_created_at(db: Database, project: Project) -> None:
    node = insert_node(db, _question(project.id))
    assert node.created_at is not None


def test_get_children_returns_direct_children_only(
    db: Database, project: Project, root_node: Node
) -> None:
    child1 = insert_node(db, _checklist(project.id, parent_id=root_node.id, title="C1"))
    child2 = insert_node(db, _checklist(project.id, parent_id=root_node.id, title="C2"))
    # grandchild — should NOT appear in root's direct children
    insert_node(db, _checklist(project.id, parent_id=child1.id, title="Grandchild"))

    children = get_children(db, root_node.id)
    ids = {n.id for n in children}
    assert child1.id in ids
    assert child2.id in ids
    assert len(children) == 2


def test_get_children_ordered_by_position(
    db: Database, project: Project, root_node: Node
) -> None:
    insert_node(db, _checklist(project.id, parent_id=root_node.id, title="B", position=1))
    insert_node(db, _checklist(project.id, parent_id=root_node.id, title="A", position=0))
    children = get_children(db, root_node.id)
    assert children[0].title == "A"
    assert children[1].title == "B"


def test_get_project_nodes_excludes_other_projects(
    db: Database, project: Project
) -> None:
    from hackmind.db.project_repo import create_project
    other = create_project(db, Project(name="Other", target_name="other.com", template_id="t"))
    insert_node(db, _checklist(project.id, title="Mine"))
    insert_node(db, _checklist(other.id, title="Not mine"))

    nodes = get_project_nodes(db, project.id)
    assert all(n.project_id == project.id for n in nodes)
    assert len(nodes) == 1


# ---------------------------------------------------------------------------
# Status and findings
# ---------------------------------------------------------------------------

def test_set_status_persists(db: Database, project: Project) -> None:
    node = insert_node(db, _checklist(project.id))
    set_status(db, node.id, NodeStatus.VULNERABLE)
    fetched = get_node(db, node.id)
    assert fetched.status == NodeStatus.VULNERABLE


def test_set_finding_persists(db: Database, project: Project) -> None:
    node = insert_node(db, _checklist(project.id))
    assert not node.is_finding
    set_finding(db, node.id, True)
    fetched = get_node(db, node.id)
    assert fetched.is_finding is True


def test_get_findings_returns_only_flagged_nodes(
    db: Database, project: Project
) -> None:
    finding = insert_node(db, _checklist(project.id, title="A finding"))
    _normal = insert_node(db, _checklist(project.id, title="Normal"))
    set_finding(db, finding.id, True)

    findings = get_findings(db, project.id)
    assert len(findings) == 1
    assert findings[0].id == finding.id


def test_get_findings_excludes_soft_deleted(
    db: Database, project: Project
) -> None:
    node = insert_node(db, _checklist(project.id))
    set_finding(db, node.id, True)
    soft_delete_subtree(db, node.id)

    assert get_findings(db, project.id) == []


# ---------------------------------------------------------------------------
# Soft-delete and restore
# ---------------------------------------------------------------------------

def _build_subtree(db: Database, project_id: str) -> tuple[Node, Node, Node]:
    """Returns (parent, child, grandchild)."""
    parent = insert_node(db, _checklist(project_id, title="Parent"))
    child = insert_node(db, _checklist(project_id, parent_id=parent.id, title="Child"))
    grandchild = insert_node(db, _checklist(project_id, parent_id=child.id, title="Grandchild"))
    return parent, child, grandchild


def test_soft_delete_marks_all_descendants(db: Database, project: Project) -> None:
    parent, child, grandchild = _build_subtree(db, project.id)
    soft_delete_subtree(db, parent.id)

    for node_id in (parent.id, child.id, grandchild.id):
        fetched = get_node(db, node_id)
        assert fetched.soft_deleted is True


def test_soft_deleted_nodes_excluded_from_get_children(
    db: Database, project: Project, root_node: Node
) -> None:
    child = insert_node(db, _checklist(project.id, parent_id=root_node.id))
    soft_delete_subtree(db, child.id)

    children = get_children(db, root_node.id)
    assert len(children) == 0


def test_soft_deleted_nodes_visible_with_flag(
    db: Database, project: Project, root_node: Node
) -> None:
    child = insert_node(db, _checklist(project.id, parent_id=root_node.id))
    soft_delete_subtree(db, child.id)

    children = get_children(db, root_node.id, include_soft_deleted=True)
    assert len(children) == 1


def test_restore_subtree_undeletes_all_descendants(
    db: Database, project: Project
) -> None:
    parent, child, grandchild = _build_subtree(db, project.id)
    soft_delete_subtree(db, parent.id)
    restore_subtree(db, parent.id)

    for node_id in (parent.id, child.id, grandchild.id):
        fetched = get_node(db, node_id)
        assert fetched.soft_deleted is False


def test_soft_delete_only_affects_target_subtree(
    db: Database, project: Project, root_node: Node
) -> None:
    branch_a = insert_node(db, _checklist(project.id, parent_id=root_node.id, title="A"))
    branch_b = insert_node(db, _checklist(project.id, parent_id=root_node.id, title="B"))
    soft_delete_subtree(db, branch_a.id)

    assert get_node(db, branch_b.id).soft_deleted is False


# ---------------------------------------------------------------------------
# Question answers
# ---------------------------------------------------------------------------

def test_set_and_get_answer(db: Database, project: Project, root_node: Node) -> None:
    set_answer(db, root_node.id, "webapp")
    answer = get_answer(db, root_node.id)
    assert answer is not None
    assert answer.option_key == "webapp"
    assert answer.node_id == root_node.id


def test_get_answer_returns_none_when_unanswered(
    db: Database, root_node: Node
) -> None:
    assert get_answer(db, root_node.id) is None


def test_set_answer_replaces_previous_answer(
    db: Database, root_node: Node
) -> None:
    set_answer(db, root_node.id, "webapp")
    set_answer(db, root_node.id, "api")
    answer = get_answer(db, root_node.id)
    assert answer.option_key == "api"


def test_get_answers_for_project_returns_all(
    db: Database, project: Project, root_node: Node
) -> None:
    q2 = insert_node(db, _question(project.id, title="Another Q"))
    set_answer(db, root_node.id, "webapp")
    set_answer(db, q2.id, "yes")

    mapping = get_answers_for_project(db, project.id)
    assert mapping[root_node.id] == "webapp"
    assert mapping[q2.id] == "yes"


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def test_get_note_auto_creates_empty_note(
    db: Database, project: Project, root_node: Node
) -> None:
    note = get_note(db, root_node.id)
    assert note is not None
    assert note.content == ""
    assert note.node_id == root_node.id


def test_save_note_persists_content(
    db: Database, project: Project, root_node: Node
) -> None:
    save_note(db, root_node.id, "This is a note.")
    note = get_note(db, root_node.id)
    assert note.content == "This is a note."


def test_save_note_overwrites_previous_content(
    db: Database, root_node: Node
) -> None:
    save_note(db, root_node.id, "First draft")
    save_note(db, root_node.id, "Second draft")
    note = get_note(db, root_node.id)
    assert note.content == "Second draft"


def test_get_note_idempotent_for_existing_note(
    db: Database, root_node: Node
) -> None:
    get_note(db, root_node.id)  # creates row
    get_note(db, root_node.id)  # should not raise (no duplicate insert)
    rows = db.conn.execute(
        "SELECT COUNT(*) FROM notes WHERE node_id = ?", (root_node.id,)
    ).fetchone()[0]
    assert rows == 1
