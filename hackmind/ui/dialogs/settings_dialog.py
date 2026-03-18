"""
Application settings dialog.

Lets the user configure:
  - Database file path   — QLineEdit + Browse button; takes effect on restart
  - Note auto-save delay — QSpinBox (100–5000 ms); takes effect immediately
  - UI theme             — QComboBox; applied immediately on OK

All values are read from and written to hackmind.settings (QSettings-backed).
The caller (MainWindow) is responsible for applying a theme change live after
the dialog closes.

Inputs:  None (reads current settings internally)
Outputs: None (writes directly to settings on accept)
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from hackmind import settings as _settings
from hackmind.ui.themes import THEMES


class SettingsDialog(QDialog):
    """
    Modal dialog for editing persistent application preferences.

    After exec() returns Accepted the caller should check whether the theme
    changed and call apply_theme() on the QApplication if so:

        old = settings.theme()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if settings.theme() != old:
                apply_theme(QApplication.instance(), settings.theme())
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)

        # ── Storage section ───────────────────────────────────────────────────
        self._db_path = QLineEdit(str(_settings.db_path()))

        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_db_path)

        db_row = QHBoxLayout()
        db_row.setContentsMargins(0, 0, 0, 0)
        db_row.addWidget(self._db_path, stretch=1)
        db_row.addWidget(browse_btn)

        restart_note = QLabel("Changing the database path requires a restart to take effect.")
        restart_note.setWordWrap(True)
        restart_note.setObjectName("mutedLabel")  # inherits muted text colour from theme QSS

        # ── Editor section ────────────────────────────────────────────────────
        self._autosave = QSpinBox()
        self._autosave.setRange(100, 5000)
        self._autosave.setSingleStep(100)
        self._autosave.setSuffix(" ms")
        self._autosave.setToolTip("How long to wait after the last keystroke before saving notes.")
        self._autosave.setValue(_settings.autosave_delay_ms())

        # ── Appearance section ────────────────────────────────────────────────
        self._theme = QComboBox()
        for name in THEMES:
            self._theme.addItem(name)
        idx = self._theme.findText(_settings.theme())
        if idx >= 0:
            self._theme.setCurrentIndex(idx)

        # ── Layout ────────────────────────────────────────────────────────────
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.addRow("Database path:", db_row)
        form.addRow("", restart_note)
        form.addRow("Note auto-save:", self._autosave)
        form.addRow("Theme:", self._theme)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _browse_db_path(self) -> None:
        """Open a file picker so the user can choose the database file location."""
        current = self._db_path.text().strip() or str(Path.home())
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Choose Database File",
            current,
            "SQLite database (*.db);;All files (*)",
        )
        if path:
            self._db_path.setText(path)

    def _accept(self) -> None:
        raw_path = self._db_path.text().strip()
        if not raw_path:
            QMessageBox.warning(self, "Validation", "Database path cannot be empty.")
            return

        path = Path(raw_path)
        # Ensure the parent directory can be created before committing the setting.
        if not path.parent.exists():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QMessageBox.critical(
                    self, "Invalid Path",
                    f"Cannot create directory for the database:\n{exc}",
                )
                return

        _settings.set_db_path(path)
        _settings.set_autosave_delay_ms(self._autosave.value())
        _settings.set_theme(self._theme.currentText())
        self.accept()
