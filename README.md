# HackMind

A desktop pentesting methodology assistant. Load a structured checklist template for your engagement, answer branching questions to filter out irrelevant sections, track progress node by node, and take notes and attach evidence directly to each item — all stored in a single local SQLite file.

---

## Features

- **Methodology templates** — YAML-based trees in two tiers:
  - *Engagement templates* (program-level recon): Bug Bounty Program, Internal Penetration Test, Red Team Operation.
  - *Asset templates* (per-target methodology): Web App, Android Mobile, Thick Client, API Security (OWASP API Top 10 + bug bounty extras).
  - Import your own or build custom ones with the built-in template editor.
- **Branching questionnaires** — Question nodes narrow the methodology to what's actually in scope (e.g., "Does the API use JWT?" spawns a JWT-specific checklist; answering "No" hides it entirely).
- **Per-node notes & attachments** — Freeform notes with auto-save and file attachments on every checklist item.
- **Scope filtering** — Tag nodes and filter the tree to a specific scope (e.g., only show items relevant to `authentication`).
- **Multiple assets per project** — Add sub-assets (discovered domains, APIs, services) under the root target, each with its own template instance.
- **Findings tracking** — Mark any checklist item as a finding for quick review; set status to **Vulnerable** when an issue is confirmed.
- **Portable data** — Everything lives in one `.db` file. Back it up, move it, or share it by copying that file.

---

## Requirements

- Python 3.11 or newer
- Windows, macOS, or Linux

---

## Installation

### Option 1 — Run from source

**Windows**

```bat
git clone https://github.com/syogod/HackMind.git
cd HackMind
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

**macOS / Linux (including Kali)**

> Modern Debian-based distros (Kali, Ubuntu 23.04+) block system-wide `pip` installs — a virtual environment is required.

```bash
git clone https://github.com/syogod/HackMind.git
cd HackMind

# Kali/Debian may need this first if python3-venv is missing:
# sudo apt install python3-venv

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

The virtual environment only needs to be created once. On subsequent runs, just use `.venv/bin/python main.py` from the repo directory.

### Option 2 — Build a standalone executable (PyInstaller)

A standalone build requires no Python installation on the target machine.

```bash
# Activate your venv first, then:
pip install -r requirements-dev.txt

# Windows
pyinstaller --onefile --windowed --add-data "templates;templates" --name HackMind main.py

# macOS / Linux
pyinstaller --onefile --windowed --add-data "templates:templates" --name HackMind main.py
```

The output executable is placed in `dist/`. Copy `dist/HackMind` (or `dist/HackMind.exe`) to any machine and run it — no Python required.

> **Note:** On macOS, `--windowed` produces a `.app` bundle. On Linux, omit `--windowed` if you encounter display issues under some desktop environments.

---

## First Run

On the first launch, HackMind automatically imports the bundled methodology templates. No manual import step is needed.

The database is created at:

| Platform | Default path |
|----------|-------------|
| Windows  | `%USERPROFILE%\HackMind Projects\hackmind.db` |
| macOS    | `~/HackMind Projects/hackmind.db` |
| Linux    | `~/HackMind Projects/hackmind.db` |

The path can be changed at any time via **File → Settings**.

---

## Usage

### Creating a project

1. Launch HackMind — the welcome screen lists recent projects.
2. Click **New Project…**, enter a project name (e.g., `ACME Corp Penetration Test`) and a root target (e.g., `acme.com`).
3. Optionally select an **Engagement Type** (e.g., *Bug Bounty Program* or *Internal Penetration Test*) — this loads a program-level recon checklist at the project root. Leave blank for a plain project with no top-level template.
4. The project opens with the root asset selected. From the **Add Sub-Asset** panel on the right, give the asset a name, choose an asset template, and click **Add Asset**.

### Navigating the tree

- The left panel shows the full methodology tree for the open project.
- Click any node to open its detail panel on the right.
- Use the **search box** to filter nodes by title.
- Use **Scope…** to restrict the tree to tagged sections.
- Check **Hide Completed** to focus on remaining work.

### Answering questions

Question nodes branch the methodology. Click a question in the tree to see the answer options. Choosing an answer spawns the relevant sub-tree and soft-deletes irrelevant branches (no data is lost — re-answering the question restores them).

### Tracking progress

Each checklist node has a status selector:

| Status | Meaning |
|--------|---------|
| Not Started | Default |
| In Progress | Actively being tested |
| Complete | Tested, no finding |
| Vulnerable | Vulnerability identified |
| N/A | Not applicable |

Status changes are reflected immediately in the tree (colour-coded icons).

Use the **Mark as Finding** checkbox to flag a node for quick review independently of its status.

### Notes and attachments

Every node has a **Notes** tab with an auto-saving text editor, and an **Attachments** tab where you can drag-and-drop or browse to attach screenshots, burp exports, etc.

### Templates

**Importing a custom template:**
`File → Import Template…` — select any `.yaml` file following the template format.

**Editing templates:**
`File → Template Editor…` — browse, view, and delete templates stored in the library.

**Exporting a template:**
Right-click an asset node in the tree → **Export as Template…** — exports the current node's methodology subtree (including any structural changes you've made) as a reusable YAML template.

---

## Template Format

Templates are YAML files. The basic structure:

```yaml
name: My Template
version: "1.0.0"
author: Your Name
description: Short description
tier: asset          # "asset" (default) or "engagement"

tree:
  id: root
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

**Node types:**
- `asset` — container node (can hold children, can have sub-assets added to it)
- `checklist` — leaf node with a status, notes, and attachments
- `info` — read-only informational node
- `question` — branching node; uses `options` instead of `children`

**Template tiers:**
- `asset` — shown in the *Add Sub-Asset* template picker; applied per target (default)
- `engagement` — shown in the *New Project* engagement type picker; loaded at the project root to provide program-level recon steps

---

## Settings

`File → Settings…` (or `Ctrl+,`):

| Setting | Description |
|---------|-------------|
| Database path | Where the `.db` file is stored. Takes effect on restart. |
| Note auto-save delay | How long after the last keystroke before notes are saved (100–5000 ms). |
| Theme | UI colour theme. Applied immediately. |

Themes can also be switched without opening Settings via **View → Theme**. Available themes: Dark, Dracula, Solarized Dark, Light, Matrix, Nord, Monokai.

---

## Data & Backup

All data is stored in the single `.db` file. To back up a project: copy the file. To move to another machine: copy the file and point the Settings path to its new location.

---

## Development

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
pytest

# Run from source
python main.py
```

Adding a new bundled template: place the `.yaml` file in `templates/` and add its path to `_BUNDLED_TEMPLATES` in [main.py](main.py). Set `tier: engagement` for program-level templates or `tier: asset` (or omit it) for per-target templates.
