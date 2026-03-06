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
- [ ] `jd stats` — system-wide statistics (total IDs, sizes, age distribution)
- [ ] `jd gc` — clean up empty dirs, broken symlinks, .DS_Store
- [ ] Unified `jd.yaml` config file (replaces `.johnnydecimal.yaml`)
  - Two top-level keys: `policy:` (validation rules) and `config:` (behavior)
  - `jd.example.yaml` in the jd-cli repo as documented default
  - Cascading: JD root → area meta dir → category meta dir → ID meta dir (each overrides)
  - Migrate existing `.johnnydecimal.yaml` policy into `jd.yaml` `policy:` key
  - `config:` holds repo roots, staging prefs, ignore patterns, external drives, etc.

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
- [ ] `jd tag add <id> <path>` — add `JD:xx.xx` Finder tag to a file/dir (no move)
- [ ] `jd tag remove <path>` — strip `JD:*` Finder tag
- [ ] `jd stage <id>` — tag + move ID's top-level items to `~/Desktop` (ID-prefixed), leave symlinks in JD dir
- [ ] `jd unstage [id]` — scan Desktop for `JD:*`-tagged items, remove tags, clean up symlinks, move back; no arg = unstage all
- [ ] Finder tagging via `xattr` (`com.apple.metadata:_kMDItemUserTags` binary plist)

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
- [ ] Make `jd` an OpenClaw skill so all agents can use it
- [ ] `jd.json` cached index (faster than filesystem scan every time)

### Known Issues
- [ ] No known issues
