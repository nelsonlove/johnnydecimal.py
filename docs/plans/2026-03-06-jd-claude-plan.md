# jd claude Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refresh the existing `jd claude` command — drop symlink lifecycle, simplify launch model, broaden TARGET, add `--show`, add tests.

**Architecture:** Modify existing `johnnydecimal/claude.py` and `johnnydecimal/cli.py`. The cascade/collection logic is already correct; we're simplifying `launch_claude()` and updating the CLI interface.

**Tech Stack:** Python, Click, pytest

---

### Task 1: Strip symlink lifecycle from claude.py

**Files:**
- Modify: `johnnydecimal/claude.py:201-255`

**Step 1: Delete `ensure_claude_symlink` function**

Remove lines 201-230 (the entire `ensure_claude_symlink` function).

**Step 2: Simplify `launch_claude`**

Replace the current `launch_claude` (lines 233-255) with:

```python
def launch_claude(working_dir: Path, context: str) -> Optional[int]:
    """Launch Claude Code with the given context."""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return None

    args = [claude_bin]
    if context:
        args.extend(["--append-system-prompt", context])

    result = subprocess.run(args, cwd=working_dir)
    return result.returncode
```

Note: removes `root` param, `dry_run` param, symlink creation, and symlink cleanup.

**Step 3: Verify no other code imports `ensure_claude_symlink`**

Run: `grep -r ensure_claude_symlink johnnydecimal/ tests/`
Expected: no matches outside claude.py itself.

**Step 4: Commit**

```bash
git add johnnydecimal/claude.py
git commit -m "Strip symlink lifecycle from jd claude"
```

---

### Task 2: Update CLI command

**Files:**
- Modify: `johnnydecimal/cli.py:3443-3505`

**Step 1: Change the command signature**

Replace the current `claude_cmd` (lines 3443-3505) with:

```python
@cli.command("claude")
@click.argument("target", required=False)
@click.option("--show", is_flag=True, help="Print cascading context to stdout instead of launching.")
def claude_cmd(target, show):
    """Launch Claude Code with cascading JD context.

    \b
    Walks up from CWD (or TARGET) to the nearest JD level, collects
    README, TODO, and CLAUDE files from each meta dir in the cascade,
    and launches Claude with the combined context.

    \b
    TARGET can be a JD ID (26.05), category (26), area (20-29), or name.

    \b
    Examples:
        jd claude              → from CWD, working dir ~/Documents
        jd claude 96.05        → context from 96.05, working dir is 96.05's path
        jd claude Recipes      → context from Recipes category
        jd claude --show       → print context without launching
    """
    from johnnydecimal.claude import (
        find_nearest_jd_level, build_context, format_context, launch_claude,
    )

    jd = get_root()
    root = jd.path

    # Resolve target to a path, determine working dir
    if target:
        path = _resolve_target(jd, target)
        if not path:
            click.echo(f"{target} not found.", err=True)
            raise SystemExit(1)
        working_dir = path
    else:
        path = Path.cwd()
        working_dir = Path.home() / "Documents"

    # Find nearest JD level for context cascade
    jd_level = find_nearest_jd_level(path)
    if not jd_level:
        # If not inside JD tree (no target), cascade from root
        jd_level = root

    # Build cascading context
    files = build_context(jd_level, root)
    context = format_context(files)

    if show:
        if not files:
            click.echo("No context files found.")
        else:
            click.echo(context)
        return

    if not shutil.which("claude"):
        click.echo("claude not found in PATH.", err=True)
        raise SystemExit(1)

    returncode = launch_claude(working_dir, context)
    if returncode:
        raise SystemExit(returncode)
```

Key changes:
- TARGET is plain string (not `JD_ID` type) so it accepts names, areas, categories
- `--dry-run` → `--show` (prints actual context, not just file list)
- No TARGET → working dir is `~/Documents`, cascade from CWD or root
- With TARGET → working dir is resolved path
- `launch_claude` called without `root` (signature changed in Task 1)

