"""
Tests for UI components: TreeModel, Panels, Dialogs, Themes, Settings.
"""

import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from hackmind.db import node_repo, template_repo, project_repo
from hackmind.db.database import Database
from hackmind.engine.template_loader import load_template_from_string
from hackmind.engine.tree_engine import add_asset, add_node, answer_asset_type, instantiate_project
from hackmind.models.types import Node, NodeStatus, NodeType, Project
from hackmind.ui.app_state import AppState
from hackmind.ui.tree_panel import TreePanel, _QtTreeModel, _ScopeFilterProxy
from hackmind.ui.panels.question_panel import QuestionPanel
from hackmind.ui.panels.checklist_panel import ChecklistPanel
from hackmind.ui.panels.asset_panel import AssetPanel
from hackmind.ui.panels.welcome_panel import WelcomePanel
from hackmind.ui.widgets.note_editor import NoteEditor
from hackmind.ui.widgets.attachment_pane import AttachmentPane
from hackmind.ui.dialogs.add_node_dialog import AddNodeDialog
from hackmind.ui.dialogs.export_template_dialog import ExportTemplateDialog
from hackmind.ui.dialogs.new_project_dialog import NewProjectDialog
from hackmind.ui.dialogs.settings_dialog import SettingsDialog
from hackmind.ui.themes import THEMES, apply_theme


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["pytest", "-platform", "offscreen"])
    return app


def test_tree_model_and_tree_panel(qapp, db: Database, project: Project) -> None:
    yaml_src = """
name: "UI Tree Test"
version: "1.0.0"
author: "Tester"
tier: "asset"
nodes:
  - id: recon_info
    type: info
    title: "Recon Section"
    children:
      - id: check_ssl
        type: checklist
        title: "Check SSL/TLS"
  - id: auth_q
    type: question
    title: "Has Authentication?"
    options:
      - label: "Yes"
        key: "yes"
        children:
          - id: check_creds
            type: checklist
            title: "Check Credentials"
      - label: "No"
        key: "no"
        children: []
"""
    tmpl = load_template_from_string(yaml_src)
    template_repo.store_template(db, tmpl, yaml_src)

    instantiate_project(db, project.id, project.target_name)
    asset = add_asset(db, project.id, None, "Target Asset", template_id=tmpl.id)

    panel = TreePanel()
    panel.load(db, project.id)

    # Check that model loaded all items
    model = panel._model
    assert model.rowCount() == 2 # root target + Target Asset
    assert len(model._item_map) >= 4

    # Select node
    item_id = next(iter(model._item_map.keys()))
    panel.select_node(item_id)
    assert panel._current_node_id() == item_id

    # Test refresh and clear
    panel.refresh(db, project.id)
    panel.clear()
    assert model.rowCount() == 0


def test_question_panel_load_and_options(qapp, db: Database, project: Project) -> None:
    yaml_src = """
name: "Q Panel Test"
version: "1.0.0"
author: "Tester"
tier: "asset"
nodes:
  - id: auth_q
    type: question
    title: "Has 2FA?"
    options:
      - label: "Yes"
        key: "yes"
        children: []
      - label: "No"
        key: "no"
        children: []
"""
    tmpl = load_template_from_string(yaml_src)
    template_repo.store_template(db, tmpl, yaml_src)

    asset = add_asset(db, project.id, None, "Q Asset", template_id=tmpl.id)
    qnode = next(n for n in node_repo.get_children(db, asset.id) if n.template_node_id == "auth_q")

    state = AppState(db=db, project=project)
    qpanel = QuestionPanel(state)
    qpanel.load(qnode)

    # QuestionPanel should have rebuilt options without crashing
    assert qpanel._title.text() == "Has 2FA?"
    assert qpanel._options_layout.count() == 2

    # Answer the question
    qpanel._select("yes")
    ans = node_repo.get_answer(db, qnode.id)
    assert ans is not None
    assert ans.option_key == "yes"


def test_checklist_panel_and_note_editor(qapp, db: Database, project: Project) -> None:
    node = node_repo.insert_node(
        db,
        Node(
            project_id=project.id,
            type=NodeType.CHECKLIST,
            title="Test XSS Protection",
            content="Check input validation and CSP",
        ),
    )

    cpanel = ChecklistPanel(db)
    cpanel.load(node)
    assert cpanel._title.text() == "Test XSS Protection"

    editor = NoteEditor(db)
    editor.load(node.id)
    editor.set_text("Updated note for XSS test")
    editor.flush()

    note = node_repo.get_note(db, node.id)
    assert note.content == "Updated note for XSS test"


def test_attachment_pane(qapp, db: Database, project: Project) -> None:
    node = node_repo.insert_node(
        db,
        Node(
            project_id=project.id,
            type=NodeType.CHECKLIST,
            title="Test Attachment Node",
        ),
    )

    pane = AttachmentPane(db)
    pane.load(node.id)
    assert pane._grid.count() == 0


def test_welcome_panel(qapp, db: Database, project: Project) -> None:
    welcome = WelcomePanel(db)
    welcome.refresh()
    assert welcome._project_list.count() >= 1


def test_themes_apply(qapp) -> None:
    for theme_name in THEMES:
        apply_theme(qapp, theme_name)
