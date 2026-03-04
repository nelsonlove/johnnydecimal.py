# Johnny Decimal System Guide

A complete reference for the Johnny Decimal filing system managed by `jd-cli`. Covers principles, structure, conventions, cross-app integration, agent workflows, and the current state of the tooling.

## What This Is

Johnny Decimal is an organizational system that assigns numeric IDs to every folder in a filing hierarchy. This project (`jd-cli`) is a Python CLI and MCP server that manages the filesystem, enforces conventions, and integrates with external apps (Apple Notes, OmniFocus).

The filesystem is the canonical source of truth. All other systems hold sparse subsets.

## System Principles

1. **The filesystem is the source of truth.** External apps (Notes, OmniFocus, email) hold subsets — never the complete picture.
2. **Folders are created on-demand.** No empty mirroring across apps. A folder exists in an app only when it has content there.
3. **JD-aware apps signal awareness via a meta marker** (e.g., an `XX-XX` area folder). If the marker is absent, the app is not JD-managed.
4. **Agents use the `jd` CLI.** No hardcoded paths. `jd which <id>` resolves everything.
5. **Minimum viable organization.** JD provides structure. OmniFocus provides action. Don't over-engineer beyond that.

## Structure

### Areas (`XX-XX Name`)

Top-level groupings. Max 10 (digits 0-9). Each area gets a two-digit range: `00-09`, `10-19`, ..., `90-99`.

### Categories (`XX Name`)

Two-digit numbered directories inside areas. Each area holds up to 10 categories.

### IDs (`XX.YY Name`)

Dotted notation inside categories. Up to 100 per category (00-99). An ID is the atomic unit — it covers a *topic*, not a single file.

### Reserved IDs

Every category follows this convention:

| ID | Purpose | Notes |
|--------|---------|-------|
| `xx.00` | **Category meta** | Agent workspace, config, templates, README |
| `xx.01` | **Unsorted** | Category-level inbox. Stuff that belongs here but hasn't been specifically filed |
| `xx.99` | **Archive** | Auto-created by `jd mv -a` |

### Area meta (`x0`)

Pattern: `x0 Meta - [Area Name]`. Purpose: area-level reference material, templates, conventions.

Each `x0` directory should contain a `README.md` documenting:
- What the area covers and its boundaries
- Setup or tooling needed
- Area-specific conventions
- Links to related resources

## Capture System

Category `01` is the system-wide intake. Items flow through here on their way to proper JD locations.

### Two-tier triage

```
01.xx (Capture)  →  xx.01 (Category unsorted)  →  xx.yy (Final ID)
```

**Tier 1 (Capture → Category):** Quick sort. "This is a health thing" → `jd mv file 13.01`. An agent or human just needs to know the domain.

**Tier 2 (Category → ID):** Detailed filing. "This is specifically lab results" → `jd mv file 13.05`. Domain agents handle this.

You don't have to do both tiers at once. Tier 1 is a fast sweep; Tier 2 happens when someone with domain knowledge is available.

### Capture buckets

| Bucket | Type | Purpose |
|--------|------|---------|
| `01.00` | meta | Capture policy, auto-sort rules, agent config |
| `01.01 Unsorted` | catch-all | True unknown — needs human decision |
| `01.02+` | source/destination | Specific intake channels (downloads, screenshots, scans) or staging for blocked actions (waiting for external drive, waiting for app import) |

Source buckets fill automatically. Destination buckets get emptied when blockers clear.

## Policy System

Cascading policy files (`.johnnydecimal.yaml`) control conventions at any level of the tree. Most specific wins, like `.editorconfig`.

### Root policy (`policy.yaml`)

Lives in the dotfiles repo, symlinked into `00.00 Meta/`. Declares:

