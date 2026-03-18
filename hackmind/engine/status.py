"""
Status derivation for HackMind.

Parent node statuses are never stored — they are always computed from
their children. This module provides two entry points:

  compute_project_statuses(db, project_id)
      Loads all nodes for a project once and derives all statuses in a
      single in-memory pass. Use this when loading the full project tree.

  derive_node_status(node_id, all_nodes, answers)
      Derives status for a single node given a pre-loaded flat list.
      Called by compute_project_statuses internally.

Derivation rules
----------------
  Leaf nodes:
    - Question node, unanswered  → NOT_STARTED
    - Question node, answered    → COMPLETE  (question is done, children carry progress)
    - All other types            → node's manually set status

  Parent nodes (have active children):
    - All children N/A           → NOT_APPLICABLE
    - Any child VULNERABLE       → VULNERABLE
    - All non-N/A children COMPLETE → COMPLETE
    - All non-N/A children NOT_STARTED → NOT_STARTED
    - Otherwise                  → IN_PROGRESS
"""

from __future__ import annotations

from hackmind.db import node_repo
from hackmind.db.database import Database
from hackmind.models.types import Node, NodeStatus, NodeType


def compute_project_statuses(
    db: Database, project_id: str
) -> dict[str, NodeStatus]:
    """
    Return a mapping of {node_id: derived_status} for every active node
    in the project. Loads data once; no recursive DB queries.
    """
    nodes = node_repo.get_project_nodes(db, project_id, include_soft_deleted=False)
    answers = node_repo.get_answers_for_project(db, project_id)
    return _derive_all(nodes, answers)


def _derive_all(
    nodes: list[Node], answers: dict[str, str]
) -> dict[str, NodeStatus]:
    """Pure function — derives all statuses from flat node list + answers."""
    node_map = {n.id: n for n in nodes}
    children_map: dict[str | None, list[Node]] = {}
    for n in nodes:
        children_map.setdefault(n.parent_id, []).append(n)

    memo: dict[str, NodeStatus] = {}

    def derive(node_id: str) -> NodeStatus:
        if node_id in memo:
            return memo[node_id]

        node = node_map[node_id]
        children = children_map.get(node_id, [])

        if not children:
            status = _leaf_status(node, answers)
        else:
            child_statuses = [derive(c.id) for c in children]
            status = _combine(child_statuses)

        memo[node_id] = status
        return status

    for node in nodes:
        if node.id not in memo:
            derive(node.id)

    return memo


def _leaf_status(node: Node, answers: dict[str, str]) -> NodeStatus:
    if node.type == NodeType.QUESTION:
        return NodeStatus.COMPLETE if node.id in answers else NodeStatus.NOT_STARTED
    return node.status


def _combine(statuses: list[NodeStatus]) -> NodeStatus:
    """Combine a list of child statuses into a single parent status."""
    relevant = [s for s in statuses if s != NodeStatus.NOT_APPLICABLE]

    if not relevant:
        return NodeStatus.NOT_APPLICABLE

    if any(s == NodeStatus.VULNERABLE for s in relevant):
        return NodeStatus.VULNERABLE

    if all(s == NodeStatus.COMPLETE for s in relevant):
        return NodeStatus.COMPLETE

    if all(s == NodeStatus.NOT_STARTED for s in relevant):
        return NodeStatus.NOT_STARTED

    return NodeStatus.IN_PROGRESS
