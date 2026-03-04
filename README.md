# jd — Johnny Decimal CLI

A command-line tool for managing a [Johnny Decimal](https://johnnydecimal.com) filing system. Built for humans and AI agents.

## Install

```bash
pipx install .

# Optional: MCP server support for AI agents
pipx inject johnnydecimal mcp
```

Requires Python 3.10+ and `pyyaml`. Optional: `tree` (for `jd ls`), `mcp` (for `jd mcp`).

## Quick Start

```bash
jd ls                  # list all areas
jd ls 26               # tree view of category 26
jd which 26.01         # resolve ID to path → /Users/.../26.01 Unsorted
jd search "pasta"    # find entries by name
jd triage              # show where attention is needed
```

## Commands

### Navigation

| Command | Description |
|---------|-------------|
| `jd cd <TARGET>` | Change directory to a JD target (ID, category, area, or name) |
| `jd ls [TARGET]` | List contents using `tree`. Supports `-L` depth, `--area`, `-d` dirs-only |
| `jd which <ID>` | Resolve a JD ID or category to its filesystem path |
| `jd search <QUERY>` | Case-insensitive name search. `--archived` includes `.99` dirs |
| `jd index` | Print the full JD index |
| `jd json` | Output the full index as JSON (for agent consumption) |
| `jd root` | Print the root directory of the filing system |

`jd cd` requires a shell wrapper. Run `jd cd --setup` to print it, then add to your `.zshrc`:

```bash
eval "$(jd cd --setup)"
```

### Creating

| Command | Description |
|---------|-------------|
| `jd new id <CAT> <NAME>` | Create a new ID in a category (auto-numbered) |
| `jd new category <AREA> <NAME>` | Create a new category in an area (auto-numbered) |
| `jd init <CAT>` | Bootstrap a category with `xx.00` and `xx.01 Unsorted` |
| `jd init-all` | Bootstrap all categories. `--dry-run` to preview |
| `jd add <PATH> <CAT>` | Add a file or directory from outside the JD tree |

### Moving & Renaming

| Command | Description |
|---------|-------------|
| `jd mv <SRC> <DEST>` | Smart move: renumber, refile, or rename based on args |
| `jd mv 26.01 22.01` | Renumber (move to specific ID) |
| `jd mv 26.01 22` | Refile to category 22 (next available ID) |
| `jd mv 26.01 "New name"` | Rename (keep number) |
| `jd mv 26 "New name"` | Rename a category |

All `mv` operations support `--dry-run` / `-n`.

### Archiving

| Command | Description |
|---------|-------------|
| `jd mv -a <TARGET>` | Archive an ID to `xx.99` or a category to `x0.99` |
| `jd restore <TARGET>` | Restore from archive to original location |
| `jd restore --renumber <TARGET>` | Restore to next available ID if original is taken |

Archive is round-trip safe. Archived items preserve their original names. Empty `.99` dirs are auto-cleaned on last restore.

```bash
jd mv -a 86.03          # → 86.99 Archive/86.03 Travel Photos/
jd mv -a 21             # → 20.99 Archive/21 Old Projects/
jd restore 86.03        # exact reversal
jd restore --renumber 86.03  # if 86.03 is now taken, assigns next available
```

### Validation & Triage

| Command | Description |
|---------|-------------|
| `jd validate` | Check for duplicates, mismatches, convention violations. `--fix` auto-fixes, `--force` fixes wrong-target links, `--dry-run` previews |
| `jd triage` | Show busiest unsorted dirs, file-IDs, empty categories |
| `jd generate-index` | Regenerate `00.00/Index.md` from the filesystem |

Validate follows symlinks into mounted external drives and checks them too.

### Symlinks & Inbound Links

| Command | Description |
|---------|-------------|
| `jd symlinks` | Show all symlinks in the tree grouped by location, with git status |
| `jd symlinks --check` | Exit 1 if any inbound link is missing or wrong |
| `jd symlinks --fix` | Create missing inbound symlinks |
| `jd ln <SOURCE> <ID>` | Create an inbound symlink and declare it in policy |
| `jd ln --remove <SOURCE> <ID>` | Remove an inbound symlink and its policy entry |

Inbound links are external paths (e.g. `~/.ssh`) that symlink *into* the JD tree. Declare them in `policy.yaml` under `links:` so `jd validate` tracks them:

```yaml
links:
  "06.05":
    - ~/.ssh
    - ~/.gnupg
```

`jd ln` creates the symlink and adds the policy entry in one step. `jd validate --fix` creates any missing inbound symlinks. `jd validate --fix --force` also recreates symlinks that point to the wrong target.

### External Volumes

Manage content on external drives (declared in `policy.yaml`):

| Command | Description |
|---------|-------------|
| `jd volume list` | List declared volumes with mount status and alias counts |
| `jd volume scan` | Report aliases, symlinks, broken links, and undeclared references per volume |
| `jd volume index [NAME]` | Generate a `tree` index of a mounted volume and save to `00.02` |

Volume aliases are files named like `86.05 Music software [Extreme SSD]`. When the drive is mounted, `jd volume link` converts them to symlinks.

### Apple Notes

Manage JD IDs that live in Apple Notes instead of the filesystem. Requires macOS.

| Command | Description |
|---------|-------------|
| `jd notes scan` | Compare Apple Notes folders against JD tree and policy declarations |
| `jd notes validate` | Check consistency between stubs, Notes, and policy |
| `jd notes stub <ID>` | Create a YAML stub file marking an ID as Notes-backed |
| `jd notes create <ID>` | Create a note/folder in Apple Notes for a JD ID. `--folder`, `--stub` |
| `jd notes open <ID>` | Open a note in Notes.app |

Declare Notes-backed IDs in root `policy.yaml`:

```yaml
notes:
  "26":
    - "26.05"
    - "26.12"
  "11": all    # entire category is Notes-backed
```

Stubs are YAML files like `26.05 Sourdough [Apple Notes].yaml` that sit in the category directory. They are recognized by `jd validate` (skipped in step 10) and contain:

```yaml
location: Apple Notes
path: 20-29 Projects > 26 Recipes > 26.05 Sourdough
```

### OmniFocus

Manage the link between OmniFocus projects and JD locations via `JD:xx.xx` tags. Requires macOS with OmniFocus installed.

| Command | Description |
|---------|-------------|
| `jd omnifocus scan` | Compare JD tags in OmniFocus against the JD tree |
| `jd omnifocus validate` | Check consistency: dead tags, orphan projects, area mismatches |
| `jd omnifocus open <ID>` | Open the OmniFocus project tagged with a JD ID |
| `jd omnifocus tag <ID>` | Create a `JD:xx.xx` tag in OmniFocus |
| `jd omnifocus create <ID>` | Create an OF project named after the JD ID, with tag. `--folder NAME` |

OmniFocus projects link to JD via tags (`JD:26.05` or `JD:26`), not mirrored folder structure. One OF project can reference multiple JD IDs. Disable with `omnifocus: false` in root `policy.yaml`.

### Policy

Cascading policy files (`.johnnydecimal.yaml`) control conventions at any level of the tree. Most specific wins, like `.editorconfig`.

| Command | Description |
|---------|-------------|
| `jd policy show [PATH]` | Show effective policy for a path |
| `jd policy get <KEY> [PATH]` | Get a specific policy value |
| `jd policy set <KEY> <VALUE> [PATH]` | Set a policy value |
| `jd policy unset <KEY> [PATH]` | Remove a policy override |
| `jd policy where <KEY> [PATH]` | Show which file sets a policy value |

#### Policy Keys

| Key | Default | Description |
|-----|---------|-------------|
| `ids_as_files` | `false` | Allow IDs to be files instead of directories |
| `ids_files_only` | `false` | IDs should contain only files (no subdirectories) |
| `meta_category` | `true` | `x0` should be "Meta - [Area]" |
| `meta_id` | `true` | `xx.00` = category meta directory |
| `unsorted_id` | `true` | `xx.01` = "Unsorted" triage inbox |

## Conventions

This tool enforces (and validates) a set of JD conventions:

- **`x0 Meta - [Area]`** — area-level meta category (exception: `00-09 Meta`)
- **`xx.00`** — category meta (agent workspace, config, templates)
- **`xx.01 Unsorted`** — category-level triage inbox
- **`xx.99 Archive`** — category-level archive (auto-created by `jd mv -a`)
- **`x0.99 Archive`** — area-level archive for whole categories
- **`01 Capture`** — top-level triage inbox with addressable buckets

Two-tier triage flow: `01.xx` (capture) → `xx.01` (category unsorted) → `xx.yy` (final ID).

## Agent Scoping

Agents can be restricted to specific areas/categories via a `jd.yaml` file in their workspace:

```yaml
# family-agent — restricted to family areas
scope:
  - "20-29"    # Family area
  - "13"       # Health and medical

# general-agent — unrestricted
scope: all
```

Scope is enforced on write operations (`mv`, `new`, `init`, archive). Reads always pass.

Resolution order:
1. `JD_AGENT_SCOPE` environment variable (path to scope file)
2. `./jd.yaml` in current working directory
3. No scope file = unrestricted

## MCP Server

An MCP server exposes the full JD API to AI agents (Claude Code, claude.ai, etc.):

```bash
# Install with MCP support
pipx install .
pipx inject johnnydecimal mcp

# Run the server (stdio transport)
jd mcp
```

### Claude Code

Add to your Claude Code MCP config:

```json
{
  "mcpServers": {
    "jd": {
      "command": "jd",
      "args": ["mcp"]
    }
  }
}
```

### Tools

The MCP server provides 29 tools covering navigation, creation, moving, archiving, validation, symlinks, volume management, Apple Notes, OmniFocus, and policy. Key tools:

| Tool | Description |
|------|-------------|
| `jd_index` | Full JD index |
| `jd_find` | Resolve an ID to its path |
| `jd_search` | Search entries by name |
| `jd_ls` | Tree listing of a target |
| `jd_new_id` / `jd_new_category` | Create new entries |
| `jd_move` | Move, rename, renumber, or archive |
| `jd_validate` | Run validation with cross-volume and inbound link checks. Supports `force` for wrong-target links |
| `jd_symlinks` | List all symlinks with git status and inbound link state |
| `jd_ln` | Create/remove inbound symlinks and update policy |
| `jd_volume_list` / `jd_volume_scan` | External drive management |
| `jd_notes_scan` / `jd_notes_validate` | Apple Notes scan and consistency checks |
| `jd_notes_create` / `jd_notes_open` | Create notes/folders and open in Notes.app |
| `jd_omnifocus_scan` / `jd_omnifocus_validate` | OmniFocus scan and consistency checks |
| `jd_omnifocus_create` / `jd_omnifocus_open` | Create OF projects with JD tags, open in OmniFocus |
| `jd_policy` / `jd_policy_set` | Read and write policy |

Resources: `jd://tree` (full index), `jd://policy` (effective policy).

## Shell Completion

Zsh completions are installed automatically. Tab-complete JD IDs with contextual help:

```
$ jd which 26.<TAB>
26.00  -- Recipes > (meta)
26.01  -- Recipes > Unsorted
26.02  -- Recipes > Weeknight dinners
26.03  -- Recipes > Holiday baking
```

To regenerate:
```bash
_JD_COMPLETE=zsh_source jd > ~/.zfunc/_jd
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT
