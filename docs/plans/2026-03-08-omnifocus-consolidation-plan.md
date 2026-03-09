# OmniFocus MCP Consolidation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite omnifocus-mcp from Node.js to Python so jd-cli can import it directly, eliminating duplicate JXA code and enabling tag operations on existing projects.

**Architecture:** omnifocus-mcp becomes a Python package exposing an `OmniFocusClient` class (library) and an MCP server (CLI entry point). jd-cli adds it as a dependency and replaces its `omnifocus.py` with imports from `omnifocus_mcp`. The omnifocus plugin's `.mcp.json` is updated to invoke the Python server.

**Tech Stack:** Python 3.10+, `mcp` (FastMCP), `subprocess` for JXA/osascript

**Design doc:** `docs/plans/2026-03-08-omnifocus-consolidation-design.md`

---

### Task 1: Scaffold omnifocus-mcp Python package

**Files:**
- Create: `~/repos/omnifocus-mcp/omnifocus_mcp/__init__.py`
- Create: `~/repos/omnifocus-mcp/omnifocus_mcp/client.py`
- Create: `~/repos/omnifocus-mcp/omnifocus_mcp/server.py`
- Create: `~/repos/omnifocus-mcp/pyproject.toml`

**Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "omnifocus-mcp"
version = "2.0.0"
description = "MCP server and Python library for OmniFocus"
requires-python = ">=3.10"
dependencies = ["mcp>=1.0"]
license = "MIT"
authors = [{ name = "Nelson Love" }]

[project.scripts]
omnifocus-mcp = "omnifocus_mcp.server:main"
```

**Step 2: Create `__init__.py`**

```python
from omnifocus_mcp.client import OmniFocusClient, OmniFocusError

__all__ = ["OmniFocusClient", "OmniFocusError"]
```

**Step 3: Create stub `client.py` with JXA runner and error class**

```python
"""OmniFocus client — JXA-based access to OmniFocus via osascript."""

import json
import subprocess


class OmniFocusError(Exception):
    """Error communicating with OmniFocus."""


def _run_jxa(script: str) -> str:
    """Run a JXA script and return stdout."""
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise OmniFocusError(result.stderr.strip() or f"osascript exited {result.returncode}")
    return result.stdout.strip()


def _run_jxa_json(script: str):
    """Run a JXA script and parse JSON output."""
    raw = _run_jxa(script)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OmniFocusError(f"Bad JSON from osascript: {exc}\n{raw[:200]}")


