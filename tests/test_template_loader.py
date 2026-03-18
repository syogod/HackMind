"""
Tests for engine/template_loader.py and db/template_repo.py
"""

import textwrap
from pathlib import Path

import pytest

from hackmind.db.database import Database
from hackmind.db.template_repo import (
    delete_template,
    get_template_raw,
    list_templates,
    store_template,
)
from hackmind.engine.template_loader import (
    TemplateValidationError,
    load_template_from_file,
    load_template_from_string,
)
from hackmind.models.types import NodeType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_VALID = textwrap.dedent("""\
    name: "Test Template"
    version: "1.0.0"
    author: "tester"
    description: "A minimal template"
    nodes:
      - id: root
        type: question
        title: "Root question?"
        options:
          - label: "Yes"
            key: "yes"
            children: []
          - label: "No"
            key: "no"
            children: []
""")

WEB_APP_YAML = Path("templates/web-app.yaml")


# ---------------------------------------------------------------------------
# Happy path — loading
# ---------------------------------------------------------------------------

def test_load_minimal_valid_template() -> None:
    t = load_template_from_string(MINIMAL_VALID)
    assert t.name == "Test Template"
    assert t.version == "1.0.0"
    assert t.author == "tester"
    assert len(t.nodes) == 1


def test_load_produces_unique_id_each_time() -> None:
    t1 = load_template_from_string(MINIMAL_VALID)
    t2 = load_template_from_string(MINIMAL_VALID)
    assert t1.id != t2.id


def test_load_question_node_has_options() -> None:
    t = load_template_from_string(MINIMAL_VALID)
    root = t.nodes[0]
    assert root.type == NodeType.QUESTION
    assert len(root.options) == 2
    assert root.options[0].key == "yes"
    assert root.options[1].key == "no"


def test_load_nested_children() -> None:
    src = textwrap.dedent("""\
        name: "Nested"
        version: "1.0.0"
        nodes:
          - id: q1
            type: question
            title: "Question?"
            options:
              - label: "Yes"
                key: "yes"
                children:
                  - id: child1
                    type: checklist
                    title: "Do a thing"
                  - id: child2
                    type: checklist
                    title: "Do another thing"
              - label: "No"
                key: "no"
                children: []
    """)
    t = load_template_from_string(src)
    yes_option = t.nodes[0].options[0]
    assert len(yes_option.children) == 2
    assert yes_option.children[0].id == "child1"
    assert yes_option.children[1].id == "child2"


def test_load_checklist_node_with_children() -> None:
    src = textwrap.dedent("""\
        name: "T"
        version: "1"
        nodes:
          - id: parent
            type: info
            title: "Parent"
            children:
              - id: child
                type: checklist
                title: "Child task"
    """)
    t = load_template_from_string(src)
    assert len(t.nodes[0].children) == 1
    assert t.nodes[0].children[0].type == NodeType.CHECKLIST


def test_load_from_file(tmp_path: Path) -> None:
    f = tmp_path / "t.yaml"
    f.write_text(MINIMAL_VALID, encoding="utf-8")
    t = load_template_from_file(f)
    assert t.name == "Test Template"
    assert t.source_file == str(f)


def test_load_bundled_web_app_template() -> None:
    """The real web-app.yaml must parse without errors."""
    t = load_template_from_file(WEB_APP_YAML)
    assert t.name == "Web Application Testing"
    assert len(t.nodes) > 0


def test_web_app_template_has_auth_question() -> None:
    t = load_template_from_file(WEB_APP_YAML)
    ids = _collect_ids(t.nodes)
    assert "q_auth" in ids
    assert "q_file_upload" in ids
    assert "q_api" in ids


def test_web_app_template_no_duplicate_ids() -> None:
    t = load_template_from_file(WEB_APP_YAML)
    ids = _collect_ids(t.nodes)
    # If load succeeded without exception, IDs are unique.
    # This just double-checks via the returned data.
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

def test_missing_name_raises() -> None:
    src = "version: '1'\nnodes: []"
    with pytest.raises(TemplateValidationError, match="name"):
        load_template_from_string(src)


def test_missing_version_raises() -> None:
    src = "name: 'T'\nnodes: []"
    with pytest.raises(TemplateValidationError, match="version"):
        load_template_from_string(src)


def test_missing_nodes_raises() -> None:
    src = "name: 'T'\nversion: '1'"
    with pytest.raises(TemplateValidationError, match="nodes"):
        load_template_from_string(src)


def test_invalid_node_type_raises() -> None:
    src = textwrap.dedent("""\
        name: T
        version: 1
        nodes:
          - id: n1
            type: banana
            title: Bad node
    """)
    with pytest.raises(TemplateValidationError, match="Unknown node type"):
        load_template_from_string(src)


