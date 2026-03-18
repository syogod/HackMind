"""
Tests for db/project_repo.py
"""

import time

from hackmind.db.database import Database
from hackmind.db.project_repo import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    update_project,
)
from hackmind.models.types import Project


def _make_project(**kwargs) -> Project:
    defaults = dict(name="Acme Corp", target_name="acme.com", template_id="tpl-1")
    defaults.update(kwargs)
    return Project(**defaults)


def test_create_project_persists(db: Database) -> None:
    p = create_project(db, _make_project())
    row = db.conn.execute("SELECT * FROM projects WHERE id = ?", (p.id,)).fetchone()
    assert row is not None
    assert row["name"] == "Acme Corp"


def test_create_project_sets_timestamps(db: Database) -> None:
    p = create_project(db, _make_project())
    assert p.created_at is not None
    assert p.updated_at is not None


def test_get_project_returns_correct_project(db: Database) -> None:
    p = create_project(db, _make_project(name="Alpha"))
    fetched = get_project(db, p.id)
    assert fetched is not None
    assert fetched.id == p.id
    assert fetched.name == "Alpha"
    assert fetched.target_name == "acme.com"


def test_get_project_returns_none_for_missing_id(db: Database) -> None:
    assert get_project(db, "nonexistent-id") is None


def test_list_projects_returns_newest_first(db: Database) -> None:
    p1 = create_project(db, _make_project(name="First"))
    time.sleep(0.01)  # ensure distinct timestamps
    p2 = create_project(db, _make_project(name="Second"))
    projects = list_projects(db)
    assert projects[0].name == "Second"
    assert projects[1].name == "First"


def test_list_projects_empty(db: Database) -> None:
    assert list_projects(db) == []


def test_update_project_persists_changes(db: Database) -> None:
    p = create_project(db, _make_project(name="Old Name"))
    p.name = "New Name"
    p.target_name = "new.com"
    update_project(db, p)
    fetched = get_project(db, p.id)
    assert fetched.name == "New Name"
    assert fetched.target_name == "new.com"


def test_update_project_bumps_updated_at(db: Database) -> None:
    p = create_project(db, _make_project())
    original_updated_at = p.updated_at
    time.sleep(0.01)
    p.name = "Changed"
    update_project(db, p)
    fetched = get_project(db, p.id)
    assert fetched.updated_at > original_updated_at


def test_delete_project_removes_row(db: Database) -> None:
    p = create_project(db, _make_project())
    delete_project(db, p.id)
    assert get_project(db, p.id) is None


def test_delete_project_not_in_list(db: Database) -> None:
    p = create_project(db, _make_project())
    delete_project(db, p.id)
    assert all(proj.id != p.id for proj in list_projects(db))
