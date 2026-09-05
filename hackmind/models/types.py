"""
Core data types for HackMind.

These are plain Python dataclasses — no Qt, no DB imports.
Both the engine and the UI layer use these as their shared language.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class NodeType(Enum):
    QUESTION = "question"
    CHECKLIST = "checklist"
    ASSET = "asset"
    INFO = "info"


class NodeStatus(Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    VULNERABLE = "vulnerable"
    NOT_APPLICABLE = "not_applicable"

    # Display labels used in the UI
    def label(self) -> str:
        return {
            NodeStatus.NOT_STARTED: "Not Started",
            NodeStatus.IN_PROGRESS: "In Progress",
            NodeStatus.COMPLETE: "Complete",
            NodeStatus.VULNERABLE: "Vulnerable",
            NodeStatus.NOT_APPLICABLE: "N/A",
        }[self]


class AssetType(Enum):
    WEBAPP = "webapp"
    API = "api"
    MOBILE = "mobile"
    SUBDOMAIN = "subdomain"
    HOST = "host"
    SERVICE = "service"
    OTHER = "other"

    def label(self) -> str:
        return {
            AssetType.WEBAPP: "Web Application",
            AssetType.API: "API",
            AssetType.MOBILE: "Mobile App",
            AssetType.SUBDOMAIN: "Subdomain",
            AssetType.HOST: "Host",
            AssetType.SERVICE: "Service",
            AssetType.OTHER: "Other",
        }[self]


# ---------------------------------------------------------------------------
# Project-level types (persisted to DB)
# ---------------------------------------------------------------------------

@dataclass
class Project:
    name: str
    target_name: str
    template_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    variables: dict[str, str] = field(default_factory=dict)


@dataclass
class Node:
    project_id: str
    type: NodeType
    title: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_id: Optional[str] = None
    template_node_id: Optional[str] = None
    template_id: Optional[str] = None      # which DB template this node came from
    content: str = ""
    status: NodeStatus = NodeStatus.NOT_STARTED
    is_finding: bool = False
    soft_deleted: bool = False
    position: int = 0
    created_at: Optional[datetime] = None

    scope_tags: list[str] = field(default_factory=list)

    # Populated at runtime (not persisted directly)
    children: list[Node] = field(default_factory=list, repr=False)
    derived_status: Optional[NodeStatus] = field(default=None, repr=False)


@dataclass
class Note:
    node_id: str
    content: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    updated_at: Optional[datetime] = None


@dataclass
class Attachment:
    node_id: str
    filename: str
    mime_type: str
    data: Optional[bytes] = None
    relative_path: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: Optional[datetime] = None


@dataclass
class QuestionAnswer:
    node_id: str
    option_key: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    answered_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Template types (in-memory only, loaded from YAML)
# ---------------------------------------------------------------------------

@dataclass
class TemplateOption:
    """One answer choice on a question node."""
    label: str
    key: str
    children: list[TemplateNode] = field(default_factory=list)


@dataclass
class TemplateNode:
    id: str
    type: NodeType
    title: str
    content: str = ""
    # Question nodes use options; all other nodes use children directly.
    options: list[TemplateOption] = field(default_factory=list)
    children: list[TemplateNode] = field(default_factory=list)
    scope_tags: list[str] = field(default_factory=list)


@dataclass
class Template:
    id: str
    name: str
    version: str
    author: str
    description: str
    tier: str = "asset"           # "engagement" | "asset"
    nodes: list[TemplateNode] = field(default_factory=list)
    source_file: Optional[str] = None

    # Flattened lookup for O(1) access to any node in the tree.
    # Keyed by TemplateNode.id.
    _nodes_lookup: dict[str, TemplateNode] = field(default_factory=dict, init=False, repr=False)

    def initialize_lookup(self) -> None:
        """Populate the internal O(1) lookup table from the tree structure."""
        self._nodes_lookup = {}
        self._walk_and_index(self.nodes)

    def get_node(self, node_id: str) -> Optional[TemplateNode]:
        """Return a node by ID in O(1) time."""
        return self._nodes_lookup.get(node_id)

    def _walk_and_index(self, nodes: list[TemplateNode]) -> None:
        for tnode in nodes:
            self._nodes_lookup[tnode.id] = tnode
            for opt in tnode.options:
                self._walk_and_index(opt.children)
            self._walk_and_index(tnode.children)