**Step 2: Remove unused import if `get_jd_root_dir` was only used here**

Check if `get_jd_root_dir` import on line 3463 is still needed. If not, remove it.

**Step 3: Commit**

```bash
git add johnnydecimal/cli.py
git commit -m "Update jd claude: broader TARGET, --show, ~/Documents default"
```

---

### Task 3: Write tests

**Files:**
- Create: `tests/test_claude.py`

**Step 1: Write tests for cascade logic**

```python
"""Tests for jd claude command."""

from unittest.mock import patch, MagicMock
from pathlib import Path
from click.testing import CliRunner

from johnnydecimal.cli import cli
from johnnydecimal.claude import (
    find_nearest_jd_level,
    get_cascade_levels,
    collect_files_at_level,
    build_context,
    format_context,
)


def _run(tmp_jd_root, monkeypatch, args):
    from johnnydecimal.models import JDSystem
    monkeypatch.setattr("johnnydecimal.cli.get_root", lambda: JDSystem(tmp_jd_root))
    runner = CliRunner()
    return runner.invoke(cli, args)


class TestCascadeLevels:
    def test_id_cascade(self, tmp_jd_root):
        """ID should cascade through root → area → category → id."""
        root = tmp_jd_root
        id_dir = root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"
        levels = get_cascade_levels(id_dir, root)
        names = [l.name for l in levels]
        assert names[0] == root.name  # root
        assert "20-29 Projects" in names
        assert "26 Recipes" in names
        assert "26.05 Sourdough" in names

    def test_category_cascade(self, tmp_jd_root):
        """Category should cascade through root → area → category."""
        root = tmp_jd_root
        cat_dir = root / "20-29 Projects" / "26 Recipes"
        levels = get_cascade_levels(cat_dir, root)
        names = [l.name for l in levels]
        assert "26.05 Sourdough" not in names
        assert "26 Recipes" in names

    def test_root_cascade(self, tmp_jd_root):
        """Root should return just root."""
        levels = get_cascade_levels(tmp_jd_root, tmp_jd_root)
        assert len(levels) == 1


class TestCollectFiles:
    def test_collects_readme(self, tmp_jd_root):
        """Collects README.md from a meta dir."""
        meta = tmp_jd_root / "00-09 Meta" / "00 Indices" / "00.00 Meta"
        (meta / "README.md").write_text("hello")
        files = collect_files_at_level(meta, ["README"], [".md"], [], [])
        assert len(files) == 1
        assert files[0].name == "README.md"

    def test_exclude_skips_file(self, tmp_jd_root):
        """Excluded files are not collected."""
        meta = tmp_jd_root / "00-09 Meta" / "00 Indices" / "00.00 Meta"
        (meta / "README.md").write_text("hello")
        (meta / "TODO.md").write_text("tasks")
        files = collect_files_at_level(meta, ["README", "TODO"], [".md"], [], ["TODO.md"])
        names = [f.name for f in files]
        assert "README.md" in names
        assert "TODO.md" not in names

    def test_extra_globs(self, tmp_jd_root):
        """Extra globs collect additional files."""
        meta = tmp_jd_root / "00-09 Meta" / "00 Indices" / "00.00 Meta"
        (meta / "NOTES.md").write_text("notes")
        files = collect_files_at_level(meta, [], [], ["*.md"], [])
        assert any(f.name == "NOTES.md" for f in files)


class TestBuildContext:
    def test_stem_ordering(self, tmp_jd_root):
        """Files are ordered stem > extension > level."""
        root = tmp_jd_root
        meta = root / "00-09 Meta" / "00 Indices" / "00.00 Meta"
        cat_meta = root / "20-29 Projects" / "26 Recipes" / "26.00 Recipes - Meta"
        (meta / "README.md").write_text("root readme")
        (meta / "TODO.md").write_text("root todo")
        (cat_meta / "README.md").write_text("cat readme")
        (cat_meta / "TODO.md").write_text("cat todo")

        id_dir = root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"
        files = build_context(id_dir, root)
        names = [Path(rel).name for _, rel in files]
        # All READMEs before all TODOs
        readme_indices = [i for i, n in enumerate(names) if n == "README.md"]
        todo_indices = [i for i, n in enumerate(names) if n == "TODO.md"]
        assert max(readme_indices) < min(todo_indices)


class TestFormatContext:
    def test_format_with_headers(self, tmp_jd_root):
        """Formatted context includes file headers."""
        meta = tmp_jd_root / "00-09 Meta" / "00 Indices" / "00.00 Meta"
        (meta / "README.md").write_text("hello world")
        files = build_context(tmp_jd_root, tmp_jd_root)
        output = format_context(files)
        assert "# " in output
        assert "hello world" in output
        assert "---" not in output  # only one file, no separator


class TestClaudeCli:
    def test_show_prints_context(self, tmp_jd_root, monkeypatch):
        """--show prints context to stdout."""
        meta = tmp_jd_root / "00-09 Meta" / "00 Indices" / "00.00 Meta"
        (meta / "README.md").write_text("system readme")
        monkeypatch.chdir(tmp_jd_root)
        result = _run(tmp_jd_root, monkeypatch, ["claude", "--show"])
        assert result.exit_code == 0
        assert "system readme" in result.output

    def test_show_no_files(self, tmp_jd_root, monkeypatch):
        """--show with no context files prints message."""
        monkeypatch.chdir(tmp_jd_root)
        result = _run(tmp_jd_root, monkeypatch, ["claude", "--show"])
        assert result.exit_code == 0
        assert "No context files found" in result.output

    def test_target_not_found(self, tmp_jd_root, monkeypatch):
        """Unknown target exits with error."""
        result = _run(tmp_jd_root, monkeypatch, ["claude", "99.99"])
        assert result.exit_code != 0
        assert "not found" in result.output

    @patch("johnnydecimal.claude.subprocess.run")
    @patch("johnnydecimal.claude.shutil.which", return_value="/usr/bin/claude")
    def test_launch_passes_working_dir(self, mock_which, mock_run, tmp_jd_root, monkeypatch):
        """Launch uses target path as working dir."""
        mock_run.return_value = MagicMock(returncode=0)
        monkeypatch.setattr("johnnydecimal.cli.shutil.which", lambda x: "/usr/bin/claude")
        result = _run(tmp_jd_root, monkeypatch, ["claude", "26.05"])
        if result.exit_code == 0:
            assert mock_run.called
            call_kwargs = mock_run.call_args
            cwd = call_kwargs.kwargs.get("cwd") or call_kwargs[1].get("cwd")
            assert "26.05" in str(cwd)
```

**Step 2: Run tests**

Run: `pytest tests/test_claude.py -v`
Expected: all pass.

**Step 3: Commit**

```bash
git add tests/test_claude.py
git commit -m "Add tests for jd claude"
```

---

### Task 4: Update TODO

**Files:**
- Modify: `TODO.md`

Mark `jd claude [TARGET]` as done. Keep the sub-items about per-level config under the `jd config` TODO (already done in design phase).

**Step 1: Mark done**

Change `- [ ] \`jd claude [TARGET]\`` to `- [x] \`jd claude [TARGET]\``.

Remove or mark done the sub-items that are now implemented:
- Walk up from CWD/TARGET ✓
- Levels cascade ✓
- stems × extensions ✓
- stem > extension > level ordering ✓
- extra/exclude ✓
- headers ✓
- `--append-system-prompt` ✓
- Working dir pinned ✓
- `--show` (was `--dry-run`) ✓

Keep as future/config items:
- Child levels append new stems/extensions (needs jd.yaml config reading)
- Configurable in `config.claude.include` (needs jd config)

**Step 2: Commit**

```bash
git add TODO.md
git commit -m "Mark jd claude as implemented in TODO"
```
