"""
Template loading and validation for HackMind.

Templates are YAML files that define the methodology tree: node types,
question options, and which subtrees to spawn for each answer.

Public API
----------
    load_template_from_file(path)  -> Template
    load_template_from_string(src) -> Template
    load_template_from_db_row(raw, source_file) -> Template

All three raise TemplateValidationError with a descriptive message if
the template is malformed.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import yaml

from hackmind.models.types import NodeType, Template, TemplateNode, TemplateOption

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class TemplateValidationError(Exception):
    """Raised when a template file fails validation."""


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------

def load_template_from_file(path: Path) -> Template:
    """Parse and validate a YAML template file."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TemplateValidationError(f"Cannot read template file: {exc}") from exc
    return load_template_from_string(source, source_file=str(path))


def load_template_from_string(source: str, source_file: str | None = None) -> Template:
    """Parse and validate a YAML string."""
    try:
        data = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        raise TemplateValidationError(f"Invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise TemplateValidationError("Template must be a YAML mapping at the top level.")

    return _parse_template(data, source_file=source_file)


def load_template_from_db_row(raw_yaml: str, source_file: str | None = None) -> Template:
    """Re-hydrate a template that was stored in the database."""
    return load_template_from_string(raw_yaml, source_file=source_file)


# ---------------------------------------------------------------------------
# Internal parsing
# ---------------------------------------------------------------------------

_REQUIRED_TOP_LEVEL = ("name", "version", "nodes")
_VALID_NODE_TYPES = {t.value for t in NodeType}


def _parse_template(data: dict, source_file: str | None) -> Template:
    _require_fields(data, _REQUIRED_TOP_LEVEL, context="template root")

    seen_ids: set[str] = set()
    nodes = [_parse_node(n, seen_ids, context="nodes") for n in _as_list(data, "nodes")]

    tier = str(data.get("tier", "asset"))
    if tier not in ("engagement", "asset"):
        raise TemplateValidationError(
            f"Invalid tier '{tier}'. Must be 'engagement' or 'asset'."
        )

    return Template(
        id=str(uuid.uuid4()),
        name=str(data["name"]),
        version=str(data["version"]),
        author=str(data.get("author", "unknown")),
        description=str(data.get("description", "")),
        tier=tier,
        nodes=nodes,
        source_file=source_file,
    )


def _parse_node(raw: Any, seen_ids: set[str], context: str) -> TemplateNode:
    if not isinstance(raw, dict):
        raise TemplateValidationError(
            f"Each node must be a mapping (got {type(raw).__name__}) in {context}."
        )

    _require_fields(raw, ("id", "type", "title"), context=f"node in {context}")

    node_id = str(raw["id"])
    node_type_str = str(raw["type"])

    if node_type_str not in _VALID_NODE_TYPES:
        raise TemplateValidationError(
            f"Unknown node type '{node_type_str}' for node '{node_id}'. "
            f"Valid types: {', '.join(sorted(_VALID_NODE_TYPES))}."
        )

    if node_id in seen_ids:
        raise TemplateValidationError(
            f"Duplicate node ID '{node_id}'. All node IDs must be unique within a template."
        )
    seen_ids.add(node_id)

    node_type = NodeType(node_type_str)

    if node_type == NodeType.QUESTION:
        return _parse_question_node(raw, node_id, seen_ids, context)
    else:
        return _parse_non_question_node(raw, node_id, node_type, seen_ids, context)


def _parse_question_node(
    raw: dict, node_id: str, seen_ids: set[str], context: str
) -> TemplateNode:
    if "children" in raw and raw["children"]:
        raise TemplateValidationError(
            f"Question node '{node_id}' should use 'options', not 'children'. "
            "Children are defined per-option."
        )

    if "options" not in raw or not raw["options"]:
        raise TemplateValidationError(
            f"Question node '{node_id}' must have at least one option."
        )

    seen_keys: set[str] = set()
    options = []
    for opt_raw in raw["options"]:
        if not isinstance(opt_raw, dict):
            raise TemplateValidationError(
                f"Each option in node '{node_id}' must be a mapping."
            )
        _require_fields(opt_raw, ("label", "key"), context=f"option in node '{node_id}'")
        if not isinstance(opt_raw["key"], str):
            raise TemplateValidationError(
                f"Option key '{opt_raw['key']}' in node '{node_id}' must be a string. "
                "Wrap boolean-like values in quotes (e.g., key: \"yes\" not key: yes)."
            )
        key = opt_raw["key"]
        if key in seen_keys:
            raise TemplateValidationError(
                f"Duplicate option key '{key}' in question node '{node_id}'."
            )
        seen_keys.add(key)

        children = [
            _parse_node(c, seen_ids, context=f"option '{key}' of '{node_id}'")
            for c in _as_list(opt_raw, "children")
        ]
        options.append(TemplateOption(label=str(opt_raw["label"]), key=key, children=children))

    scope_tags = [str(t) for t in (raw.get("scope_tags") or [])]
    return TemplateNode(
        id=node_id,
        type=NodeType.QUESTION,
        title=str(raw["title"]),
        content=str(raw.get("content", "")),
        options=options,
        scope_tags=scope_tags,
    )


def _parse_non_question_node(
    raw: dict, node_id: str, node_type: NodeType, seen_ids: set[str], context: str
) -> TemplateNode:
    if "options" in raw and raw["options"]:
        raise TemplateValidationError(
            f"Non-question node '{node_id}' (type '{node_type.value}') "
            "cannot have 'options'. Use 'children' instead."
        )

    children = [
        _parse_node(c, seen_ids, context=f"children of '{node_id}'")
        for c in _as_list(raw, "children")
    ]

    scope_tags = [str(t) for t in (raw.get("scope_tags") or [])]
    return TemplateNode(
        id=node_id,
        type=node_type,
        title=str(raw["title"]),
        content=str(raw.get("content", "")),
        children=children,
        scope_tags=scope_tags,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_fields(data: dict, fields: tuple | list, context: str) -> None:
    for field in fields:
        if field not in data:
            raise TemplateValidationError(
                f"Missing required field '{field}' in {context}."
            )


def _as_list(data: dict, key: str) -> list:
    """Return data[key] as a list, or [] if absent/null."""
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise TemplateValidationError(
            f"Field '{key}' must be a list (got {type(value).__name__})."
        )
    return value
