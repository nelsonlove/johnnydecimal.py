# Johnny Decimal CLI — TODO

## Bug Fixes (from Rex's code review)
- [ ] `is_jd_id()` uses wrong regex — should be `\d{2}\.\d{2} .+` not `\d{2} .+`
- [ ] `JDID.__str__` assumes 2-digit numbers but IDs are `category.sequence` (e.g., 26.01)
- [ ] `_get_categories()` in JDArea calls `is_jd_area()` instead of `is_jd_category()`
- [ ] `get_ids()` in api.py calls `is_jd_category()` instead of `is_jd_id()`
- [ ] JDID number parsing is wrong — reads first 2 chars but IDs are `XX.YY`

## New Commands
- [x] `jd find <id>` — resolve an ID (e.g., `26.01`) to its full filesystem path
- [x] `jd mv <source> <id>` — move a file/dir into the correct JD folder
- [x] `jd cp <source> <id>` — copy a file/dir into the correct JD folder
- [x] `jd new <id> [name]` — create a new ID folder under the right category
- [x] `jd validate` — comprehensive consistency check (see Validation section)
- [x] `jd index [area|category]` — tree output, filterable
- [x] `jd search <query>` — fuzzy search across names
- [x] `jd init <category>` — bootstrap xx.00 and xx.01
- [x] `jd init-all` — bootstrap all categories
- [x] `jd json` — machine-readable index for agents
- [x] `jd generate-index` — regenerate 00.00 Index.md + jd.json

## Validation Rules (`jd validate`)
- [ ] Duplicate IDs across categories (known: 13.05, 73.04)
- [ ] Wrong category prefix (known: area 22 Mom uses 21.xx)
- [ ] Broken symlinks — report but don't fail
- [ ] External drive symlinks/aliases — skip gracefully if target unavailable
- [ ] Orphan directories (non-JD-named dirs inside the tree)
- [ ] Convention: `x0` category = "Meta - [Area Name]" (exception: 00-09 Meta itself)
- [ ] Convention: `xx.01` = "Unsorted" in every category
- [ ] Convention: `xx.02` = "Notes" (tentative — may deprecate in favor of Apple Notes/Obsidian)
- [ ] Gap detection — missing expected IDs in a sequence
- [ ] En-dash vs hyphen consistency in area names

## Symlink Handling
- [ ] Detect and follow symlinks within the JD tree
- [ ] Report broken symlinks separately
- [ ] External drive targets (Seagate, LaCie, Extreme SSD) — indices exist at 00.02-00.04
- [ ] Don't index into external drive symlinks if unmounted
- [ ] Distinguish "symlink into JD" (preferred) vs "symlink out of JD" (git repos etc.)
- [ ] macOS aliases (different from symlinks) — detect via `mdls` or similar

## Conventions to Codify

### Meta directories (`x0`)
- Pattern: `x0 Meta - [Area Name]`
- Purpose: area-level configuration, indices, templates, and unsorted items
- Exception: `00-09 Meta` is itself meta, so `00 Indices` breaks the pattern (fine)
- Recommendation: keep `00 Indices` as-is. For all other areas, `x0 Meta - X` holds:
  - `x0.01 Unsorted` — triage landing zone
  - Area-wide reference material, templates, conventions
  - Think of it as the "junk drawer that knows it's a junk drawer"

### Category meta (`xx.00`)
- Pattern: `xx.00` (no name suffix needed, or "Meta" if you want one)
- Purpose: category-level meta — agent workspace, config, templates, README
- Parallel to `x0 Meta - [Area]` at the area level
- Agents file working artifacts here (e.g., Harbor → `64.00`, Kin → `26.00`, Rex → `06.00`)
- A `README.md` here can describe the category's purpose and conventions
- Not every category needs one — create on-demand

### Unsorted directories (`xx.01`)
- Pattern: `xx.01 Unsorted`
- Purpose: human triage inbox — stuff dumped here to be filed later
- Every category SHOULD have one (validate/create on `jd new`)

### Reserved IDs
```
xx.00    Category meta (agent workspace, config, templates, README)
xx.01    Unsorted (human triage inbox)
xx.02+   Real content (named by subject)
```
- `xx.00` parallels `x0` (area meta) at the category level
- Notes: no reserved slot. Use Apple Notes for quick capture, filesystem for archival/structured docs
- Existing `xx.02 Notes` dirs are fine — just not enforced as convention

### Git repos / sync-sensitive dirs
- Symlink INTO JD tree (preferred default)
- Exception: dirs where sync conflicts would emerge (git repos with active work)
  - These live in ~/Projects and get symlinked FROM JD into ~/Projects
  - Example: `92.05 johnnydecimal.py` lives at ~/Projects, symlinked from ~/Documents/90-99/92/

## Cross-App Integration (Future)

