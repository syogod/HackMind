"""
Tests for hackmind/engine/template_exporter.py
"""

import pytest
from hackmind.db import node_repo, template_repo
from hackmind.db.database import Database
from hackmind.engine.template_exporter import (
    bump_version,
    export_asset_subtree,
    find_primary_template_meta,
)
from hackmind.engine.template_loader import load_template_from_string
from hackmind.engine.tree_engine import add_asset, add_node, answer_asset_type, answer_question
from hackmind.models.types import NodeType, Project


def test_bump_version() -> None:
    assert bump_version("1.0.0") == "1.0.1"
    assert bump_version("2.1.9") == "2.1.10"
    assert bump_version("1") == "2"
    assert bump_version("beta") == "beta.1"


def test_export_asset_subtree_and_reimport(db: Database, project: Project) -> None:
    # 1. Create a template in DB
    yaml_src = """
name: "Export Test Base"
version: "1.0.0"
author: "Tester"
description: "Base template"
tier: "asset"
nodes:
  - id: sec_info
    type: info
    title: "Recon Section"
    children:
      - id: check_dns
        type: checklist
        title: "Check DNS"
  - id: auth_q
    type: question
    title: "Uses OAuth?"
    options:
      - label: "Yes"
        key: "yes"
        children:
          - id: check_oauth
            type: checklist
            title: "Test OAuth Redirect"
      - label: "No"
        key: "no"
        children: []
"""
    tmpl = load_template_from_string(yaml_src)
    template_repo.store_template(db, tmpl, yaml_src)

    # 2. Add asset with template
    asset = add_asset(db, project.id, None, "Export Asset", template_id=tmpl.id)

    # Add a manual checklist node under sec_info
    info_node = next(n for n in node_repo.get_children(db, asset.id) if n.template_node_id == "sec_info")
    add_node(db, project.id, info_node.id, NodeType.CHECKLIST, "Manual Port Scan", "Check open ports")

    # Find primary meta
    meta = find_primary_template_meta(db, asset.id)
    assert meta is not None
    assert meta["name"] == "Export Test Base"

    # Export subtree
    exported_yaml = export_asset_subtree(
        db,
        asset.id,
        name="Exported Custom Template",
        version="1.0.1",
        author="Custom Author",
        description="Exported description",
    )

    assert "Exported Custom Template" in exported_yaml
    assert "1.0.1" in exported_yaml
    assert "Manual Port Scan" in exported_yaml
    assert "check_dns" in exported_yaml
    assert "Uses OAuth?" in exported_yaml

    # Validate that the exported YAML loads without errors
    reimported = load_template_from_string(exported_yaml)
    assert reimported.name == "Exported Custom Template"
    assert reimported.version == "1.0.1"
    assert len(reimported.nodes) == 2
