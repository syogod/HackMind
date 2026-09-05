import os
import sys
import tempfile
from pathlib import Path

# Ensure offscreen Qt platform
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication, QMessageBox, QInputDialog, QFileDialog
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtTest import QTest

import main
from hackmind.db.database import Database
from hackmind.db import node_repo, project_repo, template_repo, attachment_repo
from hackmind.models.types import NodeStatus, NodeType, Project, Attachment
from hackmind.ui.main_window import MainWindow
from hackmind.ui.dialogs.add_node_dialog import AddNodeDialog
from hackmind.ui.dialogs.export_template_dialog import ExportTemplateDialog
from hackmind.ui.dialogs.new_project_dialog import NewProjectDialog
from hackmind.ui.dialogs.scope_dialog import ScopeDialog
from hackmind.ui.dialogs.settings_dialog import SettingsDialog
from hackmind.ui.dialogs.template_editor_dialog import TemplateEditorDialog


def run_dynamic_tests():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["hackmind_dynamic_test", "-platform", "offscreen"])

    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "hackmind_test.db"
    db = Database.open_at(db_path)

    # 1. Ensure templates
    print("[1] Ensuring bundled templates...")
    main._ensure_bundled_templates(db)

    # 2. Instantiate MainWindow
    print("[2] Initializing MainWindow...")
    window = MainWindow(db)
    window.show()
    app.processEvents()

    # 3. Test New Project Flow
    print("[3] Testing New Project creation via dialog...")
    new_dialog = NewProjectDialog(db, window)
    new_dialog._name.setText("Dynamic Test Corp")
    new_dialog._target.setText("dynamictest.com")
    # select engagement template if available
    if new_dialog._engagement_combo.count() > 1:
        new_dialog._engagement_combo.setCurrentIndex(1)
    new_dialog._accept()
    assert new_dialog.created_project is not None
    
    project = new_dialog.created_project
    project_repo.create_project(db, project)
    from hackmind.engine import tree_engine
    tree_engine.instantiate_project(db, project.id, project.target_name, template_id=project.template_id or None)
    
    window._state.project = project
    window._load_project()
    app.processEvents()

    # 4. Navigate Tree Panel & Select Nodes
    print("[4] Testing TreePanel node selections...")
    nodes = node_repo.get_project_nodes(db, project.id)
    print(f"    Loaded {len(nodes)} initial nodes")
    for n in nodes:
        window._on_node_selected(n.id)
        app.processEvents()

    # 5. Test Adding Sub-Asset without template (tests bootstrap question)
    print("[5] Testing adding sub-asset...")
    root_node = next(n for n in nodes if n.parent_id is None)
    asset_node = tree_engine.add_asset(db, project.id, root_node.id, "sub.dynamictest.com")
    window._refresh_tree()
    app.processEvents()

    # Find bootstrap question
    children = node_repo.get_children(db, asset_node.id)
    assert len(children) >= 1
    bootstrap_q = children[0]
    assert bootstrap_q.template_node_id == tree_engine.ASSET_TYPE_NODE_ID

    # 6. Test QuestionPanel with Bootstrap Question
    print("[6] Testing QuestionPanel answering bootstrap question...")
    window._on_node_selected(bootstrap_q.id)
    app.processEvents()
    
    # Get available asset template
    templates = [t for t in template_repo.list_templates(db) if t.get("tier", "asset") == "asset"]
    assert len(templates) > 0
    chosen_template = templates[0]
    window._question_panel._select_asset_type(chosen_template["id"])
    window._refresh_tree()
    app.processEvents()

    # 7. Test QuestionPanel with Normal Question (and clearing)
    print("[7] Testing QuestionPanel answering normal question and clear...")
    all_nodes = node_repo.get_project_nodes(db, project.id)
    question_nodes = [n for n in all_nodes if n.type == NodeType.QUESTION and n.template_node_id != tree_engine.ASSET_TYPE_NODE_ID]
    if question_nodes:
        q = question_nodes[0]
        window._on_node_selected(q.id)
        app.processEvents()
        
        # Click an option button
        opt_buttons = window._question_panel._options_widget.findChildren(type(window._question_panel._clear_btn))
        if opt_buttons:
            opt_buttons[0].click()
            app.processEvents()
        
        # Clear answer
        window._question_panel._clear()
        app.processEvents()

    # 8. Test Checklist Panel interactions (Status combo, Finding toggle, Filter)
    print("[8] Testing ChecklistPanel controls and status updates...")
    checklist_nodes = [n for n in all_nodes if n.type == NodeType.CHECKLIST]
    if checklist_nodes:
        chk_node = checklist_nodes[0]
        window._on_node_selected(chk_node.id)
        app.processEvents()

        # Change status
        window._checklist_panel._on_row_status_changed(chk_node, NodeStatus.VULNERABLE)
        assert node_repo.get_node(db, chk_node.id).status == NodeStatus.VULNERABLE
        window._checklist_panel._on_row_status_changed(chk_node, NodeStatus.COMPLETE)
        assert node_repo.get_node(db, chk_node.id).status == NodeStatus.COMPLETE

        # Toggle finding
        window._checklist_panel._on_row_finding_toggled(chk_node, True)
        assert node_repo.get_node(db, chk_node.id).is_finding is True
        window._checklist_panel._on_row_finding_toggled(chk_node, False)
        assert node_repo.get_node(db, chk_node.id).is_finding is False

        # Filter
        window._checklist_panel._filter_edit.setText("test")
        app.processEvents()
        window._checklist_panel._filter_edit.setText("")
        app.processEvents()

    # 9. Test NoteEditor and AttachmentPane tabs
    print("[9] Testing NoteEditor and AttachmentPane...")
    if checklist_nodes:
        target_node = checklist_nodes[0]
        window._tab_widget.setCurrentIndex(0) # Notes
        window._note_editor.set_text("Testing note content with **bold** and `code`.")
        window._note_editor.flush()
        assert node_repo.get_note(db, target_node.id).content == "Testing note content with **bold** and `code`."

        # Attach file
        window._tab_widget.setCurrentIndex(1) # Attachments
        att = Attachment(
            node_id=target_node.id,
            filename="dynamic_test.png",
            mime_type="image/png",
            data=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd4n\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        attachment_repo.insert_attachment(db, att)
        window._attachment_pane.load(target_node.id)
        app.processEvents()
        assert window._attachment_pane._grid.count() == 1

    # 10. Test Scope Dialog
    print("[10] Testing ScopeDialog...")
    scope_diag = ScopeDialog(db, project.id, window)
    scope_diag._on_accept()
    app.processEvents()

    # 11. Test Settings Dialog
    print("[11] Testing SettingsDialog...")
    settings_diag = SettingsDialog(window)
    settings_diag._theme.setCurrentIndex(0)
    settings_diag._accept()
    app.processEvents()

    # 12. Test Theme Switching
    print("[12] Testing all themes...")
    from hackmind.ui.themes import THEMES
    for theme_name in THEMES:
        window._apply_theme(theme_name)
        app.processEvents()

    # 13. Test Template Editor Dialog
    print("[13] Testing TemplateEditorDialog...")
    tmpl_editor = TemplateEditorDialog(db, window)
    tmpl_editor._add_node(NodeType.INFO)
    tmpl_editor._add_node(NodeType.CHECKLIST)
    tmpl_editor._add_node(NodeType.QUESTION)
    tmpl_editor._add_option()
    app.processEvents()
    tmpl_editor._meta_name.setText("Dynamic Template Test")
    tmpl_editor._meta_version.setText("1.0.0")
    raw_yaml, tmpl_obj = tmpl_editor._validate_and_build()
    assert tmpl_obj is not None
    assert tmpl_obj.name == "Dynamic Template Test"

    # 14. Test Report Generation and ExportWorker
    print("[14] Testing Markdown Report Generation...")
    from hackmind.engine.report_exporter import generate_markdown_report
    md_report = generate_markdown_report(db, project.id)
    assert len(md_report) > 0
    print("    Report generated successfully length:", len(md_report))

    # 15. Test Close Project and Return to Welcome
    print("[15] Testing Close Project...")
    window._close_project()
    app.processEvents()
    assert window._state.project is None

    # 16. Test Re-open Project from Welcome
    print("[16] Testing Re-opening project...")
    window._open_project_by_id(project.id)
    app.processEvents()
    assert window._state.project is not None
    assert window._state.project.id == project.id

    print("\n>>> ALL DYNAMIC TESTS PASSED WITH ZERO CRASHES! <<<")


if __name__ == "__main__":
    run_dynamic_tests()
