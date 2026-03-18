"""
HackMind — entry point.

On first run, auto-imports the bundled methodology templates so the
user can create a project immediately without a manual import step.
"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from hackmind.db.database import Database
from hackmind.db import template_repo
from hackmind.engine import tree_engine
from hackmind.engine.template_loader import load_template_from_file, TemplateValidationError
from hackmind.ui.main_window import MainWindow
from hackmind.ui.themes import apply_theme, saved_theme_name

_BUNDLED_TEMPLATES = [
    Path("templates/web-app.yaml"),
    Path("templates/android-mobile.yaml"),
    Path("templates/thick-client.yaml"),
    Path("templates/api-testing.yaml"),
]


def _ensure_bundled_templates(db: Database) -> None:
    """
    Import (or refresh) bundled templates on startup.

    New templates are inserted.  Existing templates (matched by name+version)
    have their raw YAML updated in-place so that content changes — like newly
    added scope_tags — are picked up without bumping the version.  The
    template's DB id is preserved so existing project nodes are unaffected.
    """
    existing = {(t["name"], t["version"]): t["id"] for t in template_repo.list_templates(db)}

    for path in _BUNDLED_TEMPLATES:
        if not path.exists():
            continue
        try:
            template = load_template_from_file(path)
        except TemplateValidationError:
            continue  # don't crash startup on a bad bundled template

        raw = path.read_text(encoding="utf-8")
        key = (template.name, template.version)
        if key in existing:
            # Keep the existing DB id so project node references stay valid,
            # but update the raw YAML to pick up any content changes.
            template.id = existing[key]
        template_repo.store_template(db, template, raw)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("HackMind")
    app.setApplicationVersion("0.1.0")
    apply_theme(app, saved_theme_name())

    db = Database.open()
    _ensure_bundled_templates(db)
    tree_engine.resync_scope_tags(db)

    window = MainWindow(db)
    window.show()

    exit_code = app.exec()
    db.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