```yaml
conventions:
  meta_category: true     # x0 = "Meta - [Area]"
  meta_id: true           # xx.00 = category meta
  unsorted_id: true       # xx.01 = "Unsorted"
  capture_category: "01"  # system inbox

patterns:
  "*.00": { purpose: meta }
  "*.01": { purpose: capture }
  "x0":   { purpose: area-meta }

volumes:
  External Drive:
    mount: /Volumes/External Drive
    root: Documents
```

### Policy keys

| Key | Default | Description |
|-----|---------|-------------|
| `ids_as_files` | `false` | Allow IDs to be files instead of directories |
| `ids_files_only` | `false` | IDs should contain only files (no subdirectories) |
| `meta_category` | `true` | `x0` should be "Meta - [Area]" |
| `meta_id` | `true` | `xx.00` = category meta directory |
| `unsorted_id` | `true` | `xx.01` = "Unsorted" triage inbox |

## Symlinks

### Direction
- **Into JD (preferred):** External resources get a symlink inside the JD tree.
- **Out of JD (exception):** Sync-sensitive dirs (git repos, XDG config) live outside iCloud and get symlinked FROM JD. Avoids iCloud/sync conflicts.

### External drives
- Some IDs are symlinks to external drives. If the drive is unplugged, the symlink is broken. This is expected — `jd validate` reports it but doesn't treat it as an error.

### Inbound links
External paths (e.g., `~/.ssh`) can symlink *into* the JD tree. Declare them in `policy.yaml` under `links:` so `jd validate` tracks them:

```yaml
links:
  "06.05":
    - ~/.ssh
    - ~/.gnupg
```

`jd ln` creates the symlink and adds the policy entry in one step.

## Developer Environment

### Git repos
Git repos cannot live on iCloud Drive (`.git` corruption from sync). All repos live in `~/repos/`. JD references them via symlinks:

```
~/repos/myproject/                              ← real repo
~/Documents/60-69 Work/61 Projects/61.03 MyProject → ~/repos/myproject/
```

### Dotfiles
The dotfiles repo lives at `~/.config/` and contains system policy docs (`POLICY.md`, `policy.yaml`) symlinked into the JD tree.

## Cross-App Integration

### Apple Notes

Some JD IDs live entirely in Apple Notes rather than the filesystem. The `jd notes` commands manage this:

- **Stub files** mark Notes-backed IDs: `26.05 Recipes [Apple Notes].yaml`
- **Policy declarations** in `policy.yaml` list which IDs/categories are Notes-backed
- `jd notes scan` compares Notes folders against the JD tree
- `jd notes validate` checks consistency between stubs, Notes, and policy
- `jd notes create/open` manage notes directly

### OmniFocus

JD and OmniFocus serve different purposes:
- **JD** = where things *are* (filing, artifacts, reference)
- **OF** = what you need to *do* (actions, projects, deadlines)

They link via tags (`JD:xx.xx`), not folder structure. One OF project may reference multiple JD IDs. `jd omnifocus` commands manage the tag-based linking.

## Agent Integration

### Workspace vs. JD
- Agent workspaces hold the agent's **mind**: config, memory, skills
- JD `xx.00` dirs hold the agent's **output**: reports, drafts, artifacts
- Agents read from anywhere in JD but write artifacts to their scoped categories

### Agent scoping (`jd.yaml`)
Each agent workspace can declare its JD scope:

```yaml
scope:
  - "20-29"    # Family area
  - "13"       # Health and medical
```

Scope is enforced on write operations (`mv`, `new`, `init`, archive). Reads always pass.

### Filing workflow
1. Agent produces an artifact
2. Agent knows the domain → `jd mv artifact.pdf xx.00` (into category meta)
3. Agent doesn't know → `jd mv artifact.pdf 01.01` (into capture unsorted)
4. Triage pass files it properly

### MCP server
The `jd mcp` command exposes 29 tools to AI agents, covering navigation, creation, moving, archiving, validation, symlinks, volume management, Apple Notes, OmniFocus, and policy.

## Naming Conventions

