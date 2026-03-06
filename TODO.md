# Johnny Decimal CLI — TODO

## Done
- [x] Core commands: which, mv, new, init, init-all, search, validate, json, index, generate-index, add
- [x] Bug fixes: is_jd_id regex, JDID.__str__, _get_categories, get_ids, JDID number parsing
- [x] `xx.00` support (category meta, no name suffix required)
- [x] `is_jd_root` relaxed (≥3 JD area dirs, tolerates orphan dirs)
- [x] Broken symlink scan made lazy (was rglob causing timeouts)
- [x] Archive: `jd mv -a` (xx.99 for IDs, x0.99 for categories)
- [x] Restore: `jd restore` with `--renumber` for conflict resolution
- [x] Round-trip safe archiving (names preserved, empty .99 auto-cleaned)
- [x] `--dry-run` / `-n` on mv and restore
- [x] `jd ls` wrapping `tree` (fallback to `ls -R`)
- [x] `jd triage` — busiest unsorted, file-IDs, empty categories
- [x] Tab completion: `JDIdType` with `Category > Name` disambiguation
- [x] Cascading policy system (`.johnnydecimal.yaml`, pattern matching) — migrating to `jd.yaml`
- [x] `ids_as_files` policy (default false, validate flags violations)
- [x] `ids_files_only` policy
- [x] `jd policy show/get/set/unset/where`
- [x] Agent scoping via `jd.yaml` (per-workspace, env var, scope enforcement on writes)
- [x] pipx install, pyproject.toml, zsh completions
- [x] Emoji-free output
- [x] `jd open` — open JD location in Finder/file manager

## Next Up

### CLI
- [ ] `jd backup` — snapshot the JD tree (metadata, structure, or full) to a tarball or manifest
- [ ] `jd cp` — copy into JD (like mv but keeps original)
- [ ] `jd renum` — batch renumber within a category
- [x] `jd stats` — system-wide statistics (structure, storage, file types, depth, age, health)
- [ ] Unified `jd.yaml` config file (replaces `.johnnydecimal.yaml`)
  - Two top-level keys: `policy:` (validation rules) and `config:` (behavior)
  - `jd.example.yaml` in the jd-cli repo as documented default
  - Cascading: JD root → area meta dir → category meta dir → ID meta dir (each overrides)
  - Migrate existing `.johnnydecimal.yaml` policy into `jd.yaml` `policy:` key
  - `config:` holds repo roots, staging prefs, ignore patterns, external drives, etc.
- [ ] `jd config edit [TARGET]` — open jd.yaml in `$EDITOR` at the appropriate level
  - No arg: root jd.yaml (00.00 Meta)
  - JD ID (e.g. `26.05`): that ID's meta dir jd.yaml
  - Category (e.g. `26`): that category's meta dir jd.yaml
  - Area (e.g. `20-29`): that area's meta dir jd.yaml
  - Creates from `jd.example.yaml` if file doesn't exist yet
- [ ] `jd config show [TARGET]` — like `jd policy show` but for the full jd.yaml (policy + config)
- [ ] `jd config get/set/unset` — like `jd policy get/set/unset` but supports `config.*` keys too
- [ ] Merge `jd policy` subcommands into `jd config` (policy becomes `jd config get/set policy.*`)

### Validation
- [ ] Gap detection — missing expected IDs in a sequence
- [ ] macOS alias detection (different from symlinks) — `mdls` or similar
- [ ] External drive awareness — skip gracefully if unmounted
- [ ] `jd validate --fix` — auto-fix simple issues (en-dash → hyphen, trailing spaces)

