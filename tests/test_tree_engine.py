"""
Tests for engine/tree_engine.py

Uses a small inline template so tests are self-contained and explicit.

Template structure:
  root_question: "What type?"
    option "webapp":
      info_section (always-present info node)
        check_recon   (checklist, child of info_section)
      auth_question: "Auth?"
        option "yes":
          check_auth  (checklist)
        option "no":
          (no children)
    option "api":
      check_api (checklist)

New flow:
  1. instantiate_project → creates "Target Scope" INFO node
  2. add_asset → creates asset node + bootstrap "Asset type?" question
  3. answer_asset_type → loads template under the bootstrap question
  4. answer_question → expands template question nodes
"""

import textwrap

import pytest

from hackmind.db import node_repo
from hackmind.db import template_repo
from hackmind.db.database import Database
from hackmind.db.project_repo import create_project
from hackmind.engine.template_loader import load_template_from_string
from hackmind.engine.tree_engine import (
    ASSET_TYPE_NODE_ID,
    add_asset,
    answer_asset_type,
    answer_question,
    clear_question,
    instantiate_project,
)
from hackmind.models.types import NodeType, Project

TEMPLATE_SRC = textwrap.dedent("""\
    name: "Test"
    version: "1.0.0"
    nodes:
      - id: root_question
        type: question
        title: "What type of target?"
        options:
          - label: "Web App"
            key: webapp
            children:
              - id: info_section
                type: info
                title: "Web App Testing"
                children:
                  - id: check_recon
                    type: checklist
                    title: "Run recon"

              - id: auth_question
                type: question
                title: "Does target have auth?"
                options:
                  - label: "Yes"
                    key: "yes"
                    children:
                      - id: check_auth
                        type: checklist
                        title: "Test authentication"
                  - label: "No"
                    key: "no"
                    children: []

          - label: "API"
            key: api
            children:
              - id: check_api
                type: checklist
                title: "Test API"
""")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_template_id(db: Database) -> str:
    """Store the test template in DB and return its ID."""
    template = load_template_from_string(TEMPLATE_SRC)
    template_repo.store_template(db, template, TEMPLATE_SRC)
    return template.id


@pytest.fixture
def proj(db: Database) -> Project:
    return create_project(db, Project(name="Test", target_name="t.com", template_id=""))


def _all_project_nodes(db, project_id):
    return node_repo.get_project_nodes(db, project_id, include_soft_deleted=False)


def _all_project_nodes_including_deleted(db, project_id):
    return node_repo.get_project_nodes(db, project_id, include_soft_deleted=True)


def _node_by_tid(db, project_id, tid):
    return next(
        n for n in _all_project_nodes(db, project_id)
        if n.template_node_id == tid
    )


def _setup_asset(db, proj, db_template_id, title="test.com"):
    """Create an asset and load the template via the bootstrap question."""
    asset = add_asset(db, proj.id, None, title)
    bootstrap_q = node_repo.get_children(db, asset.id)[0]
    answer_asset_type(db, bootstrap_q.id, db_template_id)
    return asset, bootstrap_q


# ---------------------------------------------------------------------------
# instantiate_project
# ---------------------------------------------------------------------------

def test_instantiate_creates_target_scope_node(
    db: Database, proj: Project
) -> None:
    instantiate_project(db, proj.id, proj.target_name)
    nodes = _all_project_nodes(db, proj.id)
    assert len(nodes) == 1
    assert nodes[0].type == NodeType.ASSET
    assert nodes[0].title == proj.target_name
    assert nodes[0].parent_id is None


def test_instantiate_creates_no_template_nodes(
    db: Database, proj: Project
) -> None:
    instantiate_project(db, proj.id, proj.target_name)
    nodes = _all_project_nodes(db, proj.id)
    assert all(n.template_id is None for n in nodes)


# ---------------------------------------------------------------------------
# add_asset
# ---------------------------------------------------------------------------

def test_add_asset_creates_asset_node(
    db: Database, proj: Project
) -> None:
    asset = add_asset(db, proj.id, None, "api.example.com")
    fetched = node_repo.get_node(db, asset.id)
    assert fetched is not None
    assert fetched.type == NodeType.ASSET
    assert fetched.title == "api.example.com"


