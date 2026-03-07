# jd claude Design

## Summary

`jd claude [TARGET]` launches Claude Code with cascading JD context injected via `--append-system-prompt`.

## Launch Model

- **No TARGET**: working dir is `~/Documents`, cascade starts from CWD (or root if CWD isn't in the JD tree)
- **With TARGET**: working dir is the resolved path (ID dir, category dir, area dir, or root)
- TARGET accepts JD IDs (`26.05`), categories (`26`), areas (`20-29`), and names (`Recipes`) — same resolution as `jd cd`
- `--show`: print concatenated context to stdout instead of launching
- No `.claude/` management — handled externally via dotfiles

## Context Cascade

For `jd claude 26.05`:

1. Resolve target to filesystem path
2. Build cascade chain: root → area (`20-29`) → category (`26`) → ID (`26.05`)
3. At each level, find context dir: meta dir for root/area/category (`xx.00`), ID dir for IDs
4. Collect files via `stems × extensions` cartesian product, then `extra` globs
5. Ordering: stem > extension > level (all READMEs together across levels, then TODOs, etc.)
6. Each file gets header: `# path/relative/to/jd-root/FILENAME.md`
7. Concatenate with `---` separators, pass via `--append-system-prompt`

**Defaults**: `README, TODO, CLAUDE` × `.md, .org, .txt`

**Per-level config** (future, when `jd config` lands): each level's `jd.yaml` can define `config.claude.include` with `stems`, `extensions`, `extra`, `exclude`. Child levels append new stems/extensions only if not already present. `extra` is local-only. `exclude` skips files at that level.

## Changes

**`claude.py`:**
- Drop `ensure_claude_symlink()` and symlink cleanup in `launch_claude()`
- `launch_claude()` takes working dir, passes to `subprocess.run(cwd=...)`

**`cli.py`:**
- TARGET accepts IDs, categories, areas, names (not just `JD_ID`)
- Default working dir: `~/Documents`; with TARGET: resolved path
- Replace `--dry-run` with `--show`

**Tests:**
- `test_claude.py`: cascade ordering, file collection, `--show` output, TARGET resolution
- Mock `subprocess.run` for launch tests
