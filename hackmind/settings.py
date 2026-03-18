"""
Central settings module for HackMind.

All persistent user preferences are stored here via QSettings("HackMind", "HackMind"),
which writes to the Windows registry on Windows and ~/.config/HackMind/HackMind.ini
on Linux/macOS.

This module is the single owner of QSettings — themes.py and database.py both
delegate here rather than making their own QSettings calls.

Important: QSettings requires a running QApplication. All getters and setters in this
module must only be called after QApplication has been constructed (which main.py does
before opening the database or showing any UI).

Usage
-----
    from hackmind import settings

    path  = settings.db_path()           # -> Path
    delay = settings.autosave_delay_ms() # -> int
    name  = settings.theme()             # -> str

    settings.set_db_path(Path("/other/hackmind.db"))
    settings.set_autosave_delay_ms(500)
    settings.set_theme("Dracula")
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings

_ORG = "HackMind"
_APP = "HackMind"

# ── Key constants ─────────────────────────────────────────────────────────────
# Import and use these in other modules so there are no raw key strings elsewhere.

KEY_THEME          = "ui/theme"
KEY_DB_PATH        = "db/path"
KEY_AUTOSAVE_DELAY = "editor/autosave_delay_ms"
KEY_GEOMETRY       = "ui/geometry"

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_THEME          = "Dark"
DEFAULT_AUTOSAVE_DELAY = 800   # milliseconds


def _default_db_path() -> str:
    """String form of ~/HackMind Projects/hackmind.db (evaluated lazily, no mkdir here)."""
    return str(Path.home() / "HackMind Projects" / "hackmind.db")


def _qs() -> QSettings:
    """Return a fresh QSettings handle. Cheap to construct; always reads the latest values."""
    return QSettings(_ORG, _APP)


# ── Theme ─────────────────────────────────────────────────────────────────────

def theme() -> str:
    """Return the active UI theme name (e.g. 'Dark', 'Dracula')."""
    return str(_qs().value(KEY_THEME, DEFAULT_THEME))


def set_theme(name: str) -> None:
    """Persist the chosen theme name."""
    s = _qs()
    s.setValue(KEY_THEME, name)


# ── Database path ─────────────────────────────────────────────────────────────

def db_path() -> Path:
    """
    Return the configured database file path.
    Defaults to ~/HackMind Projects/hackmind.db if not explicitly set.
    Does NOT create the directory — callers are responsible for that.
    """
    raw = _qs().value(KEY_DB_PATH, _default_db_path())
    return Path(str(raw))


def set_db_path(path: Path | str) -> None:
    """Persist a new database file path. Takes effect on next application start."""
    _qs().setValue(KEY_DB_PATH, str(path))


# ── Note auto-save delay ──────────────────────────────────────────────────────

def autosave_delay_ms() -> int:
    """
    Return the note auto-save debounce delay in milliseconds.
    Defaults to 800 ms. Valid range for the UI is 100–5000 ms.
    """
    raw = _qs().value(KEY_AUTOSAVE_DELAY, DEFAULT_AUTOSAVE_DELAY)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_AUTOSAVE_DELAY


def set_autosave_delay_ms(ms: int) -> None:
    """Persist the note auto-save debounce delay."""
    _qs().setValue(KEY_AUTOSAVE_DELAY, ms)


# ── Window geometry ───────────────────────────────────────────────────────────

def save_geometry(geometry: bytes) -> None:
    """Persist window geometry bytes (from QWidget.saveGeometry())."""
    _qs().setValue(KEY_GEOMETRY, geometry)


def restore_geometry() -> bytes | None:
    """
    Return previously saved geometry bytes, or None if not yet saved.
    Pass the result to QWidget.restoreGeometry(QByteArray(result)).
    """
    raw = _qs().value(KEY_GEOMETRY)
    return bytes(raw) if raw is not None else None