def _escape(s: str) -> str:
    """Escape a string for embedding in JXA."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


class OmniFocusClient:
    """Python interface to OmniFocus via JXA."""
    pass  # Methods added in subsequent tasks
```

**Step 4: Create stub `server.py`**

```python
"""MCP server for OmniFocus — exposes OmniFocusClient as MCP tools."""

from mcp.server.fastmcp import FastMCP

from omnifocus_mcp.client import OmniFocusClient

mcp = FastMCP("OmniFocus", json_response=True)
client = OmniFocusClient()


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
```

**Step 5: Commit**

```bash
cd ~/repos/omnifocus-mcp
git add omnifocus_mcp/ pyproject.toml
git commit -m "Scaffold Python package for omnifocus-mcp v2"
```

---

### Task 2: Implement OmniFocusClient read operations

Port the read methods from the Node.js `OmniFocusClient`. These are direct translations of the JXA scripts from `src/omnifocus.js`.

**Files:**
- Modify: `~/repos/omnifocus-mcp/omnifocus_mcp/client.py`

**Step 1: Implement `get_tasks`**

Port `getTasks` from `src/omnifocus.js:29-121`. Accept filters: `project`, `context`, `flagged`, `completed`. Return list of dicts with `id`, `name`, `note`, `flagged`, `completed`, `deferDate`, `dueDate`, `project`, `tags`.

**Step 2: Implement `get_projects`**

Port `getProjects` from `src/omnifocus.js:123-164`. Return list of dicts with `id`, `name`, `note`, `status`, `folder`, `dueDate`, `completionDate`, `tags`. **Important:** include `tags` in the output — the Node.js version omits them, which is why jd-cli has to do a separate query. Add tag names to each project result.

**Step 3: Implement `get_contexts`**

Port `getContexts` from `src/omnifocus.js:686-730`. Return list of dicts with `id`, `name`, `parentTag`, `childTags`.

**Step 4: Implement `get_folders`**

Port `getFolders` from `src/omnifocus.js:815-860`. Return list of dicts with `id`, `name`, `parentFolder`, `projects`, `subfolders`.

**Step 5: Verify reads work**

```bash
cd ~/repos/omnifocus-mcp
pip install -e .
python3 -c "from omnifocus_mcp import OmniFocusClient; c = OmniFocusClient(); print(len(c.get_projects()), 'projects')"
```

**Step 6: Commit**

```bash
git add -A && git commit -m "Implement read operations: get_tasks, get_projects, get_contexts, get_folders"
```

---

### Task 3: Implement OmniFocusClient write operations

Port the create/update/delete methods from `src/omnifocus.js`.

**Files:**
- Modify: `~/repos/omnifocus-mcp/omnifocus_mcp/client.py`

**Step 1: Implement `create_task`**

Port `createTask` from `src/omnifocus.js:328-443`. Accept `name`, `note`, `project`, `parent_task_id`, `context`, `flagged`, `due_date`, `defer_date`.

**Step 2: Implement `create_project`**

Port `createProject` from `src/omnifocus.js:284-326`. Accept `name`, `note`, `folder`, `status`, `due_date`, `tags` (list of tag names to apply).

**Step 3: Implement `update_task`**

Port `updateTask` from `src/omnifocus.js:469-524`. Accept `task_id` + optional `name`, `note`, `flagged`, `due_date`, `defer_date`, `project`, `context`.

**Step 4: Implement `update_project`**

Port `updateProject` from `src/omnifocus.js:573-611`. Accept `project_id` + optional `name`, `note`, `status`, `due_date`.

**Step 5: Implement `complete_task`, `delete_task`**

Port from `src/omnifocus.js:445-467` and `src/omnifocus.js:662-684`.

**Step 6: Commit**

```bash
git add -A && git commit -m "Implement write operations: create/update/delete for tasks and projects"
```

---

### Task 4: Implement tag operations (new functionality)

These are the key new operations that the Node.js version was missing.

**Files:**
- Modify: `~/repos/omnifocus-mcp/omnifocus_mcp/client.py`

**Step 1: Implement `tag_project`**

Add/remove tags on existing projects. Port the logic from `jd-cli/johnnydecimal/omnifocus.py:286-333`.

```python
def tag_project(self, project_name: str, tag_name: str) -> None:
    """Add a tag to an existing project. Creates the tag if needed. Idempotent."""
    # JXA: find project by name, find-or-create tag, add if not present
```

**Step 2: Implement `untag_project`**

```python
def untag_project(self, project_name: str, tag_name: str) -> None:
    """Remove a tag from a project."""
    # JXA: find project, find tag in project's tags, remove it
```

**Step 3: Implement `tag_task` and `untag_task`**

Same pattern but for tasks, using task ID.

**Step 4: Implement `create_tag`**

Port from `jd-cli/johnnydecimal/omnifocus.py:182-205`. Idempotent tag creation.

**Step 5: Implement `open_project`**

Port from `jd-cli/johnnydecimal/omnifocus.py:267-283`. Opens project in OF front window. **Important:** accept a list of project names and open all of them (for multi-match support).

**Step 6: Verify tag operations work**

```bash
python3 -c "
from omnifocus_mcp import OmniFocusClient
c = OmniFocusClient()
c.tag_project('06.10 OmniFocus', 'test-tag')
print('tagged')
c.untag_project('06.10 OmniFocus', 'test-tag')
print('untagged')
"
```

**Step 7: Commit**

```bash
git add -A && git commit -m "Implement tag operations: tag/untag for projects and tasks"
```

---

### Task 5: Wire up MCP server tools

Register all `OmniFocusClient` methods as MCP tools in `server.py`.

**Files:**
- Modify: `~/repos/omnifocus-mcp/omnifocus_mcp/server.py`

**Step 1: Register read tools**

`get_tasks` (with filter params), `get_projects`, `get_contexts`, `get_folders`.

**Step 2: Register write tools**

`create_task`, `create_project`, `update_task`, `update_project`, `complete_task`, `delete_task`.

**Step 3: Register tag tools**

`tag_project` (params: `project_name`, `tag_name`), `untag_project`, `tag_task`, `untag_task`, `create_tag`.

**Step 4: Register utility tools**

`open_project` (param: `name` or list of names).

**Step 5: Verify MCP server starts**

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"capabilities":{}}}' | omnifocus-mcp 2>/dev/null | head -1
```

**Step 6: Commit**

```bash
git add -A && git commit -m "Wire up all OmniFocusClient methods as MCP tools"
```

---

### Task 6: Delete Node.js artifacts from omnifocus-mcp

**Files:**
- Delete: `~/repos/omnifocus-mcp/src/` (entire directory)
- Delete: `~/repos/omnifocus-mcp/package.json`
- Delete: `~/repos/omnifocus-mcp/package-lock.json` (if exists)
- Delete: `~/repos/omnifocus-mcp/node_modules/` (if exists)

**Step 1: Remove Node.js files**

```bash
cd ~/repos/omnifocus-mcp
rm -rf src/ node_modules/ package.json package-lock.json
```

**Step 2: Commit**

```bash
git add -A && git commit -m "Remove Node.js implementation (replaced by Python)"
```

---

### Task 7: Update omnifocus plugin wiring

**Files:**
- Modify: `~/repos/claude-code-plugins/plugins/omnifocus/.mcp.json`

**Step 1: Update `.mcp.json` to point to Python server**

```json
{
  "mcpServers": {
    "omnifocus-mcp": {
      "command": "omnifocus-mcp"
    }
  }
}
```

(The `omnifocus-mcp` command is registered by `pyproject.toml`'s `[project.scripts]`.)

**Step 2: Verify the plugin loads**

Restart Claude Code, check that omnifocus-mcp tools appear.

**Step 3: Commit**

```bash
cd ~/repos/claude-code-plugins
git add plugins/omnifocus/.mcp.json
git commit -m "Point omnifocus plugin to Python MCP server"
```

---

### Task 8: Update jd-cli to depend on omnifocus-mcp

**Files:**
- Modify: `~/repos/jd-cli/pyproject.toml`
- Delete: `~/repos/jd-cli/johnnydecimal/omnifocus.py`
- Modify: `~/repos/jd-cli/johnnydecimal/mcp_server.py` (lines 1608-1820)
- Modify: `~/repos/jd-cli/johnnydecimal/cli.py` (omnifocus commands)

**Step 1: Add omnifocus-mcp dependency to pyproject.toml**

Add `"omnifocus-mcp"` to the `dependencies` list (or to the `mcp` optional dependency group).

```toml
[project.optional-dependencies]
mcp = ["mcp>=1.0", "omnifocus-mcp>=2.0"]
```

**Step 2: Install the dependency**

```bash
cd ~/repos/jd-cli
pip install -e ".[mcp]"
```

**Step 3: Rewrite `jd_omnifocus_scan` in mcp_server.py**

Replace `from johnnydecimal.omnifocus import ...` with `from omnifocus_mcp import OmniFocusClient`. Use `client.get_projects()` (which now includes tags) instead of `list_projects_with_jd_tags()`.

**Step 4: Rewrite `jd_omnifocus_validate` in mcp_server.py**

Same import swap. **Key change:** remove the "Active ID with no OF project" warning loop. Only check that existing JD tags point to valid JD IDs.

**Step 5: Rewrite `jd_omnifocus_open` in mcp_server.py**

Same import swap. **Key change:** when multiple matches found, open ALL of them instead of returning an error. Use `client.open_project(name)` for each match.

**Step 6: Rewrite `jd_omnifocus_create` in mcp_server.py**

Use `client.create_project()` and `client.tag_project()`.

**Step 7: Add `jd_omnifocus_tag` MCP tool**

New tool that tags an existing project with one or more JD IDs:

```python
@mcp.tool()
def jd_omnifocus_tag(project_name: str, targets: list[str]) -> dict:
    """Tag an existing OmniFocus project with JD IDs.

    PROJECT_NAME is the exact name of the OF project.
    TARGETS is a list of JD IDs/categories/areas (e.g. ["26.15", "26.21"]).
    """
```

**Step 8: Update CLI commands in cli.py**

Replace imports from `johnnydecimal.omnifocus` with `omnifocus_mcp.OmniFocusClient` in the CLI command implementations (`omnifocus_scan`, `omnifocus_validate`, `omnifocus_open`, `omnifocus_create`).

**Step 9: Delete `johnnydecimal/omnifocus.py`**

```bash
rm ~/repos/jd-cli/johnnydecimal/omnifocus.py
```

**Step 10: Verify everything works**

```bash
jd omnifocus scan
jd omnifocus validate
jd omnifocus open 26
```

**Step 11: Commit**

```bash
cd ~/repos/jd-cli
git add -A && git commit -m "Replace omnifocus.py with omnifocus-mcp dependency"
```

---

### Task 9: End-to-end verification

**Step 1: Verify omnifocus-mcp MCP tools work from Claude**

Use `get_projects`, `create_task`, `tag_project` via the MCP tools.

**Step 2: Verify jd-workflows MCP tools work from Claude**

Run `jd_omnifocus_scan`, `jd_omnifocus_validate`, `jd_omnifocus_open 06.10`.

**Step 3: Verify multi-tag associative model**

Tag a project with multiple JD IDs and confirm `jd_omnifocus_open` surfaces it from any of those IDs.

**Step 4: Verify `jd_omnifocus_tag` MCP tool**

Tag an existing project via the new MCP tool.

**Step 5: Commit any fixes**
