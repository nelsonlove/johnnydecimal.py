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
- [x] Cascading policy system (`.johnnydecimal.yaml`, pattern matching)
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
- [ ] Config file (`~/.config/johnnydecimal/config.yaml`) for root path, external drives, ignore patterns

### Validation
- [ ] Gap detection — missing expected IDs in a sequence
- [ ] macOS alias detection (different from symlinks) — `mdls` or similar
- [ ] External drive awareness — skip gracefully if unmounted
- [ ] `jd validate --fix` — auto-fix simple issues (en-dash → hyphen, trailing spaces)

### Tab Completion
- [ ] Test in real shell (Click's `_JD_COMPLETE=zsh_complete` needs `COMP_WORDS`)
- [ ] Bash/fish completion support

### Cross-App Integration
- [ ] Apple Notes validation (sparse subset, JD naming match)
- [ ] OmniFocus mapping (project/folder ↔ JD category)
- [ ] Email (IMAP) folder structure
- [ ] Obsidian vault alignment (if kept)
- [ ] `jd validate --notes` / `jd validate --omnifocus` for cross-app checks

### Agent Integration
- [ ] Make `jd` an OpenClaw skill so all agents can use it
- [ ] `jd.json` cached index (faster than filesystem scan every time)

### Known Issues
- [ ] No known issues