def test_add_asset_spawns_bootstrap_question(
    db: Database, proj: Project
) -> None:
    asset = add_asset(db, proj.id, None, "test.com")
    children = node_repo.get_children(db, asset.id)
    assert len(children) == 1
    assert children[0].type == NodeType.QUESTION
    assert children[0].template_node_id == ASSET_TYPE_NODE_ID


def test_two_assets_have_independent_bootstrap_questions(
    db: Database, proj: Project
) -> None:
    asset1 = add_asset(db, proj.id, None, "a.com")
    asset2 = add_asset(db, proj.id, None, "b.com")

    q1 = node_repo.get_children(db, asset1.id)[0]
    q2 = node_repo.get_children(db, asset2.id)[0]

    assert q1.id != q2.id


def test_add_asset_positions_increment(
    db: Database, proj: Project
) -> None:
    from hackmind.models.types import Node
    parent = node_repo.insert_node(
        db, Node(project_id=proj.id, type=NodeType.INFO, title="Root")
    )
    a1 = add_asset(db, proj.id, parent.id, "first.com")
    a2 = add_asset(db, proj.id, parent.id, "second.com")
    assert a1.position == 0
    assert a2.position == 1


# ---------------------------------------------------------------------------
# answer_asset_type
# ---------------------------------------------------------------------------

def test_answer_asset_type_instantiates_template(
    db: Database, proj: Project, db_template_id: str
) -> None:
    asset, bootstrap_q = _setup_asset(db, proj, db_template_id)
    nodes = _all_project_nodes(db, proj.id)
    tids = {n.template_node_id for n in nodes}
    assert "root_question" in tids


def test_answer_asset_type_records_answer(
    db: Database, proj: Project, db_template_id: str
) -> None:
    asset, bootstrap_q = _setup_asset(db, proj, db_template_id)
    ans = node_repo.get_answer(db, bootstrap_q.id)
    assert ans is not None
    assert ans.option_key == db_template_id


def test_answer_asset_type_sets_template_id_on_nodes(
    db: Database, proj: Project, db_template_id: str
) -> None:
    asset, bootstrap_q = _setup_asset(db, proj, db_template_id)
    nodes = _all_project_nodes(db, proj.id)
    template_nodes = [n for n in nodes if n.template_node_id is not None
                      and n.template_node_id != ASSET_TYPE_NODE_ID]
    assert all(n.template_id == db_template_id for n in template_nodes)


def test_answer_asset_type_same_template_twice_is_idempotent(
    db: Database, proj: Project, db_template_id: str
) -> None:
    asset, bootstrap_q = _setup_asset(db, proj, db_template_id)
    count_after_first = len(_all_project_nodes(db, proj.id))
    answer_asset_type(db, bootstrap_q.id, db_template_id)
    assert len(_all_project_nodes(db, proj.id)) == count_after_first


def test_answer_asset_type_question_only_creates_root_question(
    db: Database, proj: Project, db_template_id: str
) -> None:
    """Question node children should NOT be created until answered."""
    asset, bootstrap_q = _setup_asset(db, proj, db_template_id)
    children = node_repo.get_children(db, bootstrap_q.id)
    # Only root_question — no option children yet
    assert len(children) == 1
    assert children[0].type == NodeType.QUESTION


# ---------------------------------------------------------------------------
# answer_question — first answer
# ---------------------------------------------------------------------------

