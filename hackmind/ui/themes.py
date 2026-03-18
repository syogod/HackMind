"""
Theme system for HackMind.

Each theme is a Palette (set of colour tokens).  A single QSS template is
filled from the palette and applied to the QApplication, so every widget
inherits it automatically.

Usage
-----
    from hackmind.ui.themes import apply_theme, saved_theme_name, THEMES

    apply_theme(app, saved_theme_name())   # on startup

    apply_theme(app, "Dracula")            # to switch
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QPixmap, QPainter, QPolygon
from PyQt6.QtWidgets import QApplication

_arrow_dir: str | None = None


@dataclass(frozen=True)
class Palette:
    name: str
    bg_base: str        # window / main background
    bg_surface: str     # panels, tree, cards
    bg_elevated: str    # inputs, list items, buttons
    border: str         # borders and dividers
    text_primary: str   # body text
    text_secondary: str # labels, group box titles
    text_muted: str     # placeholder, disabled
    accent: str         # primary interactive colour
    accent_hover: str   # accent on hover / pressed
    accent_text: str    # text drawn on top of accent bg
    danger: str         # destructive actions
    danger_bg: str      # danger button hover bg
    success: str        # complete / answered
    warning: str        # in-progress


# ---------------------------------------------------------------------------
# Palette definitions
# ---------------------------------------------------------------------------

THEMES: dict[str, Palette] = {
    "Dark": Palette(
        name="Dark",
        bg_base="#1a1b26",
        bg_surface="#24283b",
        bg_elevated="#292e42",
        border="#414868",
        text_primary="#c0caf5",
        text_secondary="#9aa5ce",
        text_muted="#565f89",
        accent="#7aa2f7",
        accent_hover="#5a7fd4",
        accent_text="#1a1b26",
        danger="#f7768e",
        danger_bg="#3d1f26",
        success="#9ece6a",
        warning="#e0af68",
    ),
    "Dracula": Palette(
        name="Dracula",
        bg_base="#282a36",
        bg_surface="#21222c",
        bg_elevated="#343746",
        border="#44475a",
        text_primary="#f8f8f2",
        text_secondary="#6272a4",
        text_muted="#44475a",
        accent="#bd93f9",
        accent_hover="#9d72d9",
        accent_text="#f8f8f2",
        danger="#ff5555",
        danger_bg="#3d1515",
        success="#50fa7b",
        warning="#ffb86c",
    ),
    "Solarized Dark": Palette(
        name="Solarized Dark",
        bg_base="#002b36",
        bg_surface="#073642",
        bg_elevated="#0d3d4a",
        border="#1a5264",
        text_primary="#839496",
        text_secondary="#586e75",
        text_muted="#3a5260",
        accent="#268bd2",
        accent_hover="#1a6ba8",
        accent_text="#fdf6e3",
        danger="#dc322f",
        danger_bg="#2d0e0d",
        success="#859900",
        warning="#b58900",
    ),
    "Light": Palette(
        name="Light",
        bg_base="#f8f9fa",
        bg_surface="#ffffff",
        bg_elevated="#f0f2f5",
        border="#dee2e6",
        text_primary="#212529",
        text_secondary="#6c757d",
        text_muted="#adb5bd",
        accent="#0d6efd",
        accent_hover="#0a58ca",
        accent_text="#ffffff",
        danger="#dc3545",
        danger_bg="#fce8ea",
        success="#198754",
        warning="#fd7e14",
    ),
    "Matrix": Palette(
        name="Matrix",
        bg_base="#080c08",
        bg_surface="#0d150d",
        bg_elevated="#121f12",
        border="#1a4d1a",
        text_primary="#00ff41",
        text_secondary="#00cc33",
        text_muted="#1a5c1a",
        accent="#00ff41",
        accent_hover="#00cc33",
        accent_text="#080c08",
        danger="#ff3333",
        danger_bg="#2d0000",
        success="#00ff41",
        warning="#ccff00",
    ),
    "Nord": Palette(
        name="Nord",
        bg_base="#2e3440",
        bg_surface="#3b4252",
        bg_elevated="#434c5e",
        border="#4c566a",
        text_primary="#eceff4",
        text_secondary="#d8dee9",
        text_muted="#616e88",
        accent="#88c0d0",
        accent_hover="#6aacbd",
        accent_text="#2e3440",
        danger="#bf616a",
        danger_bg="#2d1a1c",
        success="#a3be8c",
        warning="#ebcb8b",
    ),
    "Monokai": Palette(
        name="Monokai",
        bg_base="#272822",
        bg_surface="#1e1f1c",
        bg_elevated="#3e3d32",
        border="#49483e",
        text_primary="#f8f8f2",
        text_secondary="#75715e",
        text_muted="#49483e",
        accent="#a6e22e",
        accent_hover="#88cc22",
        accent_text="#272822",
        danger="#f92672",
        danger_bg="#3d0f22",
        success="#a6e22e",
        warning="#e6db74",
    ),
}


# ---------------------------------------------------------------------------
# QSS template
# ---------------------------------------------------------------------------

def _write_arrow_png(path: str, points: list[tuple[int, int]], color: str) -> None:
    """Render a filled triangle onto a 12×12 transparent PNG and save it."""
    pixmap = QPixmap(12, 12)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPolygon(QPolygon([QPoint(x, y) for x, y in points]))
    painter.end()
    pixmap.save(path, "PNG")


def _arrow_paths(color: str) -> tuple[str, str]:
    """Return (right_arrow_path, down_arrow_path), generating PNGs if needed."""
    global _arrow_dir
    if _arrow_dir is None:
        _arrow_dir = tempfile.mkdtemp(prefix="hackmind_arrows_")
    key = color.lstrip("#")
    right = os.path.join(_arrow_dir, f"right_{key}.png")
    down  = os.path.join(_arrow_dir, f"down_{key}.png")
    if not os.path.exists(right):
        _write_arrow_png(right, [(2, 1), (10, 6), (2, 11)], color)
    if not os.path.exists(down):
        _write_arrow_png(down,  [(1, 3), (11, 3), (6, 10)], color)
    # QSS url() paths must use forward slashes
    return right.replace("\\", "/"), down.replace("\\", "/")


def _build_stylesheet(p: Palette) -> str:
    arrow_right, arrow_down = _arrow_paths(p.text_secondary)
    return f"""
