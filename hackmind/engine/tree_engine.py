"""
Tree engine for HackMind.

Responsible for translating template definitions into live DB node trees
and for managing the tree as the tester answers questions and adds assets.

Public API
----------
  instantiate_project(db, project_id)
      Create the initial "Target Scope" INFO node for a new project.

  add_asset(db, project_id, parent_node_id, title, template_id=None)
      Add a discovered asset node. If template_id is provided, the chosen
      template is instantiated directly under the new asset.

  add_node(db, project_id, parent_node_id, node_type, title, content="")
      Add a manually-created node as a child of any existing node.
      Manual nodes are not tied to any template and survive template exports.

  answer_asset_type(db, question_node_id, db_template_id)
      Record the asset-type answer and instantiate the chosen template
      under the asset node.

  answer_question(db, question_node_id, option_key)
      Record an answer and expand/restore/soft-delete subtrees accordingly.
      The template is resolved from the node's stored template_id.

  clear_question(db, question_node_id)
      Clear the current answer to a question and soft-delete its children.
"""

from __future__ import annotations

import json

from hackmind.db import node_repo, template_repo
from hackmind.db.database import Database
from hackmind.engine.template_loader import load_template_from_db_row
from hackmind.models.types import (
    Node,
    NodeType,
    Template,
    TemplateNode,
)

# Sentinel template_node_id for the bootstrap "Asset type?" question.
ASSET_TYPE_NODE_ID = "__asset_type__"

# Title shown to the user for the bootstrap question.
_ASSET_TYPE_QUESTION_TITLE = "What type of asset is this?"

# Display order when sorting spawned siblings: questions first, then info, then checklists.
_TYPE_SORT_ORDER: dict[NodeType, int] = {
    NodeType.QUESTION:  0,
    NodeType.INFO:      1,
    NodeType.CHECKLIST: 2,
    NodeType.ASSET:     3,
}


def _sort_tnodes(tnodes: list[TemplateNode]) -> list[TemplateNode]:
    return sorted(tnodes, key=lambda t: _TYPE_SORT_ORDER.get(t.type, 99))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def instantiate_project(db: Database, project_id: str, target_name: str) -> None:
    """
    Create the root asset node for a new project, named after the target.
    No bootstrap question — the root is a container, not a typed asset.
    """
    root = Node(
        project_id=project_id,
        parent_id=None,
        type=NodeType.ASSET,
        title=target_name,
        position=0,
    )
    node_repo.insert_node(db, root)


def add_asset(
    db: Database,
    project_id: str,
    parent_node_id: str | None,
    title: str,
    template_id: str | None = None,
) -> Node:
    """
    Create an asset node. If *template_id* is provided, the chosen methodology
    template is instantiated directly under the new asset.
    """
    siblings = (
        node_repo.get_children(db, parent_node_id)
        if parent_node_id
        else node_repo.get_project_nodes(db, project_id)
    )
    asset_node = Node(
        project_id=project_id,
        parent_id=parent_node_id,
        type=NodeType.ASSET,
        title=title,
        position=len(siblings),
    )
    node_repo.insert_node(db, asset_node)

    if template_id is not None:
        raw = template_repo.get_template_raw(db, template_id)
        if raw is None:
            raise ValueError(f"Template '{template_id}' not found in DB.")
        template = load_template_from_db_row(raw)
        for i, tnode in enumerate(_sort_tnodes(template.nodes)):
            _instantiate_node(
                db, project_id, tnode,
                parent_id=asset_node.id, position=i,
                template_id=template_id,
            )

    return asset_node


def add_node(
    db: Database,
    project_id: str,
    parent_node_id: str,
    node_type: NodeType,
    title: str,
    content: str = "",
) -> Node:
    """
    Add a manually-created node as a child of parent_node_id.
    Manual nodes have no template_id or template_node_id — they are not tied
    to any template and are included verbatim in template exports.
    """
    siblings = node_repo.get_children(db, parent_node_id)
    node = Node(
        project_id=project_id,
        parent_id=parent_node_id,
        type=node_type,
        title=title,
        content=content,
        position=len(siblings),
    )
    node_repo.insert_node(db, node)
    return node