def test_first_answer_spawns_option_children(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_asset(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "api")

    tids = {n.template_node_id for n in _all_project_nodes(db, proj.id)}
    assert "check_api" in tids


def test_first_answer_records_answer(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_asset(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "webapp")
    ans = node_repo.get_answer(db, root.id)
    assert ans is not None
    assert ans.option_key == "webapp"


def test_answer_creates_info_children_eagerly(
    db: Database, proj: Project, db_template_id: str
) -> None:
    """Non-question children should be created immediately when their parent is created."""
    _setup_asset(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "webapp")

    tids = {n.template_node_id for n in _all_project_nodes(db, proj.id)}
    assert "info_section" in tids
    assert "check_recon" in tids
    assert "auth_question" in tids
    assert "check_auth" not in tids  # lazy: not answered yet


def test_answer_with_no_children_creates_no_nodes(
    db: Database, proj: Project, db_template_id: str
) -> None:
    """Answering a question with an option that has no children is valid."""
    _setup_asset(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "webapp")

    nodes = _all_project_nodes(db, proj.id)
    auth_q = next(n for n in nodes if n.template_node_id == "auth_question")
    before_count = len(nodes)
    answer_question(db, auth_q.id, "no")

    assert len(_all_project_nodes(db, proj.id)) == before_count


# ---------------------------------------------------------------------------
# answer_question — changing answer (soft-delete old children)
# ---------------------------------------------------------------------------

def test_changing_answer_soft_deletes_old_children(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_asset(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")

    answer_question(db, root.id, "webapp")
    answer_question(db, root.id, "api")

    active_tids = {n.template_node_id for n in _all_project_nodes(db, proj.id)}

    assert "check_api" in active_tids
    assert "info_section" not in active_tids
    assert "check_recon" not in active_tids
    assert "auth_question" not in active_tids


def test_changing_answer_old_nodes_remain_soft_deleted(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_asset(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "webapp")
    answer_question(db, root.id, "api")

    all_nodes = _all_project_nodes_including_deleted(db, proj.id)
    deleted_tids = {n.template_node_id for n in all_nodes if n.soft_deleted}
    assert "info_section" in deleted_tids
    assert "check_recon" in deleted_tids


def test_same_answer_twice_is_idempotent(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_asset(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "webapp")
    count_after_first = len(_all_project_nodes(db, proj.id))
    answer_question(db, root.id, "webapp")
    assert len(_all_project_nodes(db, proj.id)) == count_after_first


# ---------------------------------------------------------------------------
# answer_question — reverting to a previous answer (restore)
# ---------------------------------------------------------------------------

def test_reverting_answer_restores_soft_deleted_children(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_asset(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")

    answer_question(db, root.id, "webapp")
    info_node = _node_by_tid(db, proj.id, "info_section")
    original_info_id = info_node.id

    answer_question(db, root.id, "api")
    answer_question(db, root.id, "webapp")  # should restore, not recreate

    restored_info = _node_by_tid(db, proj.id, "info_section")
    assert restored_info.id == original_info_id


def test_reverting_preserves_notes_on_restored_nodes(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_asset(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "webapp")

    recon = _node_by_tid(db, proj.id, "check_recon")
    node_repo.save_note(db, recon.id, "Found something interesting")

    answer_question(db, root.id, "api")
    answer_question(db, root.id, "webapp")

    note = node_repo.get_note(db, recon.id)
    assert note.content == "Found something interesting"


# ---------------------------------------------------------------------------
# clear_question
# ---------------------------------------------------------------------------

def test_clear_question_removes_answer(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_asset(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "webapp")
    clear_question(db, root.id)
    assert node_repo.get_answer(db, root.id) is None


def test_clear_question_soft_deletes_children(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_asset(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "webapp")
    clear_question(db, root.id)

    active = node_repo.get_children(db, root.id, include_soft_deleted=False)
    assert len(active) == 0


def test_clear_then_reanswer_restores_subtree(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_asset(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "webapp")

    info = _node_by_tid(db, proj.id, "info_section")
    original_id = info.id

    clear_question(db, root.id)
    answer_question(db, root.id, "webapp")

    restored = _node_by_tid(db, proj.id, "info_section")
    assert restored.id == original_id


# ---------------------------------------------------------------------------
# Independent asset trees
# ---------------------------------------------------------------------------

def test_two_assets_have_independent_template_trees(
    db: Database, proj: Project, db_template_id: str
) -> None:
    asset1, bq1 = _setup_asset(db, proj, db_template_id, "a.com")
    asset2, bq2 = _setup_asset(db, proj, db_template_id, "b.com")

    rq1_children = node_repo.get_children(db, bq1.id)
    rq2_children = node_repo.get_children(db, bq2.id)

    assert len(rq1_children) == 1
    assert len(rq2_children) == 1
    assert rq1_children[0].id != rq2_children[0].id


def test_answering_question_on_one_asset_does_not_affect_other(
    db: Database, proj: Project, db_template_id: str
) -> None:
    asset1, bq1 = _setup_asset(db, proj, db_template_id, "a.com")
    asset2, bq2 = _setup_asset(db, proj, db_template_id, "b.com")

    rq1 = node_repo.get_children(db, bq1.id)[0]
    answer_question(db, rq1.id, "webapp")

    rq2 = node_repo.get_children(db, bq2.id)[0]
    assert node_repo.get_answer(db, rq2.id) is None