/* ── Base ─────────────────────────────────────────────────────────────── */
QWidget {{
    background-color: {p.bg_base};
    color: {p.text_primary};
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {p.bg_base};
}}

/* ── Menu bar ──────────────────────────────────────────────────────────── */
QMenuBar {{
    background-color: {p.bg_surface};
    color: {p.text_primary};
    border-bottom: 1px solid {p.border};
    padding: 2px 4px;
}}
QMenuBar::item {{
    padding: 4px 8px;
    border-radius: 3px;
    background: transparent;
}}
QMenuBar::item:selected {{
    background-color: {p.accent};
    color: {p.accent_text};
}}
QMenu {{
    background-color: {p.bg_surface};
    border: 1px solid {p.border};
    border-radius: 4px;
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 24px 5px 12px;
    border-radius: 3px;
    color: {p.text_primary};
}}
QMenu::item:selected {{
    background-color: {p.accent};
    color: {p.accent_text};
}}
QMenu::separator {{
    height: 1px;
    background: {p.border};
    margin: 4px 8px;
}}

/* ── Splitter ──────────────────────────────────────────────────────────── */
QSplitter::handle:horizontal {{
    width: 1px;
    background-color: {p.border};
}}

/* ── Tree view ─────────────────────────────────────────────────────────── */
QTreeView {{
    background-color: {p.bg_surface};
    border: none;
    outline: none;
    padding: 4px 0;
}}
QTreeView::item {{
    padding: 4px 6px;
    border-radius: 3px;
    min-height: 22px;
}}
QTreeView::item:hover {{
    background-color: {p.bg_elevated};
}}
QTreeView::item:selected {{
    background-color: {p.accent};
    color: {p.accent_text};
}}
QTreeView::branch {{
    background-color: transparent;
}}
QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings {{
    image: url({arrow_right});
}}
QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings {{
    image: url({arrow_down});
}}

/* ── Group boxes ───────────────────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {p.border};
    border-radius: 6px;
    margin-top: 12px;
    padding: 10px 8px 8px 8px;
    color: {p.text_secondary};
    font-weight: bold;
    font-size: 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    background-color: {p.bg_base};
}}

/* ── Inputs ────────────────────────────────────────────────────────────── */
QLineEdit, QTextEdit, QTextBrowser, QPlainTextEdit {{
    background-color: {p.bg_elevated};
    border: 1px solid {p.border};
    border-radius: 4px;
    padding: 5px 8px;
    color: {p.text_primary};
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {p.accent};
}}
QTextBrowser {{
    background-color: {p.bg_surface};
}}