def answer_asset_type(
    db: Database,
    question_node_id: str,
    db_template_id: str,
) -> None:
    """
    Record the asset-type selection and instantiate the chosen template
    directly under the asset node that owns the bootstrap question.

    `db_template_id` is the PK of a row in the templates table.

    Three cases:
      1. First answer  → load template, instantiate nodes under the asset.
      2. Answer changed → soft-delete current children, instantiate new ones
                          (or restore if previously selected).
      3. Answer reverted → restore the previously soft-deleted subtree.
    """
    question_node = node_repo.get_node(db, question_node_id)
    if question_node is None:
        raise ValueError(f"Node '{question_node_id}' not found.")

    current_answer = node_repo.get_answer(db, question_node_id)

    # Nothing to do if the same template is re-selected.
    if current_answer is not None and current_answer.option_key == db_template_id:
        return

    # Soft-delete currently active children (previous template nodes).
    if current_answer is not None:
        active_children = node_repo.get_children(
            db, question_node_id, include_soft_deleted=False
        )
        for child in active_children:
            node_repo.soft_delete_subtree(db, child.id)

    # Check whether we can restore a previously soft-deleted subtree.
    soft_children = [
        c for c in node_repo.get_children(
            db, question_node_id, include_soft_deleted=True
        )
        if c.soft_deleted and c.template_id == db_template_id
    ]

    if soft_children:
        for child in soft_children:
            node_repo.restore_subtree(db, child.id)
    else:
        # Instantiate the template fresh.
        raw = template_repo.get_template_raw(db, db_template_id)
        if raw is None:
            raise ValueError(f"Template '{db_template_id}' not found in DB.")
        template = load_template_from_db_row(raw)

        for i, tnode in enumerate(_sort_tnodes(template.nodes)):
            _instantiate_node(
                db, question_node.project_id, tnode,
                parent_id=question_node_id, position=i,
                template_id=db_template_id,
            )

    node_repo.set_answer(db, question_node_id, db_template_id)


def answer_question(
    db: Database,
    question_node_id: str,
    option_key: str,
) -> None:
    """
    Record the tester's answer to a regular (non-bootstrap) question node
    and update the tree.

    The template is loaded from the DB using the node's stored template_id.

    Three cases handled:
      1. First answer   → instantiate children from the selected option.
      2. Answer changed → soft-delete current children; instantiate or
                          restore children for the new option.
      3. Answer reverted → restore previously soft-deleted children.
    """
    question_node = node_repo.get_node(db, question_node_id)
    if question_node is None:
        raise ValueError(f"Node '{question_node_id}' not found.")

    if question_node.template_id is None:
        raise ValueError(
            f"Node '{question_node_id}' has no template_id; "
            "cannot resolve question options."
        )

    raw = template_repo.get_template_raw(db, question_node.template_id)
    if raw is None:
        raise ValueError(
            f"Template '{question_node.template_id}' not found in DB."
        )
    template = load_template_from_db_row(raw)

    tnode = _find_template_node(template, question_node.template_node_id)
    if tnode is None:
        raise ValueError(
            f"Template node '{question_node.template_node_id}' not found "
            f"in template '{question_node.template_id}'."
        )

    selected_option = next(
        (opt for opt in tnode.options if opt.key == option_key), None
    )
    if selected_option is None:
        raise ValueError(
            f"Option key '{option_key}' not found in template node '{tnode.id}'."
        )

    current_answer = node_repo.get_answer(db, question_node_id)

    # Nothing to do if the same option is selected again.
    if current_answer is not None and current_answer.option_key == option_key:
        return

    # Soft-delete all currently active children (from the previous answer).
    if current_answer is not None:
        active_children = node_repo.get_children(
            db, question_node_id, include_soft_deleted=False
        )
        for child in active_children:
            node_repo.soft_delete_subtree(db, child.id)

    # Try to restore a previously soft-deleted subtree for this option.
    if selected_option.children:
        expected_ids = {tn.id for tn in selected_option.children}
        all_children = node_repo.get_children(
            db, question_node_id, include_soft_deleted=True
        )
        restorable = [
            c for c in all_children
            if c.soft_deleted and c.template_node_id in expected_ids
        ]

        if len(restorable) == len(expected_ids):
            for child in restorable:
                node_repo.restore_subtree(db, child.id)
        else:
            for i, child_tnode in enumerate(_sort_tnodes(selected_option.children)):
                _instantiate_node(
                    db, question_node.project_id, child_tnode,
                    parent_id=question_node_id, position=i,
                    template_id=question_node.template_id,
                )

    node_repo.set_answer(db, question_node_id, option_key)