### Design Principle: Sparse Subsets with Meta Markers
- Filesystem is the COMPLETE canonical tree
- Every other app holds a SPARSE SUBSET — only folders/categories that have actual content
- No empty folder mirroring — folders are created on-demand when content is filed
- Each app signals JD-awareness via a "meta marker" convention
- `jd validate --<app>` checks: (1) is meta marker present? (2) do existing folders match filesystem?
- Validation flags MISMATCHES in what exists, NOT missing folders

### Meta Markers (how we detect JD-awareness)
- **Apple Notes**: presence of `00-09 Meta` folder (or any `XX-XX` area folder)
- **OmniFocus**: top-level folder with JD area naming, or a `JD` tag
- **Email (IMAP)**: folders matching JD naming convention
- **Obsidian**: vault root contains `00-09 Meta` directory
- If marker is absent → app is not JD-managed → skip during validation

### Apple Notes
- Already partially JD-structured (40 folders, 691 notes)
- Known mismatches with filesystem numbering (see 00.00 Index.md)
- Validate: each Notes folder that uses JD naming should match filesystem
- Don't create empty folders — only create when filing a note there
- `jd file --notes <note> <id>` would create the folder path on-demand

### Obsidian
- 4 vaults exist, none follow JD structure
- Decision pending on whether to keep Obsidian at all
- If kept: single vault, sparse JD folders created as needed

### OmniFocus
- Natural mapping: OF project/folder ↔ JD category
- e.g., "Recipes & Legal" ↔ `26 Recipes`
- Don't mirror the full tree — just map what exists
- Could use tags (JD:26) or folder naming convention

### Email (IMAP)
- himalaya can manage folder structure
- JD-named folders for filing important emails
- Sparse: only create folders for categories with saved emails

### Agent Integration
- Agents (Rex, Kin) need to file documents into JD
- CLI is the interface — `jd file <path> <id>` is the primary tool
- `jd find <id>` lets agents resolve paths without hardcoding
- `jd validate` can run as a periodic heartbeat/cron task
- Index at `00.00 Index.md` is auto-generated, agents can read it for context
- Consider: `jd.json` manifest at root for machine-readable index
  - Faster than parsing filesystem every time
  - Agents read JSON, humans read `00.00 Index.md`
  - Regenerated alongside the markdown index

## Architecture

### Config file (`~/.config/johnnydecimal/config.yaml`)
```yaml
root: ~/Documents
external_drives:
  - /Volumes/Seagate
  - /Volumes/LaCie
  - /Volumes/Extreme SSD
conventions:
  meta_prefix: true      # x0 = "Meta - [Area]"
  unsorted_01: true       # xx.01 = "Unsorted"
  notes_02: optional      # xx.02 = "Notes" (don't enforce yet)
ignore:
  - .DS_Store
  - .git
  - __pycache__
  - .Trash
```

### Index outputs
- `00.00 Index.md` — auto-generated human-readable tree (regenerated by `jd index`)
- `00.01 Index Notes.md` — human-curated notes, decisions, known issues, cleanup log
- `00.00 index.json` — machine-readable index for agents (optional, generated alongside)

## Rex's Recommendations

### On the Notes question (xx.02)
Leaning toward: **Apple Notes for quick capture, filesystem for archival/structured docs.**
- Apple Notes is already where you quick-capture from phone/watch
- Filesystem `xx.02 Notes` is good for longer markdown docs, research, things you'd version
- Obsidian adds a third system with no clear advantage over the other two — consider dropping it
- The JD CLI can validate that Apple Notes folders match filesystem categories (cross-reference)
- Don't force a decision now — the CLI should track what exists without enforcing

### On Meta dirs
The `x0 Meta - [Area]` convention is solid. Use them for:
- `x0.01 Unsorted` — always present, the inbox for that area
- Templates, conventions, reference material for the area
- Area-level indices or dashboards (if needed)
- NOT for actual content — if something has a real category, it goes there

### On agent-friendliness
The single most valuable thing for agents: **`jd find` that just works.**
Everything else flows from being able to resolve `26.01` → `/Users/nelson/Documents/20-29 Family/26 Recipes/26.01 Unsorted` instantly. No guessing, no hardcoded paths.

Second most valuable: **`jd.json`** — a cached index that agents can read without scanning the filesystem every time. Regenerate on `jd index` or `jd validate`.

## Nelson's Notes (2026-02-20)
- Filesystem is canonical source of truth
- Some dirs symlinked/aliased to external drives (may not be plugged in)
- External drives have their own indices (00.02-00.04)
- Meta convention: x0 = "Meta - [Area]", exception for 00-09
- Unsorted convention: xx.01 = "Unsorted" everywhere
- Notes convention (xx.02): undecided, inconsistent currently
- Git repos: symlink out of JD into ~/Projects to avoid sync issues
- Wants agent-friendly tooling — CLI as the interface
