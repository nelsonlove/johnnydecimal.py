# jd — Johnny Decimal CLI

A command-line tool for managing a [Johnny Decimal](https://johnnydecimal.com) filing system. Built for humans and AI agents.

## Install

```bash
pipx install --editable .
```

Requires Python 3.10+ and `pyyaml`. Optional: `tree` (for `jd ls`).

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
| `jd ls [TARGET]` | List contents using `tree`. Supports `-L` depth, `--area`, `-d` dirs-only |
| `jd which <ID>` | Resolve a JD ID or category to its filesystem path |
| `jd search <QUERY>` | Case-insensitive name search. `--archived` includes `.99` dirs |
| `jd index` | Print the full JD index |
| `jd json` | Output the full index as JSON (for agent consumption) |
| `jd root` | Print the root directory of the filing system |

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
jd mv -a 86.03          # → 86.99 Archive/86.03 Wedding Photos/
jd mv -a 21             # → 20.99 Archive/21 Jen/
jd restore 86.03        # exact reversal
jd restore --renumber 86.03  # if 86.03 is now taken, assigns next available
```

### Validation & Triage

| Command | Description |
|---------|-------------|
| `jd validate` | Check for duplicates, mismatches, convention violations |
| `jd triage` | Show busiest unsorted dirs, file-IDs, empty categories |
| `jd generate-index` | Regenerate `00.00/Index.md` from the filesystem |

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
# Kin — family agent
scope:
  - "20-29"    # Family area
  - "13"       # Health and medical

# Rex — unrestricted
scope: all
```

Scope is enforced on write operations (`mv`, `new`, `init`, archive). Reads always pass.

Resolution order:
1. `JD_AGENT_SCOPE` environment variable (path to scope file)
2. `./jd.yaml` in current working directory
3. No scope file = unrestricted

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

## License

MIT