### Tab Completion
- [ ] Test in real shell (Click's `_JD_COMPLETE=zsh_complete` needs `COMP_WORDS`)
- [ ] Bash/fish completion support

### Naming
- [ ] CLI-friendly directory naming: `06.03 Dotfiles` → `06-03-dotfiles` (no spaces, no dots, lowercase)
  - Configurable naming convention in root policy (current vs CLI-friendly)
  - Dual-format parser during migration (recognize both formats)
  - `jd migrate` command — piecemeal (one area/category at a time) with rollback
  - Keep JD IDs dotted in tags/references (`26.05`) — only change filesystem names
  - Touches: models, all regexes, symlinks, Notes folders, OF tags, stubs, policy patterns, completion, iCloud sync

### Staging
- [x] `jd tag add <id> <path>` — add `JD:xx.xx` Finder tag to a file/dir (no move)
- [x] `jd tag remove <path>` — strip `JD:*` Finder tag
- [x] `jd stage <id>` — unstage current, then tag + move ID's top-level items to `~/Desktop` (ID-prefixed), leave symlinks in JD dir; `--add` to keep existing
- [x] `jd unstage [id]` — scan Desktop for `JD:*`-tagged items, remove tags, clean up symlinks, move back; no arg = unstage all
- [x] Finder tagging via `xattr` (`com.apple.metadata:_kMDItemUserTags` binary plist)
- [x] MCP tools: `jd_stage`, `jd_unstage`, `jd_tag_add`, `jd_tag_remove`

### Repo Discovery
- [ ] Configurable `repo_roots` list in config (e.g. `~/repos`, `~/.config`)
  - Check each root itself for `.git` (not just its children) — `~/.config` will be a repo
  - Also scan immediate children for `.git` dirs (e.g. `~/repos/*`)
- [ ] `jd ln --repos` — scan repo roots, show unlinked repos, suggest/create JD symlinks
- [ ] Integrate with `jd validate` — flag repos without JD symlinks

### Cross-App Integration
- [x] Apple Notes connector (scan, validate, stub, create, open)
- [x] OmniFocus connector (scan, validate, open, tag, create)
- [ ] Email (IMAP) folder structure
- [ ] Obsidian vault alignment (if kept)
- [ ] `jd validate --notes` / `jd validate --omnifocus` for cross-app checks

### Agent Integration
- [ ] `jd claude [TARGET]` — launch Claude Code with cascading JD context
  - Walk up from CWD (or TARGET) to find nearest ID/category/area
  - Levels: system meta (00.00) → area meta (x0.00) → category meta (xx.00) → ID dir
  - At each level, collect files matching `stems × extensions` (cartesian product) + `extra` globs
  - `stems` and `extensions` define display order (stem > extension > level)
  - Child levels append new stems/extensions only if not already present (preserves ordering)
  - `extra` is local-only; `exclude` skips specific files at a given level
  - Each file gets a header: `# path/relative/to/jd-root/FILENAME.md`
  - Concatenate and pass via `claude --append-system-prompt`
  - Working dir pinned to nearest JD level (id → category → area → root) from CWD
  - JD tree has no `.git` — Claude Code won't auto-load CLAUDE.md, so `jd claude` handles all levels including current
  - `--dry-run` / `-n` — show which files would be included from which levels without launching
  - Configurable in `config.claude.include`:
    ```yaml
    config:
      claude:
        include:
          stems: [README, TODO, CLAUDE]
          extensions: [.md, .org, .txt]
          extra: ["*.md"]  # does not cascade; globs match the defining dir only
          exclude: []       # skip specific files at this level
    ```
  - Retire POLICY.md — fold content into README.md (context/conventions) and CLAUDE.md (agent directives) at the system level
  - Define standard doc purposes in 00.00 README.md:
    - **README.md** — what this level contains, conventions, context (for humans and agents)
    - **TODO.md** — open tasks and plans for this level
    - **CLAUDE.md** — agent-specific instructions (behavioral rules, constraints, preferences)
  - Any ALL-CAPS `.md` files at JD meta levels (REPOS.md, etc.) should be documented or folded into the standard three
- [ ] Make `jd` an OpenClaw skill so all agents can use it
- [ ] `jd.json` cached index (faster than filesystem scan every time)

### Known Issues
- [ ] No known issues
