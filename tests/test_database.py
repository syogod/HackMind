"""
Tests for database.py — schema creation and migration machinery.
"""

from pathlib import Path

import pytest

from hackmind.db.database import Database, SCHEMA_VERSION


def test_fresh_db_creates_schema(tmp_path: Path) -> None:
    db = Database.open_at(tmp_path / "fresh.db")
    # All expected tables should exist
    tables = {
        row[0]
        for row in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    expected = {
        "schema_version", "projects", "templates",
        "nodes", "question_answers", "notes", "attachments",
    }
    assert expected.issubset(tables)
    db.close()


def test_fresh_db_sets_schema_version(tmp_path: Path) -> None:
    db = Database.open_at(tmp_path / "fresh.db")
    row = db.conn.execute("SELECT version FROM schema_version").fetchone()
    assert row is not None
    assert row["version"] == SCHEMA_VERSION
    db.close()


def test_foreign_keys_are_enabled(tmp_path: Path) -> None:
    db = Database.open_at(tmp_path / "fk.db")
    result = db.conn.execute("PRAGMA foreign_keys").fetchone()
    assert result[0] == 1
    db.close()


def test_existing_db_at_current_version_opens_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "existing.db"
    db1 = Database.open_at(path)
    db1.close()
    # Opening the same path again should not raise
    db2 = Database.open_at(path)
    db2.close()


def test_context_manager_closes_connection(tmp_path: Path) -> None:
    path = tmp_path / "ctx.db"
    with Database.open_at(path) as db:
        assert db.conn is not None
    # After exit, executing should raise (connection closed)
    with pytest.raises(Exception):
        db.conn.execute("SELECT 1")