def test_duplicate_node_id_raises() -> None:
    src = textwrap.dedent("""\
        name: T
        version: 1
        nodes:
          - id: dupe
            type: checklist
            title: First
          - id: dupe
            type: checklist
            title: Second
    """)
    with pytest.raises(TemplateValidationError, match="Duplicate node ID"):
        load_template_from_string(src)


def test_duplicate_node_id_across_nesting_raises() -> None:
    src = textwrap.dedent("""\
        name: T
        version: 1
        nodes:
          - id: q1
            type: question
            title: Q
            options:
              - label: Yes
                key: "yes"
                children:
                  - id: q1
                    type: checklist
                    title: Dupe inside child
              - label: No
                key: "no"
                children: []
    """)
    with pytest.raises(TemplateValidationError, match="Duplicate node ID"):
        load_template_from_string(src)


def test_question_node_without_options_raises() -> None:
    src = textwrap.dedent("""\
        name: T
        version: 1
        nodes:
          - id: q1
            type: question
            title: No options here
    """)
    with pytest.raises(TemplateValidationError, match="at least one option"):
        load_template_from_string(src)


def test_question_node_with_children_instead_of_options_raises() -> None:
    src = textwrap.dedent("""\
        name: T
        version: 1
        nodes:
          - id: q1
            type: question
            title: Q
            children:
              - id: c1
                type: checklist
                title: Child
    """)
    with pytest.raises(TemplateValidationError, match="options"):
        load_template_from_string(src)


def test_non_question_node_with_options_raises() -> None:
    src = textwrap.dedent("""\
        name: T
        version: 1
        nodes:
          - id: c1
            type: checklist
            title: C
            options:
              - label: Yes
                key: yes
                children: []
    """)
    with pytest.raises(TemplateValidationError, match="cannot have 'options'"):
        load_template_from_string(src)


def test_duplicate_option_key_raises() -> None:
    src = textwrap.dedent("""\
        name: T
        version: 1
        nodes:
          - id: q1
            type: question
            title: Q
            options:
              - label: Yes
                key: "yes"
                children: []
              - label: Also Yes
                key: "yes"
                children: []
    """)
    with pytest.raises(TemplateValidationError, match="Duplicate option key"):
        load_template_from_string(src)


def test_missing_node_id_raises() -> None:
    src = textwrap.dedent("""\
        name: T
        version: 1
        nodes:
          - type: checklist
            title: No ID here
    """)
    with pytest.raises(TemplateValidationError, match="'id'"):
        load_template_from_string(src)


def test_invalid_yaml_raises() -> None:
    with pytest.raises(TemplateValidationError, match="Invalid YAML"):
        load_template_from_string("{ bad yaml: [unclosed")


def test_non_mapping_yaml_raises() -> None:
    with pytest.raises(TemplateValidationError, match="mapping"):
        load_template_from_string("- just a list")


def test_load_from_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(TemplateValidationError, match="Cannot read"):
        load_template_from_file(tmp_path / "nonexistent.yaml")


# ---------------------------------------------------------------------------
# Template repo
# ---------------------------------------------------------------------------

def test_store_and_retrieve_template(db: Database) -> None:
    t = load_template_from_string(MINIMAL_VALID)
    store_template(db, t, MINIMAL_VALID)
    raw = get_template_raw(db, t.id)
    assert raw == MINIMAL_VALID


def test_get_template_raw_returns_none_for_missing(db: Database) -> None:
    assert get_template_raw(db, "nonexistent-id") is None


def test_list_templates_returns_metadata(db: Database) -> None:
    t = load_template_from_string(MINIMAL_VALID)
    store_template(db, t, MINIMAL_VALID)
    templates = list_templates(db)
    assert len(templates) == 1
    assert templates[0]["name"] == "Test Template"
    assert "data" not in templates[0]  # raw YAML not included in list


def test_delete_template(db: Database) -> None:
    t = load_template_from_string(MINIMAL_VALID)
    store_template(db, t, MINIMAL_VALID)
    delete_template(db, t.id)
    assert get_template_raw(db, t.id) is None


def test_store_template_replaces_existing(db: Database) -> None:
    t = load_template_from_string(MINIMAL_VALID)
    store_template(db, t, MINIMAL_VALID)
    updated_yaml = MINIMAL_VALID.replace("Test Template", "Updated Template")
    store_template(db, t, updated_yaml)
    raw = get_template_raw(db, t.id)
    assert "Updated Template" in raw


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_ids(nodes) -> list[str]:
    """Recursively collect all node IDs from a list of TemplateNodes."""
    ids = []
    for node in nodes:
        ids.append(node.id)
        for opt in node.options:
            ids.extend(_collect_ids(opt.children))
        ids.extend(_collect_ids(node.children))
    return ids
