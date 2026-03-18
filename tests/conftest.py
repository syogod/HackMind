"""
Shared pytest fixtures for HackMind tests.
"""

import pytest
from pathlib import Path

from hackmind.db.database import Database
from hackmind.models.types import (
    Attachment,
    Node,
    NodeStatus,
    NodeType,
    Project,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """A fresh in-memory-like database for each test."""
    database = Database.open_at(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def project(db: Database) -> Project:
    """A persisted project for use in node/attachment tests."""
    from hackmind.db.project_repo import create_project
    p = Project(name="Test Target", target_name="example.com", template_id="tpl-1")
    return create_project(db, p)


@pytest.fixture
def root_node(db: Database, project: Project) -> Node:
    """A persisted root question node."""
    from hackmind.db.node_repo import insert_node
    node = Node(
        project_id=project.id,
        type=NodeType.QUESTION,
        title="What type of target?",
        position=0,
    )
    return insert_node(db, node)


def make_checklist_node(
    db: Database,
    project_id: str,
    parent_id: str | None = None,
    title: str = "Test checklist",
    position: int = 0,
) -> Node:
    from hackmind.db.node_repo import insert_node
    node = Node(
        project_id=project_id,
        parent_id=parent_id,
        type=NodeType.CHECKLIST,
        title=title,
        position=position,
    )
    return insert_node(db, node)