QComboBox {{
    background-color: {p.bg_elevated};
    border: 1px solid {p.border};
    border-radius: 4px;
    padding: 4px 8px;
    color: {p.text_primary};
    min-width: 120px;
}}
QComboBox:focus {{
    border-color: {p.accent};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {p.bg_surface};
    border: 1px solid {p.border};
    border-radius: 4px;
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
    outline: none;
}}

/* ── Buttons (default) ─────────────────────────────────────────────────── */
QPushButton {{
    background-color: {p.bg_elevated};
    border: 1px solid {p.border};
    border-radius: 4px;
    padding: 5px 14px;
    color: {p.text_primary};
    min-height: 24px;
}}
QPushButton:hover {{
    background-color: {p.accent};
    color: {p.accent_text};
    border-color: {p.accent};
}}
QPushButton:pressed {{
    background-color: {p.accent_hover};
    border-color: {p.accent_hover};
    color: {p.accent_text};
}}
QPushButton:disabled {{
    color: {p.text_muted};
    border-color: {p.border};
    background-color: {p.bg_elevated};
}}

/* ── Danger button (setObjectName("dangerButton")) ──────────────────────── */
QPushButton#dangerButton {{
    color: {p.danger};
    border: 1px solid {p.danger};
    background-color: transparent;
    border-radius: 4px;
    padding: 4px 12px;
}}
QPushButton#dangerButton:hover {{
    background-color: {p.danger_bg};
    color: {p.danger};
    border-color: {p.danger};
}}

/* ── Answer buttons (setObjectName("answerBtn")) ────────────────────────── */
QPushButton#answerBtn {{
    background-color: {p.bg_elevated};
    border: 1px solid {p.border};
    border-radius: 5px;
    padding: 8px 14px;
    color: {p.text_primary};
    text-align: left;
    min-height: 32px;
}}
QPushButton#answerBtn:hover {{
    border-color: {p.accent};
    background-color: {p.bg_surface};
    color: {p.text_primary};
}}
QPushButton#answerBtn[active="true"] {{
    background-color: {p.accent};
    color: {p.accent_text};
    border-color: {p.accent};
    font-weight: bold;
}}

/* ── Checkboxes ─────────────────────────────────────────────────────────── */
QCheckBox {{
    color: {p.text_primary};
    spacing: 6px;
}}
QCheckBox#findingCheck {{
    color: {p.danger};
    font-weight: bold;
}}

/* ── Labels ─────────────────────────────────────────────────────────────── */
QLabel#mutedLabel {{
    color: {p.text_muted};
}}

/* ── List widget (welcome panel, attachments) ───────────────────────────── */
QListWidget {{
    background-color: {p.bg_surface};
    border: 1px solid {p.border};
    border-radius: 4px;
    outline: none;
}}
QListWidget::item {{
    padding: 6px 10px;
    border-radius: 3px;
    color: {p.text_primary};
}}
QListWidget::item:hover {{
    background-color: {p.bg_elevated};
}}
QListWidget::item:selected {{
    background-color: {p.accent};
    color: {p.accent_text};
}}

/* ── Scroll bars ────────────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    border: none;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p.border};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p.text_muted};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
    background: none;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    border: none;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {p.border};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {p.text_muted};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
    background: none;
}}

/* ── Form layout labels ─────────────────────────────────────────────────── */
QFormLayout QLabel {{
    color: {p.text_secondary};
}}

/* ── Status bar ─────────────────────────────────────────────────────────── */
QStatusBar {{
    background-color: {p.bg_surface};
    color: {p.text_secondary};
    border-top: 1px solid {p.border};
}}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_theme(app: QApplication, name: str) -> None:
    """Apply *name* to the QApplication stylesheet and persist it to settings."""
    from hackmind import settings as _settings
    palette = THEMES.get(name, THEMES[_settings.DEFAULT_THEME])
    app.setStyleSheet(_build_stylesheet(palette))
    _settings.set_theme(name)


def saved_theme_name() -> str:
    """Return the persisted theme name, falling back to the default."""
    from hackmind import settings as _settings
    return _settings.theme()
