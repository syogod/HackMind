"""
Main application window.

Owns the AppState, the tree panel (left), the stacked node-detail
panel (centre), and orchestrates all inter-widget signals.

Layout
------
  QSplitter (horizontal)
    ├── TreePanel              (left, fixed min-width)
    ├── QStackedWidget         (centre)
    │   ├── page 0: WelcomePanel
    │   ├── page 1: ChecklistPanel
    │   ├── page 2: QuestionPanel
    │   └── page 3: AssetPanel
    └── QSplitter (vertical)   (right)
        ├── InfoPanel
        └── QTabWidget (Notes / Attachments)
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QProgressBar,
    QStatusBar,
    QTabWidget,
)
from PyQt6.QtCore import Qt, QByteArray, QThread, pyqtSignal

from hackmind.db import node_repo, project_repo, template_repo
from hackmind.db.database import Database


class ExportWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str, str) # file_path, result_type
    error = pyqtSignal(str)

    def __init__(self, db_path: Path, project_id: str, file_path: str, export_type: str, **kwargs) -> None:
        super().__init__()
        self.db_path = Path(db_path)
        self.project_id = project_id
        self.file_path = file_path
        self.export_type = export_type
        self.kwargs = kwargs

    def run(self) -> None:
        try:
            db = Database.open_at(self.db_path)
            try:
                if self.export_type == "markdown":
                    from hackmind.engine.report_exporter import generate_markdown_report
                    self.progress.emit(30)
                    report_md = generate_markdown_report(db, self.project_id)
                    self.progress.emit(70)
                    Path(self.file_path).write_text(report_md, encoding="utf-8")
                    self.progress.emit(100)
                    self.finished.emit(self.file_path, "Markdown Report")
                elif self.export_type == "template":
                    from hackmind.engine.template_exporter import export_asset_subtree
                    from hackmind.engine.template_loader import load_template_from_string
                    self.progress.emit(20)
                    raw_yaml = export_asset_subtree(
                        db, self.kwargs["asset_node_id"],
                        name=self.kwargs["name"],
                        version=self.kwargs["version"],
                        author=self.kwargs["author"],
                        description=self.kwargs["description"]
                    )
                    self.progress.emit(60)
                    template = load_template_from_string(raw_yaml)
                    template_repo.store_template(db, template, raw_yaml)
                    self.progress.emit(80)
                    Path(self.file_path).write_text(raw_yaml, encoding="utf-8")
                    self.progress.emit(100)
                    self.finished.emit(self.file_path, "Methodology Template")
            finally:
                db.close()
        except Exception as e:
            self.error.emit(str(e))


from hackmind.engine import tree_engine
from hackmind.engine.template_exporter import (
    bump_version,
    find_primary_template_meta,
)
from hackmind.engine.template_loader import (
    TemplateValidationError,
    load_template_from_file,
)
from hackmind.models.types import NodeType
from hackmind.ui.app_state import AppState
from hackmind.ui.dialogs.add_node_dialog import AddNodeDialog
from hackmind.ui.dialogs.export_template_dialog import ExportTemplateDialog
from hackmind.ui.dialogs.new_project_dialog import NewProjectDialog
from hackmind.ui.dialogs.settings_dialog import SettingsDialog
from hackmind.ui.dialogs.template_editor_dialog import TemplateEditorDialog
from hackmind.ui.panels.asset_panel import AssetPanel
from hackmind.ui.panels.checklist_panel import ChecklistPanel
from hackmind.ui.panels.info_panel import InfoPanel
from hackmind.ui.panels.question_panel import QuestionPanel
from hackmind.ui.panels.welcome_panel import WelcomePanel
from hackmind.ui.themes import THEMES, apply_theme
from hackmind.ui.tree_panel import TreePanel
from hackmind.ui.widgets.attachment_pane import AttachmentPane
from hackmind.ui.widgets.note_editor import NoteEditor

_PAGE_WELCOME   = 0
_PAGE_CHECKLIST = 1
_PAGE_QUESTION  = 2
_PAGE_ASSET     = 3


class MainWindow(QMainWindow):
    def __init__(self, db: Database) -> None:
        super().__init__()
        self._state = AppState(db=db)
        self._theme_group = None  # set by _build_menu(); kept for _sync_theme_menu()
        self.setWindowTitle("HackMind")
        self.resize(1280, 800)
        self.setAcceptDrops(True)
        self._build_ui()
        self._build_menu()
        self._restore_geometry()
        
        # Status Bar with Progress
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumWidth(200)
        self._progress_bar.setVisible(False)
        self._status_bar.addPermanentWidget(self._progress_bar)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # 1. Left Pane: Tree
        self._tree_panel = TreePanel()
        self._tree_panel.node_selected.connect(self._on_node_selected)
        self._tree_panel.width_hint_changed.connect(self._on_tree_width_hint)
        self._tree_panel.node_add_requested.connect(self._on_node_add_requested)
        self._tree_panel.export_requested.connect(self._on_export_requested)

        # 2. Center Pane: Dynamic Checklist/Content
        # We'll use a stack for the center pane to handle different node types
        self._center_stack = QStackedWidget()
        
        self._welcome = WelcomePanel(self._state.db)
        self._welcome.project_opened.connect(self._open_project_by_id)
        self._welcome.new_project_requested.connect(self._new_project)

        self._checklist_panel = ChecklistPanel(self._state.db)
        self._checklist_panel.tree_changed.connect(self._refresh_tree)
        
        self._question_panel = QuestionPanel(self._state)
        self._question_panel.tree_changed.connect(self._refresh_tree)

        self._asset_panel = AssetPanel(self._state)
        self._asset_panel.tree_changed.connect(self._refresh_tree)
        self._asset_panel.node_deleted.connect(self._on_asset_deleted)
        self._asset_panel.node_focus_requested.connect(self._on_node_selected)
        self._asset_panel.node_focus_requested.connect(self._tree_panel.select_node)

        self._center_stack.addWidget(self._welcome)         # 0
        self._center_stack.addWidget(self._checklist_panel) # 1
        self._center_stack.addWidget(self._question_panel)  # 2
        self._center_stack.addWidget(self._asset_panel)     # 3

        # 3. Right Pane: Info (Top) & Tabs (Notes / Attachments) (Bottom)
        self._right_splitter = QSplitter(Qt.Orientation.Vertical)
        
        self._info_panel = InfoPanel()
        
        self._tab_widget = QTabWidget()
        self._note_editor = NoteEditor(self._state.db)
        self._attachment_pane = AttachmentPane(self._state.db)
        self._tab_widget.addTab(self._note_editor, "Notes")
        self._tab_widget.addTab(self._attachment_pane, "Attachments")
        
        self._right_splitter.addWidget(self._info_panel)
        self._right_splitter.addWidget(self._tab_widget)
        self._right_splitter.setStretchFactor(0, 1)
        self._right_splitter.setStretchFactor(1, 2)

        # Main Layout: Three Panes
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.addWidget(self._tree_panel)
        self._main_splitter.addWidget(self._center_stack)
        self._main_splitter.addWidget(self._right_splitter)
        
        self._main_splitter.setStretchFactor(0, 1)
        self._main_splitter.setStretchFactor(1, 2)
        self._main_splitter.setStretchFactor(2, 1)
        self._main_splitter.setStretchFactor(1, 2)
        self._main_splitter.setStretchFactor(2, 1)

        self.setCentralWidget(self._main_splitter)
        self._show_welcome()

    def _build_menu(self) -> None:
        from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
        menubar = self.menuBar()

        def action(text: str, slot, shortcut: str | None = None) -> QAction:
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            return a

        file_menu = menubar.addMenu("&File")
        file_menu.addAction(action("&New Project…",      self._new_project,        "Ctrl+N"))
        file_menu.addAction(action("&Close Project",     self._close_project))
        file_menu.addSeparator()
        file_menu.addAction(action("&Import Targets (Text File)…", self._import_targets))
        file_menu.addAction(action("&Export Report (Markdown)…", self._export_report, "Ctrl+E"))
        file_menu.addSeparator()
        file_menu.addAction(action("&Import Template…",  self._import_template))
        file_menu.addAction(action("&Template Editor…",  self._open_template_editor))
        file_menu.addSeparator()
        file_menu.addAction(action("&Settings…",         self._open_settings,      "Ctrl+,"))
        file_menu.addSeparator()
        file_menu.addAction(action("&Quit",              self.close,               "Ctrl+Q"))

        view_menu = menubar.addMenu("&View")
        theme_menu = view_menu.addMenu("&Theme")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        for name in THEMES:
            a = QAction(name, self)
            a.setCheckable(True)
            a.setChecked(name == self._current_theme_name())
            a.triggered.connect(lambda checked, n=name: self._apply_theme(n))
            self._theme_group.addAction(a)
            theme_menu.addAction(a)

    # ------------------------------------------------------------------
    # Project lifecycle
    # ------------------------------------------------------------------

    def _new_project(self) -> None:
        dialog = NewProjectDialog(self._state.db, self)
        if dialog.exec() != NewProjectDialog.DialogCode.Accepted:
            return
        if dialog.created_project is None:
            return

        project = dialog.created_project
        project_repo.create_project(self._state.db, project)
        tree_engine.instantiate_project(
            self._state.db, project.id, project.target_name,
            template_id=project.template_id or None,
        )

        self._state.project = project
        self._load_project()
        root = next(
            (n for n in node_repo.get_project_nodes(self._state.db, project.id)
             if n.parent_id is None),
            None,
        )
        if root:
            self._tree_panel.select_node(root.id)

    def _open_project_by_id(self, project_id: str) -> None:
        project = project_repo.get_project(self._state.db, project_id)
        if project is None:
            QMessageBox.warning(self, "Not Found", "Project not found.")
            return

        self._state.project = project
        self._load_project()

    def _close_project(self) -> None:
        if self._state.project is None:
            return
        self._checklist_panel.flush()
        self._asset_panel.flush()
        self._note_editor.flush()
        self._state.project = None
        self._tree_panel.clear()
        self._show_welcome()

    def _load_project(self) -> None:
        if not self._state.project_open:
            return
        self.setWindowTitle(
            f"HackMind — {self._state.project.name} [{self._state.project.target_name}]"
        )
        self._tree_panel.load(self._state.db, self._state.project.id)
        self._center_stack.setCurrentIndex(_PAGE_WELCOME)

    def _export_report(self) -> None:
        if self._state.project is None:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return

        save_file, _ = QFileDialog.getSaveFileName(
            self, "Export Markdown Report", f"{self._state.project.name}_Report.md",
            "Markdown files (*.md *.markdown)"
        )
        if not save_file:
            return

        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._status_bar.showMessage("Exporting report...")

        self._export_worker = ExportWorker(self._state.db._path, self._state.project.id, save_file, "markdown")
        self._export_worker.progress.connect(self._progress_bar.setValue)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.error.connect(self._on_export_error)
        self._export_worker.start()

    def _on_export_finished(self, file_path: str, export_type: str) -> None:
        self._progress_bar.setVisible(False)
        self._status_bar.showMessage(f"{export_type} exported successfully.", 5000)
        QMessageBox.information(self, "Export Successful", f"{export_type} saved to:\n{file_path}")

    def _on_export_error(self, error_msg: str) -> None:
        self._progress_bar.setVisible(False)
        self._status_bar.showMessage("Export failed.", 5000)
        QMessageBox.critical(self, "Export Failed", f"An error occurred during export:\n{error_msg}")

    # Global Drag and Drop
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        current_node_id = self._tree_panel._current_node_id()
        if not current_node_id:
            return

        from hackmind.db import attachment_repo
        from hackmind.models.types import Attachment
        import mimetypes
        from pathlib import Path

        for url in event.mimeData().urls():
            file_path = Path(url.toLocalFile())
            if file_path.is_file():
                data = file_path.read_bytes()
                mime_type, _ = mimetypes.guess_type(str(file_path))
                att = Attachment(
                    node_id=current_node_id,
                    filename=file_path.name,
                    mime_type=mime_type or "application/octet-stream",
                    data=data
                )
                attachment_repo.insert_attachment(self._state.db, att)
        
        self._refresh_tree()
        self._on_node_selected(current_node_id)
        self._attachment_pane.load(current_node_id)
        event.acceptProposedAction()

    def _import_targets(self) -> None:
        if self._state.project is None:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Import Targets", "", "Text files (*.txt);;All files (*)"
        )
        if not path:
            return

        try:
            content = Path(path).read_text(encoding="utf-8")
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            if not lines:
                return

            # Add each line as a new asset under the project root
            # First find project root
            root = next(
                (n for n in node_repo.get_project_nodes(self._state.db, self._state.project.id)
                 if n.parent_id is None),
                None,
            )
            if not root:
                return

            for line in lines:
                tree_engine.add_asset(
                    self._state.db,
                    self._state.project.id,
                    root.id,
                    line,
                )
            
            self._refresh_tree()
            QMessageBox.information(self, "Imported", f"Imported {len(lines)} targets.")
        except Exception as exc:
            QMessageBox.critical(self, "Import Failed", f"Could not import targets:\n{str(exc)}")

    # ------------------------------------------------------------------
    # Node selection
    # ------------------------------------------------------------------

    def _on_node_selected(self, node_id: str) -> None:
        node = node_repo.get_node(self._state.db, node_id)
        if node is None:
            return

        # Right pane always updates
        self._info_panel.load(node)
        self._note_editor.load(node.id)
        self._attachment_pane.load(node.id)

        # Center pane updates based on type
        if node.type == NodeType.QUESTION:
            self._question_panel.load(node)
            self._center_stack.setCurrentIndex(_PAGE_QUESTION)

        elif node.type == NodeType.CHECKLIST:
            self._checklist_panel.flush()
            self._checklist_panel.load(node)
            self._center_stack.setCurrentIndex(_PAGE_CHECKLIST)

        elif node.type == NodeType.ASSET:
            self._asset_panel.load(node)
            self._center_stack.setCurrentIndex(_PAGE_ASSET)

        elif node.type == NodeType.INFO:
            self._center_stack.setCurrentIndex(_PAGE_WELCOME)

    # ------------------------------------------------------------------
    # Tree refresh
    # ------------------------------------------------------------------

    def _refresh_tree(self) -> None:
        if not self._state.project_open:
            return
        self._tree_panel.refresh(self._state.db, self._state.project.id)

    def _on_asset_deleted(self) -> None:
        self._refresh_tree()
        self._center_stack.setCurrentIndex(_PAGE_WELCOME)

    # ------------------------------------------------------------------
    # Template import
    # ------------------------------------------------------------------

    def _open_template_editor(self) -> None:
        dialog = TemplateEditorDialog(self._state.db, self)
        dialog.exec()
        # Refresh the welcome panel in case templates were added/updated.
        self._welcome.refresh()

    def _import_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Template", "", "YAML files (*.yaml *.yml);;All files (*)"
        )
        if not path:
            return
        try:
            template = load_template_from_file(Path(path))
        except TemplateValidationError as exc:
            QMessageBox.critical(self, "Template Error", str(exc))
            return

        raw = Path(path).read_text(encoding="utf-8")
        template_repo.store_template(self._state.db, template, raw)
        QMessageBox.information(
            self, "Template Imported",
            f"'{template.name}' v{template.version} imported successfully."
        )
        self._welcome.refresh()

    # ------------------------------------------------------------------
    # Manual node addition
    # ------------------------------------------------------------------

    def _on_node_add_requested(self, parent_node_id: str, node_type_value: str) -> None:
        if self._state.project is None:
            return
        node_type = NodeType(node_type_value)
        dialog = AddNodeDialog(node_type, self)
        if dialog.exec() != AddNodeDialog.DialogCode.Accepted:
            return
        tree_engine.add_node(
            self._state.db,
            self._state.project.id,
            parent_node_id,
            node_type,
            dialog.result_title,
            dialog.result_content,
        )
        self._refresh_tree()

    # ------------------------------------------------------------------
    # Template export
    # ------------------------------------------------------------------

    def _on_export_requested(self, asset_node_id: str) -> None:
        if self._state.project is None:
            return

        meta = find_primary_template_meta(self._state.db, asset_node_id)
        suggested_name    = meta["name"]    if meta else self._state.project.target_name
        suggested_version = bump_version(meta["version"]) if meta else "1.0.0"
        suggested_author  = meta.get("author", "") if meta else ""

        dialog = ExportTemplateDialog(
            suggested_name=suggested_name,
            suggested_version=suggested_version,
            suggested_author=suggested_author,
            parent=self,
        )
        if dialog.exec() != ExportTemplateDialog.DialogCode.Accepted:
            return

        save_file, _ = QFileDialog.getSaveFileName(
            self, "Save Template File", f"{dialog.result_name}.yaml",
            "YAML files (*.yaml *.yml)"
        )
        if not save_file:
            return

        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._status_bar.showMessage("Exporting template...")

        self._export_worker = ExportWorker(
            self._state.db._path, self._state.project.id, save_file, "template",
            asset_node_id=asset_node_id,
            name=dialog.result_name,
            version=dialog.result_version,
            author=dialog.result_author,
            description=dialog.result_description
        )
        self._export_worker.progress.connect(self._progress_bar.setValue)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.finished.connect(lambda: self._welcome.refresh())
        self._export_worker.error.connect(self._on_export_error)
        self._export_worker.start()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        from hackmind import settings as _settings
        old_theme = _settings.theme()

        dialog = SettingsDialog(self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return

        # Apply theme change immediately without requiring a restart.
        new_theme = _settings.theme()
        if new_theme != old_theme:
            from PyQt6.QtWidgets import QApplication
            apply_theme(QApplication.instance(), new_theme)
            self._sync_theme_menu(new_theme)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _current_theme_name(self) -> str:
        from hackmind.ui.themes import saved_theme_name
        return saved_theme_name()

    def _apply_theme(self, name: str) -> None:
        """Called by the View > Theme menu actions."""
        from PyQt6.QtWidgets import QApplication
        apply_theme(QApplication.instance(), name)
        self._sync_theme_menu(name)

    def _sync_theme_menu(self, active_name: str) -> None:
        """Update the View > Theme checkmarks to reflect *active_name*."""
        if self._theme_group is None:
            return
        for action in self._theme_group.actions():
            action.setChecked(action.text() == active_name)

    # ------------------------------------------------------------------
    # Geometry persistence
    # ------------------------------------------------------------------

    def _restore_geometry(self) -> None:
        """Restore the window size and position from the previous session."""
        from hackmind import settings as _settings
        raw = _settings.restore_geometry()
        if raw:
            self.restoreGeometry(QByteArray(raw))

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Save window geometry before closing so it can be restored next launch."""
        from hackmind import settings as _settings
        _settings.save_geometry(bytes(self.saveGeometry()))
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _on_tree_width_hint(self, width: int) -> None:
        sizes = self._main_splitter.sizes()
        if len(sizes) == 3:
            remaining = sum(sizes) - width
            center = int(remaining * 2 / 3)
            right = remaining - center
            self._main_splitter.setSizes([width, center, right])
        elif len(sizes) == 2:
            self._main_splitter.setSizes([width, sum(sizes) - width])

    def _show_welcome(self) -> None:
        self._welcome.refresh()
        self._center_stack.setCurrentIndex(_PAGE_WELCOME)
        self.setWindowTitle("HackMind")
