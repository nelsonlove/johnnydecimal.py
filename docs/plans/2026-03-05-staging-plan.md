# Staging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `jd tag add/remove`, `jd stage`, and `jd unstage` commands to surface JD items on Desktop and return them.

**Architecture:** New `johnnydecimal/staging.py` module handles Finder tag read/write (via `xattr` subprocess + `plistlib`) and stage/unstage logic. CLI commands in `cli.py` follow the existing group pattern. MCP tools wrap the staging module.

**Tech Stack:** Python stdlib only — `subprocess`, `plistlib`, `shutil`, `pathlib`.

**Design doc:** `docs/plans/2026-03-05-staging-design.md`

**Key codebase patterns:**
- CLI groups: `@cli.group()` + `@group.command("name")` (see `new`, `policy` groups in cli.py)
- File moves: `shutil.move()` for external, `Path.rename()` for internal
- Symlinks: `Path.symlink_to()`, `Path.is_symlink()`, `Path.unlink()`
- Tests: `tmp_jd_root` fixture from conftest.py, `monkeypatch` get_root, `CliRunner`
- MCP tools: `@mcp.tool()` returning dicts, errors as `{"error": "msg"}`
- Finder tags: `com.apple.metadata:_kMDItemUserTags` xattr, binary plist of string list
- Tag format: `JD:26.05` (consistent with OmniFocus connector's `_parse_jd_tags`)

---

### Task 1: Finder tag helpers — `staging.py` + tests

Create `johnnydecimal/staging.py` with:
- `_read_finder_tags(path) -> list[str]` — read via `xattr -px`, parse hex output with plistlib
- `_write_finder_tags(path, tags)` — write via `xattr -wx` with hex-encoded plist
- `get_jd_tags(path) -> list[str]` — filter to `JD:xx.xx` tags, return ID strings
- `add_jd_tag(path, jd_id)` — add `JD:xx.xx` tag, no-op if present
- `remove_jd_tag(path, jd_id=None)` — remove specific or all JD tags

Create `tests/test_staging.py` with tests mocking `_read_finder_tags`/`_write_finder_tags` (xattr doesn't work on tmpfs). Test classes: `TestGetJdTags`, `TestAddJdTag`, `TestRemoveJdTag`.

Commit: `"Add Finder tag helpers for staging"`

---

### Task 2: Core stage/unstage logic

Add to `staging.py`:
- `stage_items(id_dir, jd_id, desktop, dry_run=False) -> list[str]` — for each non-dotfile, non-symlink item: move to `desktop/xx.xx name`, add JD tag, leave symlink behind. Return names staged.
- `_strip_id_prefix(name, jd_id) -> str` — strip `xx.xx ` prefix if present
- `unstage_items(desktop, find_id_dir, filter_id=None, dry_run=False) -> list[dict]` — scan desktop for JD-tagged items, remove symlinks from ID dir, strip prefix, move back, remove tag. Handles both staged (symlink+prefix) and manually tagged (no symlink, no prefix) items.

Add to `tests/test_staging.py`: `TestStageItems` (files, dirs, dotfiles, existing symlinks, dry-run) and `TestUnstageItems` (tagged items, manually tagged, filter by ID, dry-run). Mock `add_jd_tag`/`get_jd_tags`/`remove_jd_tag` but use real filesystem for move/symlink.

Commit: `"Add stage/unstage core logic with symlinks"`

---

### Task 3: CLI — `jd tag add/remove`

Add to `cli.py`:
- Import `add_jd_tag, remove_jd_tag, stage_items, unstage_items` from staging
- `@cli.group() def tag()` group
- `@tag.command("add")` — takes `jd_id` (JD_ID type) + `path` (click.Path(exists=True)), validates ID exists, calls `add_jd_tag`
- `@tag.command("remove")` — takes `path` + optional `--id`, calls `remove_jd_tag`

Add `TestTagAddCli` and `TestTagRemoveCli` to tests — use `_run` helper with monkeypatched get_root, mock `add_jd_tag`/`remove_jd_tag`.

Commit: `"Add jd tag add/remove CLI commands"`

---

### Task 4: CLI — `jd stage`, `jd unstage`

Add to `cli.py`:
- `DESKTOP = Path.home() / "Desktop"` module-level constant
- `@cli.command() def stage(jd_id, dry_run)` — resolve ID, call `stage_items`, print results with `(dry run)` prefix
- `@cli.command() def unstage(jd_id, dry_run)` — jd_id optional, call `unstage_items` with `find_id_dir` closure over JD system, print results

Add `TestStageCli` and `TestUnstageCli` — monkeypatch `DESKTOP`, mock `stage_items`/`unstage_items`.

Commit: `"Add jd stage and jd unstage CLI commands"`

---

### Task 5: MCP tools

Add to `mcp_server.py`:
- `DESKTOP = Path.home() / "Desktop"`
- `@mcp.tool() jd_stage(jd_id)` — wraps `stage_items`, returns `{"error": None, "jd_id": ..., "staged": [...]}`
- `@mcp.tool() jd_unstage(jd_id=None)` — wraps `unstage_items`
- `@mcp.tool() jd_tag_add(jd_id, path)` — wraps `add_jd_tag`
- `@mcp.tool() jd_tag_remove(path, jd_id=None)` — wraps `remove_jd_tag`

Add `TestStageMcp` tests — monkeypatch `_get_root` and `DESKTOP`.

Commit: `"Add MCP tools for stage, unstage, tag add/remove"`

---

### Task 6: Round-trip integration tests + full suite

Add `TestStagingRoundTrip`:
- `test_stage_then_unstage_restores_original_state` — stage files+dirs, verify symlinks, unstage, verify original state restored and desktop clean
- `test_manually_tagged_then_unstage` — manually tagged item on desktop gets moved to correct ID dir

Run full suite: `pytest tests/ -v` — all existing + new tests pass.

Commit: `"Add staging round-trip integration tests"`
