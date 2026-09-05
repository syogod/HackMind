"""
Database connection and schema management for HackMind.
Supports SQLCipher encryption.

All data is stored in a single SQLite file:
    ~/HackMind Projects/hackmind.db

This makes backup trivial (copy one file) and keeps project listing simple.
Tests use Database.open_at() with a temporary path to avoid touching user data.

Schema migrations are versioned via the schema_version table.
Increment SCHEMA_VERSION and add a (from_version, sql) tuple to MIGRATIONS
whenever the schema changes.
"""

try:
    from pysqlcipher3 import dbapi2 as sqlite3
    HAS_SQLCIPHER = True
except ImportError:
    try:
        from sqlcipher3 import dbapi2 as sqlite3
        HAS_SQLCIPHER = True
    except ImportError:
        import sqlite3
        HAS_SQLCIPHER = False

from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 7

_CREATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    target_name TEXT NOT NULL,
    template_id TEXT NOT NULL,
    variables   TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS templates (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    version     TEXT NOT NULL,
    tier        TEXT NOT NULL DEFAULT 'asset',
    source_file TEXT,
    data        TEXT NOT NULL,       -- full YAML/JSON source, stored as-is
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    id               TEXT PRIMARY KEY,
    project_id       TEXT NOT NULL,
    parent_id        TEXT,
    template_node_id TEXT,
    type             TEXT NOT NULL,  -- question | checklist | asset | info
    title            TEXT NOT NULL,
    content          TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'not_started',
    is_finding       INTEGER NOT NULL DEFAULT 0,
    soft_deleted     INTEGER NOT NULL DEFAULT 0,
    position         INTEGER NOT NULL DEFAULT 0,
    template_id      TEXT,
    scope_tags       TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id)  REFERENCES nodes(id)
);

CREATE TABLE IF NOT EXISTS project_scope_tags (
    project_id TEXT NOT NULL,
    tag        TEXT NOT NULL,
    PRIMARY KEY (project_id, tag),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS question_answers (
    id          TEXT PRIMARY KEY,
    node_id     TEXT NOT NULL UNIQUE,  -- one active answer per question node
    option_key  TEXT NOT NULL,
    answered_at TEXT NOT NULL,
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notes (
    id         TEXT PRIMARY KEY,
    node_id    TEXT NOT NULL UNIQUE,   -- one note block per node
    content    TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS attachments (
    id            TEXT PRIMARY KEY,
    node_id       TEXT NOT NULL,
    filename      TEXT NOT NULL,
    mime_type     TEXT NOT NULL,
    relative_path TEXT NOT NULL,      -- path relative to the project directory
    created_at    TEXT NOT NULL,
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
);
"""

MIGRATIONS: list[tuple[int, str]] = [
    (1, "ALTER TABLE nodes ADD COLUMN template_id TEXT;"),
    (2, """ALTER TABLE nodes ADD COLUMN scope_tags TEXT NOT NULL DEFAULT '[]';
CREATE TABLE IF NOT EXISTS project_scope_tags (
    project_id TEXT NOT NULL,
    tag        TEXT NOT NULL,
    PRIMARY KEY (project_id, tag),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);"""),
    (3, "ALTER TABLE templates ADD COLUMN tier TEXT NOT NULL DEFAULT 'asset';"),
    (4, "ALTER TABLE projects ADD COLUMN variables TEXT NOT NULL DEFAULT '{}';"),
    (5, "ALTER TABLE attachments ADD COLUMN relative_path TEXT;"),
    (6, "ALTER TABLE attachments DROP COLUMN data;"),
]


def get_default_db_path() -> Path:
    """
    Returns the user-configured database path (from settings), creating the
    parent directory if it doesn't already exist.

    The path defaults to ~/HackMind Projects/hackmind.db but can be changed
    via the Settings dialog. The lazy import keeps database.py free of Qt
    dependencies at module load time.
    """
    import hackmind.settings as _settings  # lazy: QApplication must exist first
    path = _settings.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class Database:
    """
    Wrapper around a sqlite3 connection. Supports SQLCipher encryption.

    Normal use (opens the global app database):
        db = Database.open(password="...")

    Test use (explicit path, won't touch user data):
        db = Database.open_at(tmp_path / "test.db", password="...")

    Always call db.close() when done, or use as a context manager:
        with Database.open(password="...") as db:
            ...
    """

    def __init__(self, path: str | Path, password: Optional[str] = None) -> None:
        self._path = Path(path)
        self.conn: sqlite3.Connection = sqlite3.connect(str(self._path))
        self.conn.row_factory = sqlite3.Row
        
        if password:
            if HAS_SQLCIPHER:
                # Use parameter binding or ensure proper escaping if needed, 
                # but PRAGMA usually takes a literal.
                self.conn.execute(f"PRAGMA key = '{password}'")
            else:
                print("WARNING: SQLCipher not found. Database is unencrypted.")

        self.conn.execute("PRAGMA foreign_keys = ON")
        
        try:
            self._initialise_schema()
        except sqlite3.DatabaseError as e:
            # SQLCipher throws this if the key is wrong
            if "file is not a database" in str(e) or "encrypted" in str(e):
                raise ValueError("Incorrect password or database is corrupted/unencrypted.") from e
            raise

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def open(cls, password: Optional[str] = None) -> "Database":
        """Open the global app database."""
        return cls(get_default_db_path(), password=password)

    @classmethod
    def open_at(cls, path: Path, password: Optional[str] = None) -> "Database":
        """Open a database at an explicit path (for tests)."""
        return cls(path, password=password)

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    @property
    def attachments_dir(self) -> Path:
        """Return the directory where external attachments are stored."""
        # Attachments are stored in a .attachments folder next to the DB
        path = self._path.parent / ".attachments"
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # Schema initialisation and migration
    # ------------------------------------------------------------------

    def _initialise_schema(self) -> None:
        # Check if we can at least query something to verify the key
        try:
            current = self._get_schema_version()
        except sqlite3.DatabaseError:
            # Re-raise to be caught in __init__
            raise

        if current == 0:
            self.conn.executescript(_CREATE_SCHEMA)
            self._set_schema_version(SCHEMA_VERSION)
            return

        for from_ver, sql in MIGRATIONS:
            if current == from_ver:
                self.conn.executescript(sql)
                current += 1
                self._set_schema_version(current)

        if current != SCHEMA_VERSION:
            raise RuntimeError(
                f"Database at schema version {current} is incompatible with "
                f"this application (expects version {SCHEMA_VERSION}). "
                "A migration may be missing."
            )

    def _get_schema_version(self) -> int:
        try:
            row = self.conn.execute(
                "SELECT version FROM schema_version LIMIT 1"
            ).fetchone()
            return row["version"] if row else 0
        except sqlite3.OperationalError:
            return 0  # schema_version table doesn't exist yet

    def _set_schema_version(self, version: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM schema_version")
            self.conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (version,)
            )
