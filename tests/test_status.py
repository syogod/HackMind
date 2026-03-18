"""
Tests for engine/status.py

Tests status derivation both in isolation (_combine rules) and
end-to-end through compute_project_statuses using the tree engine.
"""

import textwrap

import pytest

from hackmind.db import node_repo, template_repo
from hackmind.db.database import Database
from hackmind.db.project_repo import create_project
from hackmind.engine.status import _combine, compute_project_statuses
from hackmind.engine.template_loader import load_template_from_string
from hackmind.engine.tree_engine import (
    add_asset,
    answer_asset_type,
    answer_question,
    instantiate_project,
)
from hackmind.models.types import NodeStatus, Project

TEMPLATE_SRC = textwrap.dedent("""\
    name: "Test"
    version: "1.0.0"
    nodes:
      - id: root_question
        type: question
        title: "What type?"
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


@pytest.fixture
def db_template_id(db: Database) -> str:
    template = load_template_from_string(TEMPLATE_SRC)
    template_repo.store_template(db, template, TEMPLATE_SRC)
    return template.id


@pytest.fixture
def proj(db: Database) -> Project:
    return create_project(db, Project(name="T", target_name="t.com", template_id=""))


def _statuses(db, project_id):
    return compute_project_statuses(db, project_id)


def _active_nodes(db, project_id):
    return node_repo.get_project_nodes(db, project_id)


def _node_by_tid(db, project_id, tid):
    return next(
        n for n in node_repo.get_project_nodes(db, project_id)
        if n.template_node_id == tid
    )


def _setup_project(db, proj, db_template_id):
    """Full setup: project root + one asset with template loaded."""
    instantiate_project(db, proj.id, proj.target_name)
    asset = add_asset(db, proj.id, None, "test.com")
    bootstrap_q = node_repo.get_children(db, asset.id)[0]
    answer_asset_type(db, bootstrap_q.id, db_template_id)
    return asset, bootstrap_q


# ---------------------------------------------------------------------------
# _combine unit tests (pure logic, no DB)
# ---------------------------------------------------------------------------

def test_combine_all_not_started():
    assert _combine([NodeStatus.NOT_STARTED] * 3) == NodeStatus.NOT_STARTED


def test_combine_all_complete():
    assert _combine([NodeStatus.COMPLETE] * 3) == NodeStatus.COMPLETE


def test_combine_all_na():
    assert _combine([NodeStatus.NOT_APPLICABLE] * 3) == NodeStatus.NOT_APPLICABLE


def test_combine_any_vulnerable():
    statuses = [NodeStatus.COMPLETE, NodeStatus.VULNERABLE, NodeStatus.IN_PROGRESS]
    assert _combine(statuses) == NodeStatus.VULNERABLE


def test_combine_vulnerable_beats_na():
    statuses = [NodeStatus.NOT_APPLICABLE, NodeStatus.VULNERABLE]
    assert _combine(statuses) == NodeStatus.VULNERABLE


def test_combine_na_ignored_when_others_complete():
    statuses = [NodeStatus.COMPLETE, NodeStatus.NOT_APPLICABLE, NodeStatus.COMPLETE]
    assert _combine(statuses) == NodeStatus.COMPLETE


def test_combine_mix_of_complete_and_not_started():
    statuses = [NodeStatus.COMPLETE, NodeStatus.NOT_STARTED]
    assert _combine(statuses) == NodeStatus.IN_PROGRESS


def test_combine_mix_of_complete_and_in_progress():
    statuses = [NodeStatus.COMPLETE, NodeStatus.IN_PROGRESS]
    assert _combine(statuses) == NodeStatus.IN_PROGRESS


def test_combine_single_in_progress():
    assert _combine([NodeStatus.IN_PROGRESS]) == NodeStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# compute_project_statuses — integration tests
# ---------------------------------------------------------------------------

def test_unanswered_question_is_not_started(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_project(db, proj, db_template_id)
    statuses = _statuses(db, proj.id)
    root = _node_by_tid(db, proj.id, "root_question")
    assert statuses[root.id] == NodeStatus.NOT_STARTED


def test_answered_question_with_no_children_is_complete(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_project(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "webapp")

    auth_q = _node_by_tid(db, proj.id, "auth_question")
    answer_question(db, auth_q.id, "no")  # "no" spawns no children

    statuses = _statuses(db, proj.id)
    assert statuses[auth_q.id] == NodeStatus.COMPLETE


def test_checklist_leaf_defaults_to_not_started(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_project(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "webapp")

    recon = _node_by_tid(db, proj.id, "check_recon")
    statuses = _statuses(db, proj.id)
    assert statuses[recon.id] == NodeStatus.NOT_STARTED


def test_completing_leaf_propagates_up(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_project(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "api")  # only check_api under it

    check_api = _node_by_tid(db, proj.id, "check_api")
    node_repo.set_status(db, check_api.id, NodeStatus.COMPLETE)

    statuses = _statuses(db, proj.id)
    assert statuses[root.id] == NodeStatus.COMPLETE


def test_vulnerable_leaf_propagates_up(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_project(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "webapp")

    recon = _node_by_tid(db, proj.id, "check_recon")
    node_repo.set_status(db, recon.id, NodeStatus.VULNERABLE)

    statuses = _statuses(db, proj.id)
    assert statuses[root.id] == NodeStatus.VULNERABLE


def test_partial_completion_gives_in_progress(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_project(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "webapp")
    auth_q = _node_by_tid(db, proj.id, "auth_question")
    answer_question(db, auth_q.id, "yes")

    recon = _node_by_tid(db, proj.id, "check_recon")
    node_repo.set_status(db, recon.id, NodeStatus.COMPLETE)

    statuses = _statuses(db, proj.id)
    assert statuses[root.id] == NodeStatus.IN_PROGRESS


def test_not_applicable_leaf_excluded_from_parent(
    db: Database, proj: Project, db_template_id: str
) -> None:
    _setup_project(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "webapp")
    auth_q = _node_by_tid(db, proj.id, "auth_question")
    answer_question(db, auth_q.id, "yes")

    recon = _node_by_tid(db, proj.id, "check_recon")
    check_auth = _node_by_tid(db, proj.id, "check_auth")
    node_repo.set_status(db, recon.id, NodeStatus.COMPLETE)
    node_repo.set_status(db, check_auth.id, NodeStatus.NOT_APPLICABLE)

    statuses = _statuses(db, proj.id)
    assert statuses[root.id] == NodeStatus.COMPLETE


def test_soft_deleted_nodes_excluded_from_status(
    db: Database, proj: Project, db_template_id: str
) -> None:
    """Changing answer should not count the old children's statuses."""
    _setup_project(db, proj, db_template_id)
    root = _node_by_tid(db, proj.id, "root_question")
    answer_question(db, root.id, "webapp")

    recon = _node_by_tid(db, proj.id, "check_recon")
    node_repo.set_status(db, recon.id, NodeStatus.VULNERABLE)
    answer_question(db, root.id, "api")

    statuses = _statuses(db, proj.id)
    assert statuses[root.id] != NodeStatus.VULNERABLE
    assert statuses[root.id] == NodeStatus.NOT_STARTED


def test_empty_project_returns_empty_statuses(
    db: Database, proj: Project
) -> None:
    statuses = compute_project_statuses(db, proj.id)
    assert statuses == {}