def resync_scope_tags(db: Database) -> None:
    """
    Propagate scope_tags from each template's current YAML onto the DB nodes
    that were instantiated from it.

    Called on startup so that scope_tags added to a bundled template after a
    project was created are reflected on the existing nodes without requiring
    the user to recreate the project.
    """
    # Find all unique template_ids referenced by live nodes.
    rows = db.conn.execute(
        """
        SELECT DISTINCT template_id FROM nodes
         WHERE template_id IS NOT NULL AND template_node_id IS NOT NULL
           AND soft_deleted = 0
        """
    ).fetchall()

    for row in rows:
        tid = row["template_id"]
        raw = template_repo.get_template_raw(db, tid)
        if raw is None:
            continue
        try:
            template = load_template_from_db_row(raw)
        except Exception:
            continue

        # Build template_node_id → scope_tags mapping for this template.
        tag_map: dict[str, list[str]] = {}
        _collect_scope_tags(template.nodes, tag_map)

        if not any(tag_map.values()):
            continue  # Template has no scope_tags — nothing to update.

        # Update nodes whose stored scope_tags differ from the template.
        node_rows = db.conn.execute(
            """
            SELECT id, template_node_id, scope_tags FROM nodes
             WHERE template_id = ? AND template_node_id IS NOT NULL
            """,
            (tid,),
        ).fetchall()

        with db.conn:
            for nr in node_rows:
                desired = tag_map.get(nr["template_node_id"], [])
                current = json.loads(nr["scope_tags"] or "[]")
                if desired != current:
                    db.conn.execute(
                        "UPDATE nodes SET scope_tags = ? WHERE id = ?",
                        (json.dumps(desired), nr["id"]),
                    )


def _collect_scope_tags(tnodes: list[TemplateNode], out: dict[str, list[str]]) -> None:
    for tnode in tnodes:
        out[tnode.id] = tnode.scope_tags
        for opt in tnode.options:
            _collect_scope_tags(opt.children, out)
        _collect_scope_tags(tnode.children, out)


def clear_question(db: Database, question_node_id: str) -> None:
    """
    Clear the current answer to a question and soft-delete its active children.
    The children are preserved in the DB (soft-deleted) so they can be
    restored if the same answer is selected again.
    """
    active_children = node_repo.get_children(
        db, question_node_id, include_soft_deleted=False
    )
    for child in active_children:
        node_repo.soft_delete_subtree(db, child.id)
    node_repo.clear_answer(db, question_node_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _instantiate_node(
    db: Database,
    project_id: str,
    tnode: TemplateNode,
    parent_id: str | None,
    position: int,
    template_id: str | None = None,
) -> Node:
    """
    Create a single DB node from a TemplateNode.
    Recursively creates children for non-question nodes.
    Question nodes are left childless until answered.
    """
    node = Node(
        project_id=project_id,
        parent_id=parent_id,
        type=tnode.type,
        title=tnode.title,
        content=tnode.content,
        template_node_id=tnode.id,
        template_id=template_id,
        position=position,
        scope_tags=list(tnode.scope_tags),
    )
    node_repo.insert_node(db, node)

    # Question children are lazy; all other children are eager.
    if tnode.type != NodeType.QUESTION:
        for i, child in enumerate(_sort_tnodes(tnode.children)):
            _instantiate_node(
                db, project_id, child,
                parent_id=node.id, position=i,
                template_id=template_id,
            )

    return node


def _find_template_node(
    template: Template, template_node_id: str | None
) -> TemplateNode | None:
    """Recursively search the template tree for a node by ID."""
    if template_node_id is None:
        return None
    for tnode in template.nodes:
        found = _search_node(tnode, template_node_id)
        if found:
            return found
    return None


def _search_node(tnode: TemplateNode, target_id: str) -> TemplateNode | None:
    if tnode.id == target_id:
        return tnode
    for opt in tnode.options:
        for child in opt.children:
            found = _search_node(child, target_id)
            if found:
                return found
    for child in tnode.children:
        found = _search_node(child, target_id)
        if found:
            return found
    return None
