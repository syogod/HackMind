# HackMind Template Reference

This note summarizes how HackMind templates work, how template files are loaded and instantiated, and how live trees are exported back to YAML.

## 1. Purpose

HackMind templates are YAML documents that define methodology trees for engagements and assets. They are used to instantiate structured checklists, question branches, informational sections, and asset hierarchies inside a project.

## 2. Template file structure

Top-level fields:
- `name` (required)
- `version` (required)
- `author` (optional)
- `description` (optional)
- `tier` (optional): `asset` or `engagement`; defaults to `asset`
- `nodes` (required): list of top-level nodes

Example:

```yaml
name: My Template
version: "1.0.0"
author: Your Name
description: Short description
tier: asset
nodes:
  - id: root
    type: asset
    title: Target
    children:
      - id: recon
        type: checklist
        title: Reconnaissance
        content: |
          - Enumerate subdomains
          - Identify tech stack
      - id: auth_question
        type: question
        title: Authentication mechanism?
        options:
          - key: jwt
            label: JWT
            children:
              - id: jwt_checks
                type: checklist
                title: JWT Security Checks
                content: |
                  - Test none algorithm
                  - Test RS256→HS256 confusion
          - key: none
            label: No authentication
            children: []
```

> Note: the top-level key must be `nodes:` (a list of root nodes), not `tree:`. This is validated by `hackmind/engine/template_loader.py`.

## 3. Supported node types

The `type` field must be one of:
- `asset` — a container node, can hold children, can host sub-assets
- `checklist` — leaf/note item with status, notes, attachments
- `info` — informational node, read-only
- `question` — branching node with `options`

## 4. Question nodes

Question nodes cannot use `children` directly. They must use `options`.
Each option requires:
- `label` (display text)
- `key` (unique string identifier)
- `children` (list of subtree nodes for that choice)

Example:

```yaml
- id: q_api
  type: question
  title: Does the target expose an API?
  options:
    - label: Yes
      key: yes
      children:
        - id: api_checklist
          type: checklist
          title: API Testing
          content: |-
            - Enumerate endpoints
    - label: No
      key: no
      children: []
```

## 5. Template validation rules

Validation is performed by `hackmind/engine/template_loader.py`.

Key rules:
- Top-level YAML must be a mapping
- Required top-level fields: `name`, `version`, `nodes`
- Each node must have `id`, `type`, `title`
- Node `type` must be one of `question`, `checklist`, `asset`, `info`
- Node IDs must be unique across the entire template tree
- `question` nodes must have non-empty `options`
- `question` nodes must not have `children`
- Non-question nodes must not have `options`
- `scope_tags` may be present on any node and is parsed as a list

## 6. Template tiers

Tier determines where the template is offered in the UI:
- `asset` templates appear in the Add Sub-Asset picker
- `engagement` templates appear in the New Project engagement type picker

Bundled templates are defined in `main.py` via `_BUNDLED_TEMPLATES`.

## 7. How templates are instantiated

The tree engine is in `hackmind/engine/tree_engine.py`.

Important behavior:
- New project root asset is created in `instantiate_project()`
- If an engagement `template_id` is provided, its top-level nodes are instantiated under the root asset
- When adding a new asset, `add_asset()` can instantiate a chosen `asset` template under the new asset node
- `TemplateNode` objects are converted to DB `Node` records with `template_id` and `template_node_id` references
- Non-question children are instantiated eagerly
- Question children are instantiated lazily only after the question is answered

## 8. Question answering semantics

When a user answers a template question:
- `answer_question()` records the answer in `node_repo` answer table
- Existing active children are soft-deleted
- If the selected option was used previously, the subtree is restored from soft-deleted rows
- Otherwise, the selected option's children are instantiated fresh
- If the `question` node has no `template_id`, it cannot resolve options and raises

The asset type is chosen up front when adding an asset: `add_asset(..., template_id=...)`
instantiates the chosen template's top-level nodes directly under the new asset node
(there is no separate bootstrap "Asset type?" question).

## 9. Soft delete / restoring behavior

The engine preserves previous branches using soft-delete.
This means:
- Changing an answer hides the prior branch rather than permanently removing it
- Re-selecting a previously selected answer restores the old branch with its notes/status
- This also means exported templates can retain inactive branches if they were originally present in the template

## 10. Template export behavior

Template export is in `hackmind/engine/template_exporter.py`.

Key points:
- `export_asset_subtree()` exports the current asset subtree as YAML
- Exported nodes keep original `template_node_id` values when available
- Manually-created nodes get generated IDs derived from titles
- For question nodes:
  - the active option's children come from the live DB tree, preserving manual additions
  - inactive options are re-exported from the original template YAML so all options remain
- If the original template is missing, a manual question exports only the active branch
- The layout uses literal block style for multiline `content`

## 11. Template persistence

Templates are stored in the DB as raw YAML in `hackmind/db/template_repo.py`.

Behavior:
- `store_template()` inserts or updates by template ID
- Bundled templates are refreshed on startup by `main.py` using `name+version`
- Deleting a template from the library does not affect existing project nodes
- Existing live nodes keep their `template_id` reference, though raw YAML may be gone if the template row is deleted

## 12. UI integration

UI flows in `hackmind/ui/main_window.py`:
- Import template: user selects `.yaml` file, loader validates it, then stores it in the DB
- Export template: user picks metadata, `export_asset_subtree()` generates YAML, loader validates the generated YAML, then saves it to the library and optionally to disk
- Template editor dialog allows browsing and deleting stored templates

## 13. Recommended template authoring notes

- Always include `name`, `version`, and `nodes`
- Use stable `id` values for reusable nodes, especially questions
- Use `key` values in question options to represent semantic choices, not display text
- Keep `tier` explicit when the template should be engagement-level
- Prefer `asset` templates for per-target methodology
- Use `scope_tags` for filtering by domain and later runtime scope selection
- Keep question options distinct and avoid duplicate `key` values

## 14. Useful files to inspect

- `hackmind/engine/template_loader.py` — validation and parsing rules
- `hackmind/engine/tree_engine.py` — project/asset instantiation and question branching
- `hackmind/engine/template_exporter.py` — export logic for live tree → YAML
- `hackmind/db/template_repo.py` — persisted template storage
- `main.py` — bundled template import and refresh logic
- `tests/test_template_loader.py` — loader validation coverage
- `tests/test_tree_engine.py` — question and asset instantiation behavior


