# OmniFocus MCP Consolidation

Date: 2026-03-08

## Problem

Two independent MCP servers talk to OmniFocus via separate JXA implementations:

- **omnifocus-mcp** (Node.js): generic CRUD — tasks, projects, tags
- **jd-cli** (`omnifocus.py`, Python): JD-aware scan, validate, open, create

They share zero code. omnifocus-mcp lacks tag operations on existing items. jd-cli's `tag_project` function isn't exposed as an MCP tool. The cross-language split (Node vs Python) prevents jd-cli from importing omnifocus-mcp as a library.

### Findings from test drive

- **Associative tagging works**: OF projects can carry multiple `JD:xx` tags, enabling cross-cutting projects (e.g., "Motion for Temporary Orders" tagged `JD:26`, `JD:26.15`, `JD:26.21`).
- **`jd omnifocus open` bug**: treats multiple matches as an error, but with associative tagging, multi-match is the expected case.
- **`jd omnifocus open <ID>` bug**: JXA type conversion error on ID-level targets.
- **`jd omnifocus validate`**: flags ~260 untracked IDs as warnings, which is noise — most IDs are archival/reference and don't need OF projects.
- **No MCP tool for tagging existing projects**: had to shell out to Python directly.

## Design

### 1. Rewrite omnifocus-mcp as Python

Replace the Node.js implementation in `~/repos/omnifocus-mcp` with a Python package.

**Package**: `omnifocus_mcp`
**MCP server**: Python MCP SDK (stdio transport)
**OF access**: `subprocess.run(['osascript', '-l', 'JavaScript', '-e', script])` — same mechanism, just Python instead of Node.

**MCP tools:**

| Tool | Status | Notes |
|------|--------|-------|
| `get_tasks` | Existing | Filters: project, context, flagged, completed |
| `get_projects` | Existing | |
| `get_contexts` | Existing | Tags/contexts |
| `create_task` | Existing | |
| `create_project` | Existing | |
| `update_task` | Expanded | Add tag support |
| `update_project` | New | Same fields as update_task but for projects |
| `complete_task` | Existing | |
| `delete_task` | Existing | |
| `tag_project` | New | Add/remove tags on existing projects |
| `tag_task` | New | Add/remove tags on existing tasks |

**Library API**: `OmniFocusClient` class with methods matching the tools. Importable by jd-cli: `from omnifocus_mcp import OmniFocusClient`.

### 2. jd-cli delegates OF access to omnifocus-mcp

- Delete `johnnydecimal/omnifocus.py` (334 lines of independent JXA)
- Add `omnifocus-mcp` as a dependency in `pyproject.toml`
- Rewrite OF integration to use `OmniFocusClient`

**JD-aware tools stay in jd-cli** (the JD logic is the value):

| Tool | Change |
|------|--------|
| `jd_omnifocus_scan` | Delegates OF queries to `OmniFocusClient` |
| `jd_omnifocus_validate` | Revised: only checks existing JD tags against JD tree. Stops flagging untracked IDs. |
| `jd_omnifocus_open` | Fixed: opens all matches instead of erroring on multi-match. Fixed: JXA type conversion bug. |
| `jd_omnifocus_create` | Delegates to `client.create_project()` + `client.tag_project()` |
| `jd_omnifocus_tag` | New MCP tool: tag existing projects with JD IDs. Supports multiple tags. |

**Tag format**: `JD:xx.xx` prefix distinguishes JD tags from other OF tags.

### 3. Plugin wiring

- **omnifocus plugin** (`plugins/omnifocus/`): update `.mcp.json` to point to Python MCP server
- **jd-workflows plugin** (`plugins/jd-workflows/`): no change (already points to `jd mcp`)
- Plugins stay separate: omnifocus = generic OF CRUD, jd-workflows = JD intelligence

### Deleted artifacts

- `~/repos/omnifocus-mcp/src/` (Node.js source)
- `~/repos/omnifocus-mcp/package.json`, `node_modules/`
- `~/repos/jd-cli/johnnydecimal/omnifocus.py`

### Created artifacts

- `~/repos/omnifocus-mcp/omnifocus_mcp/` (Python package)
- `~/repos/omnifocus-mcp/pyproject.toml`

## Tagging policy (baked into tool behavior)

- JD tags on OF projects indicate which IDs are relevant, not 1:1 ownership.
- A project can carry multiple JD tags (associative, many-to-many).
- `jd_omnifocus_open <target>` surfaces all projects that touch that target.
- Projects are tagged on-demand — no empty mirroring from the JD tree.
