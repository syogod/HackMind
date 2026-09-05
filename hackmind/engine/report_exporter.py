"""
Evidence-to-report exporter for HackMind.

Generates a Markdown report summarizing findings, notes, and attachment references.
If *export_dir* is provided, referenced attachment files are copied into a
".attachments/" folder next to the report so the links stay valid wherever
the report is saved or shared.
"""

import shutil
from datetime import datetime
from pathlib import Path

from hackmind.db import node_repo, project_repo, attachment_repo
from hackmind.db.database import Database
from hackmind.models.types import NodeStatus


def _copy_attachment(db: Database, att, export_dir: Path) -> str | None:
    """
    Copy an attachment file into <export_dir>/.attachments/<relative_path>.
    Return the relative link path, or None if the source file is missing.
    """
    src = db.attachments_dir / att.relative_path
    if not src.is_file():
        return None
    dest = export_dir / ".attachments" / att.relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.stat().st_size != src.stat().st_size:
        shutil.copy2(src, dest)
    return f".attachments/{att.relative_path}"


def generate_markdown_report(
    db: Database,
    project_id: str,
    export_dir: Path | None = None,
) -> str:
    """
    Generate a full Markdown report for the given project.

    1. Executive Summary: Count findings by severity.
    2. Vulnerability Details: Detailed notes and attachments for each finding.

    If *export_dir* is given, attachment files are copied to
    <export_dir>/.attachments/ and the report links to them relatively.
    """
    project = project_repo.get_project(db, project_id)
    if not project:
        return "# Project Not Found"

    # Get all nodes that are not soft-deleted
    all_nodes = node_repo.get_project_nodes(db, project_id, include_soft_deleted=False)
    
    # Identify findings (explicit findings or status is VULNERABLE)
    findings = [n for n in all_nodes if n.is_finding or n.status == NodeStatus.VULNERABLE]

    report = []
    report.append(f"# Pentest Report: {project.name}")
    report.append(f"**Target:** {project.target_name}")
    report.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("\n---\n")

    # Order findings by severity (critical first) for a professional layout.
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

    def _node_severity(node) -> str:
        for tag in node.scope_tags:
            if tag.lower() in severity_rank:
                return tag.lower()
        return "info"

    findings.sort(key=lambda n: severity_rank[_node_severity(n)])

    # 1. Executive Summary
    report.append("## 1. Executive Summary")
    report.append(f"Total Findings Identified: **{len(findings)}**")
    report.append("\n### Findings by Severity")
    
    severity_counts = {s: 0 for s in severity_rank}
    for f in findings:
        severity_counts[_node_severity(f)] += 1
            
    report.append("| Severity | Count |")
    report.append("| :--- | :--- |")
    for sev in ("critical", "high", "medium", "low", "info"):
        count = severity_counts[sev]
        if count > 0:
            report.append(f"| {sev.capitalize()} | {count} |")
    
    report.append("\n---\n")

    # 2. Vulnerability Details
    report.append("## 2. Vulnerability Details")
    
    if not findings:
        report.append("_No findings identified._")
    else:
        for i, f in enumerate(findings, start=1):
            severity = _node_severity(f).capitalize()
            report.append(f"### F-{i:02d} — {f.title}")
            report.append(f"**Severity:** {severity}")
            
            # Note content
            note = node_repo.get_note(db, f.id)
            if note and note.content.strip():
                report.append("\n#### Description & Evidence")
                report.append(note.content)
            else:
                report.append("\n_No detailed notes provided._")
            
            # 4. Attachment References
            attachments = attachment_repo.get_attachments_for_node(db, f.id, include_data=False)
            if attachments:
                report.append("\n#### Attachments")
                for att in attachments:
                    link_path = f".attachments/{att.relative_path}"
                    if export_dir is not None:
                        copied = _copy_attachment(db, att, export_dir)
                        if copied is not None:
                            link_path = copied
                    report.append(f"- [{att.filename}]({link_path})")
            
            report.append("\n---\n")

    return "\n".join(report)