- Areas: `XX-XX Name` (hyphen, not en-dash)
- Categories: `XX Name`
- IDs: `XX.YY Name` (or just `XX.YY` for meta dirs)
- Sentence case for names
- No trailing spaces
- No special characters that break shell commands (`:`, `*`, `?`)

## Documentation Conventions

| File | Purpose | Auto-loaded? |
|------|---------|--------------|
| `README.md` | What this is, conventions, context. For humans and agents. | No |
| `CLAUDE.md` | Claude Code session instructions. Rules, preferences, constraints. | Yes |

Don't duplicate content between them. README.md is context; CLAUDE.md is directives.

## What's Implemented

### CLI commands (all working, 105 tests passing)
- **Navigation:** `cd`, `ls`, `which`, `search`, `index`, `json`, `root`, `open`
- **Creating:** `new id`, `new category`, `init`, `init-all`, `add`
- **Moving:** `mv` (renumber, refile, rename), archiving (`mv -a`), `restore`
- **Validation:** `validate` (with `--fix`, `--force`, `--dry-run`), `triage`, `generate-index`
- **Symlinks:** `symlinks`, `ln`
- **Volumes:** `volume list`, `volume scan`, `volume index`, `volume link`
- **Apple Notes:** `notes scan`, `notes validate`, `notes stub`, `notes create`, `notes open`
- **OmniFocus:** `omnifocus scan`, `omnifocus validate`, `omnifocus open`, `omnifocus tag`, `omnifocus create`
- **Policy:** `policy show`, `policy get`, `policy set`, `policy unset`, `policy where`
- **MCP server:** 29 tools + 2 resources, mirrors all CLI functionality

### Infrastructure
- Cascading policy system (`.johnnydecimal.yaml`)
- Agent scoping via `jd.yaml`
- Shell completion (zsh)
- `pipx install` packaging

## What's Planned

### CLI
- `jd backup` — snapshot to tarball/manifest
- `jd cp` — copy into JD (like mv but keeps original)
- `jd renum` — batch renumber within a category
- `jd stats` — system-wide statistics
- `jd gc` — clean up empty dirs, broken symlinks, .DS_Store
- Config file (`~/.config/johnnydecimal/config.yaml`)

### Validation
- Gap detection (missing IDs in a sequence)
- macOS alias detection
- External drive awareness (skip gracefully if unmounted)
- Auto-fix for simple issues (en-dash → hyphen, trailing spaces)

### Naming migration (major project)
- CLI-friendly directory naming: `06.03 Dotfiles` → `06-03-dotfiles`
- Configurable naming convention in root policy
- Dual-format parser during migration
- `jd migrate` command with rollback
- Touches everything: models, regexes, symlinks, Notes, OF, stubs, policy, completion, iCloud sync

### More integrations
- Email (IMAP) folder structure
- Obsidian vault alignment
- `jd validate --notes` / `jd validate --omnifocus` for cross-app checks
- Make `jd` an OpenClaw skill for all agents
- `jd.json` cached index for faster lookups

## Architecture

```
johnnydecimal/
  cli.py          — Click commands (~3200 lines)
  mcp_server.py   — MCP tools mirroring CLI commands
  models.py       — JDRoot, JDArea, JDCategory, JDID
  policy.py       — Cascading .johnnydecimal.yaml policy system
  scope.py        — Agent write scoping via jd.yaml
  util.py         — Path helpers, JD pattern matching
  notes.py        — Apple Notes connector (JXA)
  omnifocus.py    — OmniFocus connector (JXA)
tests/            — 105 tests (pytest)
docs/             — Integration guides
```

## Related Documentation

| File | What |
|------|------|
| `README.md` | Quick-start CLI reference |
| `docs/omnifocus-integration.md` | OmniFocus integration guide |
| `TODO.md` | Feature roadmap |
| Root `policy.yaml` | Machine-readable system conventions |
| Root `POLICY.md` | Full system policy (in dotfiles repo, symlinked into JD tree) |
