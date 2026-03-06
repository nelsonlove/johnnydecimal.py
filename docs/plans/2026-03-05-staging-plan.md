# Staging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `jd tag add/remove`, `jd stage`, and `jd unstage` commands to surface JD items on Desktop and return them.

**Architecture:** New `johnnydecimal/staging.py` module handles Finder tag read/write (via `xattr` subprocess + `plistlib`) and stage/unstage logic. CLI commands in `cli.py` follow the existing group pattern (`jd tag`, `jd stage`, `jd unstage`). MCP tools wrap the staging module.

**Tech Stack:** Python stdlib only — `subprocess` for `/usr/bin/xattr`, `plistlib` for binary plist encoding/decoding, `shutil.move` for file moves, `Path.symlink_to` for symlinks.

---

### Task 1: Finder tag helpers in `staging.py`

**Files:**
- Create: `johnnydecimal/staging.py`
- Create: `tests/test_staging.py`

**Step 1: Write failing tests for tag helpers**

Note: `xattr` calls only work on real macOS filesystems (not `tmp_path` which may be on a tmpfs). Tests must mock `subprocess.run`.

```python
"""Tests for staging module."""

import plistlib
import re
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from johnnydecimal.staging import get_jd_tags, add_jd_tag, remove_jd_tag


class TestGetJdTags:
    def test_returns_jd_tags_from_xattr(self):
        tags = ["JD:26.05", "Work", "JD:11.03"]
        plist_bytes = plistlib.dumps(tags)
        mock_result = MagicMock(returncode=0, stdout=plist_bytes)
        with patch("subprocess.run", return_value=mock_result):
            result = get_jd_tags(Path("/fake/file"))
        assert result == ["26.05", "11.03"]

    def test_returns_empty_when_no_xattr(self):
        mock_result = MagicMock(returncode=1, stdout=b"", stderr=b"No such xattr")
        with patch("subprocess.run", return_value=mock_result):
            result = get_jd_tags(Path("/fake/file"))
        assert result == []

    def test_returns_empty_when_no_jd_tags(self):
        tags = ["Work", "Personal"]
        plist_bytes = plistlib.dumps(tags)
        mock_result = MagicMock(returncode=0, stdout=plist_bytes)
        with patch("subprocess.run", return_value=mock_result):
            result = get_jd_tags(Path("/fake/file"))
        assert result == []


class TestAddJdTag:
    def test_adds_tag_to_file_with_no_existing_tags(self):
        # First call: read existing tags (none)
        read_result = MagicMock(returncode=1, stdout=b"", stderr=b"No such xattr")
        # Second call: write tags
        write_result = MagicMock(returncode=0)
        with patch("subprocess.run", side_effect=[read_result, write_result]) as mock_run:
            add_jd_tag(Path("/fake/file"), "26.05")
        # Verify write was called with plist containing JD:26.05
        write_call = mock_run.call_args_list[1]
        written_plist = write_call[0][0][4]  # 5th arg: the plist hex string
        # The command is: xattr -w -x com.apple.metadata:_kMDItemUserTags <hex> <path>
        written_bytes = bytes.fromhex(written_plist)
        written_tags = plistlib.loads(written_bytes)
        assert "JD:26.05" in written_tags

    def test_preserves_existing_tags(self):
        existing = ["Work"]
        read_result = MagicMock(returncode=0, stdout=plistlib.dumps(existing))
        write_result = MagicMock(returncode=0)
        with patch("subprocess.run", side_effect=[read_result, write_result]) as mock_run:
            add_jd_tag(Path("/fake/file"), "26.05")
        write_call = mock_run.call_args_list[1]
        written_bytes = bytes.fromhex(write_call[0][0][4])
        written_tags = plistlib.loads(written_bytes)
        assert "Work" in written_tags
        assert "JD:26.05" in written_tags

    def test_skips_if_tag_already_present(self):
        existing = ["JD:26.05"]
        read_result = MagicMock(returncode=0, stdout=plistlib.dumps(existing))
        with patch("subprocess.run", side_effect=[read_result]) as mock_run:
            add_jd_tag(Path("/fake/file"), "26.05")
        assert mock_run.call_count == 1  # only read, no write


class TestRemoveJdTag:
    def test_removes_jd_tag_preserving_others(self):
        existing = ["JD:26.05", "Work"]
        read_result = MagicMock(returncode=0, stdout=plistlib.dumps(existing))
        write_result = MagicMock(returncode=0)
        with patch("subprocess.run", side_effect=[read_result, write_result]) as mock_run:
            remove_jd_tag(Path("/fake/file"), "26.05")
        write_call = mock_run.call_args_list[1]
        written_bytes = bytes.fromhex(write_call[0][0][4])
        written_tags = plistlib.loads(written_bytes)
        assert "Work" in written_tags
        assert "JD:26.05" not in written_tags

    def test_removes_all_jd_tags_when_no_id_specified(self):
        existing = ["JD:26.05", "JD:11.03", "Work"]
        read_result = MagicMock(returncode=0, stdout=plistlib.dumps(existing))
        write_result = MagicMock(returncode=0)
        with patch("subprocess.run", side_effect=[read_result, write_result]) as mock_run:
            remove_jd_tag(Path("/fake/file"))
        write_call = mock_run.call_args_list[1]
        written_bytes = bytes.fromhex(write_call[0][0][4])
        written_tags = plistlib.loads(written_bytes)
        assert written_tags == ["Work"]
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_staging.py -v`
Expected: FAIL with ImportError (staging module doesn't exist)

**Step 3: Implement tag helpers**

```python
"""Staging — surface JD items on Desktop and return them."""

import plistlib
import re
import subprocess
from pathlib import Path

XATTR_KEY = "com.apple.metadata:_kMDItemUserTags"
JD_TAG_RE = re.compile(r"^JD:(\d{2}\.\d{2})$")


def _read_finder_tags(path: Path) -> list[str]:
    """Read all Finder tags from a file/dir. Returns [] if none."""
    result = subprocess.run(
        ["/usr/bin/xattr", "-px", XATTR_KEY, str(path)],
        capture_output=True,
    )
    if result.returncode != 0:
        return []
    # xattr -px outputs space-separated hex lines; join and decode
    hex_str = result.stdout.replace(b"\n", b" ").decode().strip()
    raw = bytes.fromhex(hex_str.replace(" ", ""))
    return plistlib.loads(raw)


def _write_finder_tags(path: Path, tags: list[str]) -> None:
    """Write Finder tags to a file/dir."""
    plist_bytes = plistlib.dumps(tags)
    hex_str = plist_bytes.hex()
    subprocess.run(
        ["/usr/bin/xattr", "-wx", XATTR_KEY, hex_str, str(path)],
        check=True,
    )


def get_jd_tags(path: Path) -> list[str]:
    """Return list of JD ID strings tagged on this path. E.g. ['26.05']."""
    tags = _read_finder_tags(path)
    result = []
    for tag in tags:
        m = JD_TAG_RE.match(tag)
        if m:
            result.append(m.group(1))
    return result


def add_jd_tag(path: Path, jd_id: str) -> None:
    """Add a JD:xx.xx Finder tag. No-op if already present."""
    tag_name = f"JD:{jd_id}"
    tags = _read_finder_tags(path)
    if tag_name in tags:
        return
    tags.append(tag_name)
    _write_finder_tags(path, tags)


def remove_jd_tag(path: Path, jd_id: str | None = None) -> None:
    """Remove JD Finder tag(s). If jd_id given, remove that one; else remove all JD:* tags."""
    tags = _read_finder_tags(path)
    if jd_id:
        new_tags = [t for t in tags if t != f"JD:{jd_id}"]
    else:
        new_tags = [t for t in tags if not JD_TAG_RE.match(t)]
    if new_tags != tags:
        _write_finder_tags(path, new_tags)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_staging.py -v`
Expected: The mock-based tests need adjustment — `_read_finder_tags` uses `xattr -px` (hex output) not binary. Update the mocks to match. The implementation uses `xattr -px` which returns hex, so mock `_read_finder_tags` and `_write_finder_tags` directly instead:

Replace the test mocks — patch at the helper level instead of `subprocess.run`:

```python
"""Tests for staging module."""

import plistlib
import re
from pathlib import Path
from unittest.mock import patch, call

import pytest

from johnnydecimal.staging import get_jd_tags, add_jd_tag, remove_jd_tag


class TestGetJdTags:
    def test_returns_jd_tags(self):
        with patch("johnnydecimal.staging._read_finder_tags", return_value=["JD:26.05", "Work", "JD:11.03"]):
            assert get_jd_tags(Path("/fake")) == ["26.05", "11.03"]

    def test_returns_empty_when_no_tags(self):
        with patch("johnnydecimal.staging._read_finder_tags", return_value=[]):
            assert get_jd_tags(Path("/fake")) == []

    def test_returns_empty_when_no_jd_tags(self):
        with patch("johnnydecimal.staging._read_finder_tags", return_value=["Work", "Personal"]):
            assert get_jd_tags(Path("/fake")) == []


class TestAddJdTag:
    def test_adds_tag_when_none_exist(self):
        with patch("johnnydecimal.staging._read_finder_tags", return_value=[]) as mock_read, \
             patch("johnnydecimal.staging._write_finder_tags") as mock_write:
            add_jd_tag(Path("/fake"), "26.05")
        mock_write.assert_called_once_with(Path("/fake"), ["JD:26.05"])

    def test_preserves_existing_tags(self):
        with patch("johnnydecimal.staging._read_finder_tags", return_value=["Work"]), \
             patch("johnnydecimal.staging._write_finder_tags") as mock_write:
            add_jd_tag(Path("/fake"), "26.05")
        mock_write.assert_called_once_with(Path("/fake"), ["Work", "JD:26.05"])

    def test_skips_if_already_tagged(self):
        with patch("johnnydecimal.staging._read_finder_tags", return_value=["JD:26.05"]), \
             patch("johnnydecimal.staging._write_finder_tags") as mock_write:
            add_jd_tag(Path("/fake"), "26.05")
        mock_write.assert_not_called()


class TestRemoveJdTag:
    def test_removes_specific_tag(self):
        with patch("johnnydecimal.staging._read_finder_tags", return_value=["JD:26.05", "Work"]), \
             patch("johnnydecimal.staging._write_finder_tags") as mock_write:
            remove_jd_tag(Path("/fake"), "26.05")
        mock_write.assert_called_once_with(Path("/fake"), ["Work"])

    def test_removes_all_jd_tags(self):
        with patch("johnnydecimal.staging._read_finder_tags", return_value=["JD:26.05", "JD:11.03", "Work"]), \
             patch("johnnydecimal.staging._write_finder_tags") as mock_write:
            remove_jd_tag(Path("/fake"))
        mock_write.assert_called_once_with(Path("/fake"), ["Work"])

    def test_noop_when_tag_not_present(self):
        with patch("johnnydecimal.staging._read_finder_tags", return_value=["Work"]), \
             patch("johnnydecimal.staging._write_finder_tags") as mock_write:
            remove_jd_tag(Path("/fake"), "26.05")
        mock_write.assert_not_called()
```

**Step 5: Run tests**

Run: `pytest tests/test_staging.py -v`
Expected: All 9 pass

**Step 6: Commit**

```bash
git add johnnydecimal/staging.py tests/test_staging.py
git commit -m "Add Finder tag helpers for staging"
```

---

### Task 2: `stage_items` and `unstage_items` core logic

**Files:**
- Modify: `johnnydecimal/staging.py`
- Modify: `tests/test_staging.py`

**Step 1: Write failing tests for stage_items**

These tests use real filesystem (tmp_path) but mock the tag helpers since xattr doesn't work on tmpfs.

```python
class TestStageItems:
    """Test stage_items() which moves items to desktop and leaves symlinks."""

    def test_stages_files_to_desktop(self, tmp_path):
        # Set up a JD ID dir with a file
        id_dir = tmp_path / "26.05 Sourdough"
        id_dir.mkdir()
        (id_dir / "recipe.txt").write_text("flour and water")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()

        with patch("johnnydecimal.staging.add_jd_tag"):
            result = stage_items(id_dir, "26.05", desktop)

        # File moved to desktop with ID prefix
        assert (desktop / "26.05 recipe.txt").exists()
        assert (desktop / "26.05 recipe.txt").read_text() == "flour and water"
        # Symlink left behind
        assert (id_dir / "recipe.txt").is_symlink()
        assert (id_dir / "recipe.txt").resolve() == (desktop / "26.05 recipe.txt").resolve()
        assert result == ["recipe.txt"]

    def test_stages_directories(self, tmp_path):
        id_dir = tmp_path / "26.05 Sourdough"
        id_dir.mkdir()
        subdir = id_dir / "photos"
        subdir.mkdir()
        (subdir / "bread.jpg").write_text("img")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()

        with patch("johnnydecimal.staging.add_jd_tag"):
            result = stage_items(id_dir, "26.05", desktop)

        assert (desktop / "26.05 photos").is_dir()
        assert (desktop / "26.05 photos" / "bread.jpg").read_text() == "img"
        assert (id_dir / "photos").is_symlink()

    def test_skips_dotfiles(self, tmp_path):
        id_dir = tmp_path / "26.05 Sourdough"
        id_dir.mkdir()
        (id_dir / ".DS_Store").write_text("x")
        (id_dir / "recipe.txt").write_text("flour")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()

        with patch("johnnydecimal.staging.add_jd_tag"):
            result = stage_items(id_dir, "26.05", desktop)

        assert result == ["recipe.txt"]
        assert not (desktop / "26.05 .DS_Store").exists()

    def test_skips_existing_symlinks(self, tmp_path):
        id_dir = tmp_path / "26.05 Sourdough"
        id_dir.mkdir()
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        # Pre-existing symlink in ID dir (e.g. already staged)
        (desktop / "26.05 old.txt").write_text("old")
        (id_dir / "old.txt").symlink_to(desktop / "26.05 old.txt")

        with patch("johnnydecimal.staging.add_jd_tag"):
            result = stage_items(id_dir, "26.05", desktop)

        assert result == []  # nothing new to stage

    def test_dry_run_does_not_move(self, tmp_path):
        id_dir = tmp_path / "26.05 Sourdough"
        id_dir.mkdir()
        (id_dir / "recipe.txt").write_text("flour")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()

        with patch("johnnydecimal.staging.add_jd_tag"):
            result = stage_items(id_dir, "26.05", desktop, dry_run=True)

        assert result == ["recipe.txt"]
        # Nothing actually moved
        assert (id_dir / "recipe.txt").exists()
        assert not (id_dir / "recipe.txt").is_symlink()
        assert not (desktop / "26.05 recipe.txt").exists()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_staging.py::TestStageItems -v`
Expected: ImportError for `stage_items`

**Step 3: Implement `stage_items`**

Add to `johnnydecimal/staging.py`:

```python
import shutil


def stage_items(
    id_dir: Path, jd_id: str, desktop: Path, dry_run: bool = False
) -> list[str]:
    """Move top-level items from id_dir to desktop, leaving symlinks behind.

    Returns list of item names that were (or would be) staged.
    """
    staged = []
    for item in sorted(id_dir.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_symlink():
            continue
        staged.append(item.name)
        if dry_run:
            continue
        desktop_name = f"{jd_id} {item.name}"
        desktop_path = desktop / desktop_name
        shutil.move(str(item), str(desktop_path))
        add_jd_tag(desktop_path, jd_id)
        item.symlink_to(desktop_path)
    return staged
```

**Step 4: Run tests**

Run: `pytest tests/test_staging.py::TestStageItems -v`
Expected: All 5 pass

**Step 5: Write failing tests for `unstage_items`**

```python
class TestUnstageItems:
    """Test unstage_items() which scans desktop and moves items back."""

    def test_unstages_tagged_items(self, tmp_path):
        id_dir = tmp_path / "26.05 Sourdough"
        id_dir.mkdir()
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        # Simulate a staged file
        (desktop / "26.05 recipe.txt").write_text("flour")
        (id_dir / "recipe.txt").symlink_to(desktop / "26.05 recipe.txt")

        with patch("johnnydecimal.staging.get_jd_tags", return_value=["26.05"]), \
             patch("johnnydecimal.staging.remove_jd_tag"):
            result = unstage_items(desktop, find_id_dir=lambda jd_id: id_dir)

        # File moved back, symlink removed
        assert (id_dir / "recipe.txt").exists()
        assert not (id_dir / "recipe.txt").is_symlink()
        assert (id_dir / "recipe.txt").read_text() == "flour"
        assert not (desktop / "26.05 recipe.txt").exists()
        assert len(result) == 1

    def test_unstages_manually_tagged_items(self, tmp_path):
        """Items tagged with jd tag add (no symlink, no prefix)."""
        id_dir = tmp_path / "26.05 Sourdough"
        id_dir.mkdir()
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        (desktop / "random.pdf").write_text("data")

        with patch("johnnydecimal.staging.get_jd_tags", return_value=["26.05"]), \
             patch("johnnydecimal.staging.remove_jd_tag"):
            result = unstage_items(desktop, find_id_dir=lambda jd_id: id_dir)

        assert (id_dir / "random.pdf").exists()
        assert not (desktop / "random.pdf").exists()

    def test_filters_by_id(self, tmp_path):
        id_dir_26 = tmp_path / "26.05 Sourdough"
        id_dir_26.mkdir()
        id_dir_11 = tmp_path / "11.03 Taxes"
        id_dir_11.mkdir()
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        (desktop / "26.05 recipe.txt").write_text("flour")
        (desktop / "11.03 tax.pdf").write_text("taxes")

        def mock_tags(path):
            if "26.05" in path.name:
                return ["26.05"]
            if "11.03" in path.name:
                return ["11.03"]
            return []

        def find_dir(jd_id):
            return id_dir_26 if jd_id == "26.05" else id_dir_11

        with patch("johnnydecimal.staging.get_jd_tags", side_effect=mock_tags), \
             patch("johnnydecimal.staging.remove_jd_tag"):
            result = unstage_items(desktop, find_id_dir=find_dir, filter_id="26.05")

        assert (id_dir_26 / "recipe.txt").exists()
        assert (desktop / "11.03 tax.pdf").exists()  # not unstaged

    def test_dry_run_does_not_move(self, tmp_path):
        id_dir = tmp_path / "26.05 Sourdough"
        id_dir.mkdir()
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        (desktop / "26.05 recipe.txt").write_text("flour")
        (id_dir / "recipe.txt").symlink_to(desktop / "26.05 recipe.txt")

        with patch("johnnydecimal.staging.get_jd_tags", return_value=["26.05"]), \
             patch("johnnydecimal.staging.remove_jd_tag"):
            result = unstage_items(desktop, find_id_dir=lambda jd_id: id_dir, dry_run=True)

        assert len(result) == 1
        assert (desktop / "26.05 recipe.txt").exists()  # still there
        assert (id_dir / "recipe.txt").is_symlink()  # still a symlink
```

**Step 6: Run tests to verify they fail**

Run: `pytest tests/test_staging.py::TestUnstageItems -v`
Expected: ImportError for `unstage_items`

**Step 7: Implement `unstage_items`**

Add to `johnnydecimal/staging.py`:

```python
from typing import Callable


def _strip_id_prefix(name: str, jd_id: str) -> str:
    """Strip 'xx.xx ' prefix from a filename if present."""
    prefix = f"{jd_id} "
    if name.startswith(prefix):
        return name[len(prefix):]
    return name


def unstage_items(
    desktop: Path,
    find_id_dir: Callable[[str], Path | None],
    filter_id: str | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Scan desktop for JD-tagged items and move them back.

    find_id_dir: callable that maps a JD ID string to its directory Path (or None).
    filter_id: if set, only unstage items tagged with this ID.
    Returns list of dicts: [{"name": ..., "jd_id": ..., "dest": ...}].
    """
    unstaged = []
    for item in sorted(desktop.iterdir()):
        if item.name.startswith("."):
            continue
        jd_ids = get_jd_tags(item)
        if not jd_ids:
            continue
        jd_id = jd_ids[0]
        if filter_id and jd_id != filter_id:
            continue
        id_dir = find_id_dir(jd_id)
        if id_dir is None:
            continue
        original_name = _strip_id_prefix(item.name, jd_id)
        dest = id_dir / original_name
        unstaged.append({"name": item.name, "jd_id": jd_id, "dest": str(dest)})
        if dry_run:
            continue
        # Remove symlink in ID dir if it exists
        if dest.is_symlink():
            dest.unlink()
        shutil.move(str(item), str(dest))
        remove_jd_tag(dest, jd_id)
    return unstaged
```

**Step 8: Run tests**

Run: `pytest tests/test_staging.py -v`
Expected: All pass

**Step 9: Commit**

```bash
git add johnnydecimal/staging.py tests/test_staging.py
git commit -m "Add stage/unstage core logic with symlinks"
```

---

### Task 3: CLI commands — `jd tag add`, `jd tag remove`

**Files:**
- Modify: `johnnydecimal/cli.py`
- Modify: `tests/test_staging.py`

**Step 1: Write failing tests**

```python
from click.testing import CliRunner
from johnnydecimal.cli import cli


def _run(tmp_jd_root, monkeypatch, args):
    from johnnydecimal.models import JDSystem
    monkeypatch.setattr("johnnydecimal.cli.get_root", lambda: JDSystem(tmp_jd_root))
    runner = CliRunner()
    return runner.invoke(cli, args)


class TestTagAddCli:
    def test_tags_a_file(self, tmp_jd_root, monkeypatch):
        target = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough" / "recipe.txt"
        target.write_text("flour")
        with patch("johnnydecimal.cli.add_jd_tag") as mock_tag:
            result = _run(tmp_jd_root, monkeypatch, ["tag", "add", "26.05", str(target)])
        assert result.exit_code == 0
        mock_tag.assert_called_once_with(target, "26.05")

    def test_error_when_path_missing(self, tmp_jd_root, monkeypatch):
        result = _run(tmp_jd_root, monkeypatch, ["tag", "add", "26.05", "/nonexistent"])
        assert result.exit_code != 0

    def test_error_when_id_not_found(self, tmp_jd_root, monkeypatch):
        f = tmp_jd_root / "somefile"
        f.write_text("x")
        result = _run(tmp_jd_root, monkeypatch, ["tag", "add", "99.99", str(f)])
        assert result.exit_code != 0


class TestTagRemoveCli:
    def test_removes_tag(self, tmp_jd_root, monkeypatch):
        target = tmp_jd_root / "somefile"
        target.write_text("x")
        with patch("johnnydecimal.cli.remove_jd_tag") as mock_rm:
            result = _run(tmp_jd_root, monkeypatch, ["tag", "remove", str(target)])
        assert result.exit_code == 0
        mock_rm.assert_called_once_with(target)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_staging.py::TestTagAddCli -v`
Expected: FAIL — no `tag` command group

**Step 3: Implement CLI commands**

Add to `johnnydecimal/cli.py` (after imports, add `from johnnydecimal.staging import add_jd_tag, remove_jd_tag, stage_items, unstage_items`):

```python
@cli.group()
def tag():
    """Manage JD Finder tags."""
    pass


@tag.command("add")
@click.argument("jd_id", type=JD_ID)
@click.argument("path", type=click.Path(exists=True))
def tag_add(jd_id, path):
    """Tag a file or directory with a JD ID.

    \b
    Example:
        jd tag add 26.05 ~/Desktop/recipe.pdf
    """
    jd = get_root()
    target = jd.find_by_id(jd_id)
    if not target:
        click.echo(f"ID {jd_id} not found.", err=True)
        raise SystemExit(1)
    target_path = Path(path).resolve()
    add_jd_tag(target_path, jd_id)
    click.echo(f"Tagged {target_path.name} with JD:{jd_id}")


@tag.command("remove")
@click.argument("path", type=click.Path(exists=True))
@click.option("--id", "jd_id", default=None, type=JD_ID, help="Remove only this JD tag (default: all)")
def tag_remove(path, jd_id):
    """Remove JD Finder tag(s) from a file or directory.

    \b
    Example:
        jd tag remove ~/Desktop/recipe.pdf
        jd tag remove --id 26.05 ~/Desktop/recipe.pdf
    """
    target_path = Path(path).resolve()
    remove_jd_tag(target_path, jd_id)
    if jd_id:
        click.echo(f"Removed JD:{jd_id} tag from {target_path.name}")
    else:
        click.echo(f"Removed all JD tags from {target_path.name}")
```

**Step 4: Run tests**

Run: `pytest tests/test_staging.py::TestTagAddCli tests/test_staging.py::TestTagRemoveCli -v`
Expected: All pass

**Step 5: Commit**

```bash
git add johnnydecimal/cli.py tests/test_staging.py
git commit -m "Add jd tag add/remove CLI commands"
```

---

### Task 4: CLI commands — `jd stage`, `jd unstage`

**Files:**
- Modify: `johnnydecimal/cli.py`
- Modify: `tests/test_staging.py`

**Step 1: Write failing tests**

```python
class TestStageCli:
    def test_stages_id_contents(self, tmp_jd_root, monkeypatch):
        sourdough = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"
        (sourdough / "recipe.txt").write_text("flour")
        desktop = tmp_jd_root / "Desktop"
        desktop.mkdir()

        with patch("johnnydecimal.cli.stage_items", return_value=["recipe.txt"]) as mock_stage, \
             patch("johnnydecimal.staging.DESKTOP", desktop):
            monkeypatch.setattr("johnnydecimal.cli.DESKTOP", desktop)
            result = _run(tmp_jd_root, monkeypatch, ["stage", "26.05"])

        assert result.exit_code == 0
        assert "recipe.txt" in result.output

    def test_error_when_id_not_found(self, tmp_jd_root, monkeypatch):
        result = _run(tmp_jd_root, monkeypatch, ["stage", "99.99"])
        assert result.exit_code != 0

    def test_dry_run(self, tmp_jd_root, monkeypatch):
        sourdough = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"
        (sourdough / "recipe.txt").write_text("flour")
        desktop = tmp_jd_root / "Desktop"
        desktop.mkdir()

        with patch("johnnydecimal.cli.stage_items", return_value=["recipe.txt"]) as mock_stage:
            monkeypatch.setattr("johnnydecimal.cli.DESKTOP", desktop)
            result = _run(tmp_jd_root, monkeypatch, ["stage", "-n", "26.05"])

        assert result.exit_code == 0
        assert "dry run" in result.output.lower()
        mock_stage.assert_called_once()
        assert mock_stage.call_args[1].get("dry_run") or mock_stage.call_args[0][3] is True


class TestUnstageCli:
    def test_unstages_all(self, tmp_jd_root, monkeypatch):
        desktop = tmp_jd_root / "Desktop"
        desktop.mkdir()
        unstaged_data = [{"name": "26.05 recipe.txt", "jd_id": "26.05", "dest": "/some/path"}]

        with patch("johnnydecimal.cli.unstage_items", return_value=unstaged_data) as mock_unstage:
            monkeypatch.setattr("johnnydecimal.cli.DESKTOP", desktop)
            result = _run(tmp_jd_root, monkeypatch, ["unstage"])

        assert result.exit_code == 0
        assert "recipe.txt" in result.output

    def test_unstages_specific_id(self, tmp_jd_root, monkeypatch):
        desktop = tmp_jd_root / "Desktop"
        desktop.mkdir()

        with patch("johnnydecimal.cli.unstage_items", return_value=[]) as mock_unstage:
            monkeypatch.setattr("johnnydecimal.cli.DESKTOP", desktop)
            result = _run(tmp_jd_root, monkeypatch, ["unstage", "26.05"])

        assert result.exit_code == 0
        mock_unstage.assert_called_once()
        # Verify filter_id was passed
        call_kwargs = mock_unstage.call_args
        assert "26.05" in str(call_kwargs)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_staging.py::TestStageCli -v`
Expected: FAIL

**Step 3: Implement CLI commands**

Add to `johnnydecimal/cli.py`:

```python
DESKTOP = Path.home() / "Desktop"


@cli.command()
@click.argument("jd_id", type=JD_ID)
@click.option("-n", "--dry-run", is_flag=True, help="Show what would be staged without doing it")
def stage(jd_id, dry_run):
    """Stage a JD ID's contents to the Desktop.

    Moves all top-level items to ~/Desktop (prefixed with the ID),
    tags them with JD:xx.xx, and leaves symlinks in the JD directory.

    \b
    Example:
        jd stage 26.05
        jd stage -n 26.05   # preview only
    """
    jd = get_root()
    target = jd.find_by_id(jd_id)
    if not target:
        click.echo(f"ID {jd_id} not found.", err=True)
        raise SystemExit(1)
    if not target.path.is_dir():
        click.echo(f"{jd_id} is a file-ID, not a directory.", err=True)
        raise SystemExit(1)

    prefix = "(dry run) " if dry_run else ""
    staged = stage_items(target.path, jd_id, DESKTOP, dry_run=dry_run)

    if not staged:
        click.echo(f"Nothing to stage in {jd_id}.")
        return
    for name in staged:
        click.echo(f"{prefix}{name} -> ~/Desktop/{jd_id} {name}")


@cli.command()
@click.argument("jd_id", type=JD_ID, required=False, default=None)
@click.option("-n", "--dry-run", is_flag=True, help="Show what would be unstaged without doing it")
def unstage(jd_id, dry_run):
    """Return staged items from Desktop to their JD directories.

    Scans ~/Desktop for JD-tagged items and moves them back.
    Optionally filter by a specific ID.

    \b
    Example:
        jd unstage          # unstage everything
        jd unstage 26.05    # unstage only 26.05 items
        jd unstage -n       # preview only
    """
    jd = get_root()

    def find_id_dir(id_str):
        obj = jd.find_by_id(id_str)
        return obj.path if obj else None

    prefix = "(dry run) " if dry_run else ""
    result = unstage_items(DESKTOP, find_id_dir, filter_id=jd_id, dry_run=dry_run)

    if not result:
        click.echo("Nothing to unstage.")
        return
    for entry in result:
        click.echo(f"{prefix}{entry['name']} -> {entry['dest']}")
```

**Step 4: Run tests**

Run: `pytest tests/test_staging.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add johnnydecimal/cli.py tests/test_staging.py
git commit -m "Add jd stage and jd unstage CLI commands"
```

---

### Task 5: MCP tools

**Files:**
- Modify: `johnnydecimal/mcp_server.py`
- Modify: `tests/test_staging.py`

**Step 1: Write failing tests**

```python
class TestStageMcp:
    def test_jd_stage_tool(self, tmp_jd_root, monkeypatch):
        from johnnydecimal import mcp_server
        monkeypatch.setattr(mcp_server, "_get_root", lambda: JDSystem(tmp_jd_root))
        sourdough = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"
        (sourdough / "recipe.txt").write_text("flour")
        desktop = tmp_jd_root / "Desktop"
        desktop.mkdir()
        monkeypatch.setattr(mcp_server, "DESKTOP", desktop)

        with patch("johnnydecimal.staging.add_jd_tag"):
            result = mcp_server.jd_stage("26.05")

        assert result["error"] is None
        assert "recipe.txt" in result["staged"]

    def test_jd_unstage_tool(self, tmp_jd_root, monkeypatch):
        from johnnydecimal import mcp_server
        from johnnydecimal.models import JDSystem
        monkeypatch.setattr(mcp_server, "_get_root", lambda: JDSystem(tmp_jd_root))
        desktop = tmp_jd_root / "Desktop"
        desktop.mkdir()
        monkeypatch.setattr(mcp_server, "DESKTOP", desktop)

        with patch("johnnydecimal.staging.get_jd_tags", return_value=[]), \
             patch("johnnydecimal.staging.remove_jd_tag"):
            result = mcp_server.jd_unstage()

        assert result["error"] is None
        assert result["unstaged"] == []
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_staging.py::TestStageMcp -v`
Expected: FAIL — no `jd_stage` function

**Step 3: Implement MCP tools**

Add to `johnnydecimal/mcp_server.py`:

```python
from johnnydecimal.staging import stage_items, unstage_items, add_jd_tag, remove_jd_tag

DESKTOP = Path.home() / "Desktop"


@mcp.tool()
def jd_stage(jd_id: str) -> dict:
    """Stage a JD ID's contents to the Desktop.

    Moves all top-level items to ~/Desktop (prefixed with the ID),
    tags them with JD:xx.xx, and leaves symlinks in the JD directory.
    """
    jd = _get_root()
    target = jd.find_by_id(jd_id)
    if not target:
        return {"error": f"ID {jd_id} not found"}
    if not target.path.is_dir():
        return {"error": f"{jd_id} is a file-ID, not a directory"}

    staged = stage_items(target.path, jd_id, DESKTOP)
    return {"error": None, "jd_id": jd_id, "staged": staged}


@mcp.tool()
def jd_unstage(jd_id: str | None = None) -> dict:
    """Return staged items from Desktop to their JD directories.

    Scans ~/Desktop for JD-tagged items and moves them back.
    Optionally filter by a specific JD ID.
    """
    jd = _get_root()

    def find_id_dir(id_str):
        obj = jd.find_by_id(id_str)
        return obj.path if obj else None

    result = unstage_items(DESKTOP, find_id_dir, filter_id=jd_id)
    return {"error": None, "unstaged": result}


@mcp.tool()
def jd_tag_add(jd_id: str, path: str) -> dict:
    """Add a JD Finder tag to a file or directory without moving it."""
    jd = _get_root()
    target = jd.find_by_id(jd_id)
    if not target:
        return {"error": f"ID {jd_id} not found"}
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return {"error": f"Path not found: {path}"}
    add_jd_tag(p, jd_id)
    return {"error": None, "tagged": str(p), "tag": f"JD:{jd_id}"}


@mcp.tool()
def jd_tag_remove(path: str, jd_id: str | None = None) -> dict:
    """Remove JD Finder tag(s) from a file or directory."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return {"error": f"Path not found: {path}"}
    remove_jd_tag(p, jd_id)
    return {"error": None, "path": str(p), "removed": f"JD:{jd_id}" if jd_id else "all JD tags"}
```

**Step 4: Run tests**

Run: `pytest tests/test_staging.py -v`
Expected: All pass

**Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add johnnydecimal/mcp_server.py tests/test_staging.py
git commit -m "Add MCP tools for stage, unstage, tag add/remove"
```

---

### Task 6: Integration test — full round-trip

**Files:**
- Modify: `tests/test_staging.py`

**Step 1: Write integration test**

This test exercises the full stage → unstage round-trip using the core functions (mocking only xattr).

```python
class TestStagingRoundTrip:
    def test_stage_then_unstage_restores_original_state(self, tmp_path):
        """Full round trip: stage moves files + creates symlinks, unstage reverses."""
        # Setup
        id_dir = tmp_path / "26.05 Sourdough"
        id_dir.mkdir()
        (id_dir / "recipe.txt").write_text("flour and water")
        (id_dir / "photos").mkdir()
        (id_dir / "photos" / "bread.jpg").write_text("img data")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()

        # Stage
        with patch("johnnydecimal.staging.add_jd_tag"):
            staged = stage_items(id_dir, "26.05", desktop)
        assert set(staged) == {"recipe.txt", "photos"}
        # Verify staged state
        assert (id_dir / "recipe.txt").is_symlink()
        assert (id_dir / "photos").is_symlink()
        assert (desktop / "26.05 recipe.txt").exists()
        assert (desktop / "26.05 photos" / "bread.jpg").exists()

        # Unstage
        with patch("johnnydecimal.staging.get_jd_tags", return_value=["26.05"]), \
             patch("johnnydecimal.staging.remove_jd_tag"):
            unstaged = unstage_items(desktop, find_id_dir=lambda _: id_dir)
        assert len(unstaged) == 2

        # Verify restored state
        assert (id_dir / "recipe.txt").exists()
        assert not (id_dir / "recipe.txt").is_symlink()
        assert (id_dir / "recipe.txt").read_text() == "flour and water"
        assert (id_dir / "photos").is_dir()
        assert not (id_dir / "photos").is_symlink()
        assert (id_dir / "photos" / "bread.jpg").read_text() == "img data"
        # Desktop is clean
        assert list(desktop.iterdir()) == []

    def test_manually_tagged_then_unstage(self, tmp_path):
        """Items tagged with jd tag add (no prefix, no symlink) get unstaged correctly."""
        id_dir = tmp_path / "26.05 Sourdough"
        id_dir.mkdir()
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        (desktop / "random-doc.pdf").write_text("doc content")

        with patch("johnnydecimal.staging.get_jd_tags", return_value=["26.05"]), \
             patch("johnnydecimal.staging.remove_jd_tag"):
            unstaged = unstage_items(desktop, find_id_dir=lambda _: id_dir)

        assert (id_dir / "random-doc.pdf").exists()
        assert (id_dir / "random-doc.pdf").read_text() == "doc content"
        assert not (desktop / "random-doc.pdf").exists()
```

**Step 2: Run tests**

Run: `pytest tests/test_staging.py::TestStagingRoundTrip -v`
Expected: All pass

**Step 3: Run full suite**

Run: `pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add tests/test_staging.py
git commit -m "Add staging round-trip integration tests"
```
