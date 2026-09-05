"""
Tests for hackmind/engine/report_exporter.py
"""

import pytest
from hackmind.db import node_repo, attachment_repo
from hackmind.db.database import Database
from hackmind.engine.report_exporter import generate_markdown_report
from hackmind.models.types import Attachment, Node, NodeStatus, NodeType, Project


def test_generate_markdown_report_nonexistent_project(db: Database) -> None:
    report = generate_markdown_report(db, "nonexistent-id")
    assert report == "# Project Not Found"


def test_generate_markdown_report_empty_project(db: Database, project: Project) -> None:
    report = generate_markdown_report(db, project.id)
    assert f"# Pentest Report: {project.name}" in report
    assert f"**Target:** {project.target_name}" in report
    assert "Total Findings Identified: **0**" in report
    assert "_No findings identified._" in report


def test_generate_markdown_report_with_findings_and_attachments(
    db: Database, project: Project
) -> None:
    # Create vulnerable node
    vulnerable_node = node_repo.insert_node(
        db,
        Node(
            project_id=project.id,
            type=NodeType.CHECKLIST,
            title="SQL Injection in Login",
            status=NodeStatus.VULNERABLE,
            scope_tags=["critical", "injection"],
        ),
    )
    # Save note for the vulnerable node
    node_repo.save_note(db, vulnerable_node.id, "Found union based SQLi in username field.")

    # Create attachment for the vulnerable node
    att = Attachment(
        node_id=vulnerable_node.id,
        filename="sqli_proof.png",
        mime_type="image/png",
        data=b"dummy-png-bytes",
    )
    attachment_repo.insert_attachment(db, att)

    # Create finding flagged node
    finding_node = node_repo.insert_node(
        db,
        Node(
            project_id=project.id,
            type=NodeType.CHECKLIST,
            title="Exposed Debug Endpoint",
            status=NodeStatus.COMPLETE,
            is_finding=True,
            scope_tags=["medium"],
        ),
    )
    node_repo.save_note(db, finding_node.id, "Endpoint at /debug/pprof exposed.")

    report = generate_markdown_report(db, project.id)

    assert "Total Findings Identified: **2**" in report
    assert "| Critical | 1 |" in report
    assert "| Medium | 1 |" in report
    # Critical finding is numbered and sorted first.
    assert "### F-01 — SQL Injection in Login" in report
    assert "**Severity:** Critical" in report
    assert "Found union based SQLi in username field." in report
    assert "[sqli_proof.png](.attachments/" in report
    assert "### F-02 — Exposed Debug Endpoint" in report
    assert "**Severity:** Medium" in report
    assert "Endpoint at /debug/pprof exposed." in report


def test_generate_markdown_report_orders_by_severity(
    db: Database, project: Project
) -> None:
    """Findings are numbered and ordered critical -> info regardless of creation order."""
    node_repo.insert_node(db, Node(project_id=project.id, type=NodeType.CHECKLIST,
                                   title="Low one", status=NodeStatus.VULNERABLE, scope_tags=["low"]))
    node_repo.insert_node(db, Node(project_id=project.id, type=NodeType.CHECKLIST,
                                   title="Critical one", status=NodeStatus.VULNERABLE, scope_tags=["critical"]))
    node_repo.insert_node(db, Node(project_id=project.id, type=NodeType.CHECKLIST,
                                   title="Untagged one", status=NodeStatus.VULNERABLE, scope_tags=[]))

    report = generate_markdown_report(db, project.id)
    i_low = report.index("Low one")
    i_crit = report.index("Critical one")
    i_un = report.index("Untagged one")
    assert i_crit < i_low < i_un  # untagged falls back to Info (last)


def test_set_severity_updates_scope_tags(db: Database, project: Project) -> None:
    """set_severity replaces any existing severity tag, keeping other tags."""
    node = node_repo.insert_node(
        db, Node(project_id=project.id, type=NodeType.CHECKLIST,
                 title="Finding X", status=NodeStatus.VULNERABLE,
                 scope_tags=["sqli", "high"])
    )
    node_repo.set_severity(db, node.id, "critical")
    fetched = node_repo.get_node(db, node.id)
    assert sorted(fetched.scope_tags) == ["critical", "sqli"]

    node_repo.set_severity(db, node.id, "info")
    fetched = node_repo.get_node(db, node.id)
    assert sorted(fetched.scope_tags) == ["info", "sqli"]

    with pytest.raises(ValueError):
        node_repo.set_severity(db, node.id, "banana")


def test_generate_markdown_report_copies_attachments_to_export_dir(
    db: Database, project: Project, tmp_path
) -> None:
    """With export_dir set, attachment files are copied next to the report."""
    vulnerable_node = node_repo.insert_node(
        db,
        Node(
            project_id=project.id,
            type=NodeType.CHECKLIST,
            title="SQL Injection in Login",
            status=NodeStatus.VULNERABLE,
            scope_tags=["critical"],
        ),
    )
    att = Attachment(
        node_id=vulnerable_node.id,
        filename="sqli_proof.png",
        mime_type="image/png",
        data=b"dummy-png-bytes",
    )
    attachment_repo.insert_attachment(db, att)

    export_dir = tmp_path / "report_output"
    export_dir.mkdir()
    report = generate_markdown_report(db, project.id, export_dir=export_dir)

    # The copied file exists and the report links to it.
    copied = list((export_dir / ".attachments").rglob("*sqli_proof.png"))
    assert len(copied) == 1
    assert copied[0].read_bytes() == b"dummy-png-bytes"
    rel_link = copied[0].relative_to(export_dir).as_posix()
    assert f"]({rel_link})" in report
