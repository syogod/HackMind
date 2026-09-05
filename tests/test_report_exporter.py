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
    assert "### SQL Injection in Login" in report
    assert "**Severity:** Critical" in report
    assert "Found union based SQLi in username field." in report
    assert "[sqli_proof.png](.attachments/" in report
    assert "### Exposed Debug Endpoint" in report
    assert "**Severity:** Medium" in report
    assert "Endpoint at /debug/pprof exposed." in report
