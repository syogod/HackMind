"""
Template exporter for HackMind.

Walks the live node tree rooted at an asset and produces a YAML template
string that can be stored as a new (independent) template.

Rules:
- Template-originated nodes keep their original template_node_id as the
  exported YAML id (guaranteeing stable references).
- Manually-added nodes (template_node_id is None) get a slug derived from
  their title, de-duplicated with a counter if needed.
- Question nodes: the active option's children come from the live tree
  (so manual additions to that branch are preserved); inactive option
  branches are copied verbatim from the original template YAML so the
  full question structure is retained.
- The original template is never modified; the export always produces a
  brand-new template with a fresh UUID assigned on import.

Public API
----------
    export_asset_subtree(db, asset_node_id, name, version, author, description)
        -> str  (raw YAML ready to pass to load_template_from_string / store)

    find_primary_template_meta(db, asset_node_id)
        -> dict | None  ({id, name, version, ...}) for pre-filling the dialog

    bump_version(version)
        -> str  e.g. "1.0.2" -> "1.0.3"
"""

from __future__ import annotations

import re

import yaml

from hackmind.db import node_repo, template_repo
from hackmind.db.database import Database
from hackmind.engine.template_loader import load_template_from_db_row
from hackmind.models.types import Node, NodeType, Template, TemplateNode


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def bump_version(version: str) -> str:
    """Increment the last numeric component: '1.0.2' → '1.0.3'."""
    parts = version.strip().split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except (ValueError, IndexError):
        return version + ".1"
    return ".".join(parts)


def find_primary_template_meta(db: Database, asset_node_id: str) -> dict | None:
    """
    Return metadata dict for the template most used by this asset's children,
    or None if the asset has no template-originated nodes.
    """
    children = node_repo.get_children(db, asset_node_id)
    for child in children:
        if child.template_id:
            rows = template_repo.list_templates(db)
            return next((r for r in rows if r["id"] == child.template_id), None)
    return None


def export_asset_subtree(
    db: Database,
    asset_node_id: str,
    name: str,
    version: str,
    author: str,
    description: str = "",
) -> str:
    """
    Walk the live (non-soft-deleted) subtree of *asset_node_id* and return
    a YAML string representing a new standalone template.
    """
    exporter = _Exporter(db)
    root_children = node_repo.get_children(db, asset_node_id)
    nodes_list = [exporter.export_node(c) for c in root_children]

    doc: dict = {
        "name": name,
        "version": version,
        "author": author,
    }
    if description:
        doc["description"] = description
    doc["nodes"] = nodes_list

    return yaml.dump(
        doc,
        Dumper=_LiteralDumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


# ---------------------------------------------------------------------------
# YAML dumper with literal block scalars for multiline strings
# ---------------------------------------------------------------------------

class _LiteralDumper(yaml.Dumper):
    pass


def _literal_str(dumper: yaml.Dumper, data: str) -> yaml.ScalarNode:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_LiteralDumper.add_representer(str, _literal_str)


# ---------------------------------------------------------------------------
# Exporter class (stateful: tracks used IDs across the whole tree)
# ---------------------------------------------------------------------------

class _Exporter:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._used_ids: set[str] = set()
        self._template_cache: dict[str, Template] = {}

    # ------------------------------------------------------------------
    # Template cache
    # ------------------------------------------------------------------

    def _get_template(self, template_id: str) -> Template | None:
        if template_id not in self._template_cache:
            raw = template_repo.get_template_raw(self._db, template_id)
            if raw:
                self._template_cache[template_id] = load_template_from_db_row(raw)
        return self._template_cache.get(template_id)

    # ------------------------------------------------------------------
    # ID management
    # ------------------------------------------------------------------

    def _claim_id(self, candidate: str) -> str:
        """Return *candidate* if unused, otherwise append _2, _3, … until unique."""
        if candidate not in self._used_ids:
            self._used_ids.add(candidate)
            return candidate
        i = 2
        while True:
            unique = f"{candidate}_{i}"
            if unique not in self._used_ids:
                self._used_ids.add(unique)
                return unique
            i += 1

    def _id_for(self, node: Node) -> str:
        if node.template_node_id:
            return self._claim_id(node.template_node_id)
        slug = re.sub(r"[^a-z0-9_]", "_", node.title.lower()).strip("_")[:40] or "node"
        return self._claim_id(slug)

    # ------------------------------------------------------------------
    # Core export
    # ------------------------------------------------------------------

    def export_node(self, node: Node) -> dict:
        d: dict = {
            "id": self._id_for(node),
            "type": node.type.value,
            "title": node.title,
        }
        if node.content:
            d["content"] = node.content

        if node.type == NodeType.QUESTION:
            d["options"] = self._build_options(node)
        else:
            children = node_repo.get_children(self._db, node.id)
            if children:
                d["children"] = [self.export_node(c) for c in children]

        return d

    def _build_options(self, qnode: Node) -> list[dict]:
        answer = node_repo.get_answer(self._db, qnode.id)
        active_key = answer.option_key if answer else None

        # Try to get full option list from the original template.
        original_options: list = []
        if qnode.template_id and qnode.template_node_id:
            tmpl = self._get_template(qnode.template_id)
            if tmpl:
                tnode = _find_in_template(tmpl, qnode.template_node_id)
                if tnode:
                    original_options = tnode.options

        if original_options:
            result = []
            for opt in original_options:
                opt_d: dict = {"label": opt.label, "key": opt.key}
                if opt.key == active_key:
                    # Active branch: use live children (may contain manual nodes).
                    live = node_repo.get_children(self._db, qnode.id)
                    opt_d["children"] = [self.export_node(c) for c in live]
                else:
                    # Inactive branch: preserve from original template as-is.
                    opt_d["children"] = self._tnodes_to_dicts(opt.children)
                result.append(opt_d)
            return result

        # No original template found (manual question): export active branch only.
        if active_key:
            live = node_repo.get_children(self._db, qnode.id)
            return [{
                "label": active_key,
                "key": active_key,
                "children": [self.export_node(c) for c in live],
            }]

        # Unanswered manual question: emit a placeholder to keep YAML valid.
        return [{"label": "Not answered", "key": "not_answered", "children": []}]

    def _tnodes_to_dicts(self, tnodes: list[TemplateNode]) -> list[dict]:
        """Serialise original TemplateNode objects (inactive branches) back to dicts."""
        result = []
        for tnode in tnodes:
            d: dict = {
                "id": self._claim_id(tnode.id),
                "type": tnode.type.value,
                "title": tnode.title,
            }
            if tnode.content:
                d["content"] = tnode.content
            if tnode.type == NodeType.QUESTION:
                d["options"] = [
                    {
                        "label": opt.label,
                        "key": opt.key,
                        "children": self._tnodes_to_dicts(opt.children),
                    }
                    for opt in tnode.options
                ]
            else:
                if tnode.children:
                    d["children"] = self._tnodes_to_dicts(tnode.children)
            result.append(d)
        return result


# ---------------------------------------------------------------------------
# Template-tree search helper
# ---------------------------------------------------------------------------

def _find_in_template(template: Template, node_id: str) -> TemplateNode | None:
    def _search(tnode: TemplateNode) -> TemplateNode | None:
        if tnode.id == node_id:
            return tnode
        for opt in tnode.options:
            for child in opt.children:
                found = _search(child)
                if found:
                    return found
        for child in tnode.children:
            found = _search(child)
            if found:
                return found
        return None

    for root in template.nodes:
        found = _search(root)
        if found:
            return found
    return None
