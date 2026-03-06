"""Tests for johnnydecimal.staging — Finder tag helpers."""

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from johnnydecimal.cli import cli
from johnnydecimal.staging import (
    _strip_id_prefix,
    add_jd_tag,
    get_jd_tags,
    remove_jd_tag,
    stage_items,
    unstage_items,
)

STAGING = "johnnydecimal.staging"


def _run(tmp_jd_root, monkeypatch, args):
    from johnnydecimal.models import JDSystem
    monkeypatch.setattr("johnnydecimal.cli.get_root", lambda: JDSystem(tmp_jd_root))
    runner = CliRunner()
    return runner.invoke(cli, args)


class TestGetJdTags:
    """get_jd_tags returns JD ID strings filtered from Finder tags."""

    @patch(f"{STAGING}._read_finder_tags")
    def test_returns_jd_ids(self, mock_read):
        mock_read.return_value = ["JD:26.05", "Red", "JD:11.03"]
        assert get_jd_tags(Path("/tmp/x")) == ["26.05", "11.03"]

    @patch(f"{STAGING}._read_finder_tags")
    def test_empty_when_no_tags(self, mock_read):
        mock_read.return_value = []
        assert get_jd_tags(Path("/tmp/x")) == []

    @patch(f"{STAGING}._read_finder_tags")
    def test_empty_when_no_jd_tags(self, mock_read):
        mock_read.return_value = ["Red", "Blue", "Important"]
        assert get_jd_tags(Path("/tmp/x")) == []


class TestAddJdTag:
    """add_jd_tag appends a JD tag or skips if already present."""

    @patch(f"{STAGING}._write_finder_tags")
    @patch(f"{STAGING}._read_finder_tags")
    def test_adds_when_none_exist(self, mock_read, mock_write):
        mock_read.return_value = []
        add_jd_tag(Path("/tmp/x"), "26.05")
        mock_write.assert_called_once_with(Path("/tmp/x"), ["JD:26.05"])

    @patch(f"{STAGING}._write_finder_tags")
    @patch(f"{STAGING}._read_finder_tags")
    def test_preserves_existing(self, mock_read, mock_write):
        mock_read.return_value = ["Red", "JD:11.03"]
        add_jd_tag(Path("/tmp/x"), "26.05")
        mock_write.assert_called_once_with(
            Path("/tmp/x"), ["Red", "JD:11.03", "JD:26.05"]
        )

    @patch(f"{STAGING}._write_finder_tags")
    @patch(f"{STAGING}._read_finder_tags")
    def test_skips_if_already_tagged(self, mock_read, mock_write):
        mock_read.return_value = ["JD:26.05"]
        add_jd_tag(Path("/tmp/x"), "26.05")
        mock_write.assert_not_called()


class TestRemoveJdTag:
    """remove_jd_tag removes specific or all JD tags."""

    @patch(f"{STAGING}._write_finder_tags")
    @patch(f"{STAGING}._read_finder_tags")
    def test_removes_specific_tag(self, mock_read, mock_write):
        mock_read.return_value = ["Red", "JD:26.05", "JD:11.03"]
        remove_jd_tag(Path("/tmp/x"), "26.05")
        mock_write.assert_called_once_with(
            Path("/tmp/x"), ["Red", "JD:11.03"]
        )

    @patch(f"{STAGING}._write_finder_tags")
    @patch(f"{STAGING}._read_finder_tags")
    def test_removes_all_jd_tags(self, mock_read, mock_write):
        mock_read.return_value = ["Red", "JD:26.05", "JD:11.03"]
        remove_jd_tag(Path("/tmp/x"))
        mock_write.assert_called_once_with(Path("/tmp/x"), ["Red"])

    @patch(f"{STAGING}._write_finder_tags")
    @patch(f"{STAGING}._read_finder_tags")
    def test_noop_when_tag_not_present(self, mock_read, mock_write):
        mock_read.return_value = ["Red", "JD:11.03"]
        remove_jd_tag(Path("/tmp/x"), "26.05")
        mock_write.assert_not_called()


class TestStageItems:
    """stage_items moves real items to desktop with ID prefix."""

    @patch(f"{STAGING}.add_jd_tag")
    def test_stages_files_to_desktop(self, mock_add_tag, tmp_path):
        id_dir = tmp_path / "id_dir"
        id_dir.mkdir()
        (id_dir / "report.txt").write_text("hello")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()

        result = stage_items(id_dir, "26.05", desktop)

        assert result == ["report.txt"]
        # File moved to desktop with prefix
        dest = desktop / "26.05 report.txt"
        assert dest.exists()
        assert dest.read_text() == "hello"
        # Symlink left behind
        link = id_dir / "report.txt"
        assert link.is_symlink()
        assert link.resolve() == dest.resolve()
        mock_add_tag.assert_called_once_with(dest, "26.05")

    @patch(f"{STAGING}.add_jd_tag")
    def test_stages_directories(self, mock_add_tag, tmp_path):
        id_dir = tmp_path / "id_dir"
        id_dir.mkdir()
        sub = id_dir / "photos"
        sub.mkdir()
        (sub / "a.jpg").write_text("img")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()

        result = stage_items(id_dir, "11.03", desktop)

        assert result == ["photos"]
        dest = desktop / "11.03 photos"
        assert dest.is_dir()
        assert (dest / "a.jpg").read_text() == "img"
        assert (id_dir / "photos").is_symlink()

    @patch(f"{STAGING}.add_jd_tag")
    def test_skips_dotfiles(self, mock_add_tag, tmp_path):
        id_dir = tmp_path / "id_dir"
        id_dir.mkdir()
        (id_dir / ".DS_Store").write_text("x")
        (id_dir / "notes.md").write_text("y")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()

        result = stage_items(id_dir, "26.05", desktop)

        assert result == ["notes.md"]
        assert (id_dir / ".DS_Store").exists()
        assert not (id_dir / ".DS_Store").is_symlink()

    @patch(f"{STAGING}.add_jd_tag")
    def test_skips_existing_symlinks(self, mock_add_tag, tmp_path):
        id_dir = tmp_path / "id_dir"
        id_dir.mkdir()
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        # Create a pre-existing symlink (already staged)
        target = desktop / "26.05 old.txt"
        target.write_text("old")
        (id_dir / "old.txt").symlink_to(target)
        # And a real file
        (id_dir / "new.txt").write_text("new")

        result = stage_items(id_dir, "26.05", desktop)

        assert result == ["new.txt"]

    @patch(f"{STAGING}.add_jd_tag")
    def test_dry_run_does_not_move(self, mock_add_tag, tmp_path):
        id_dir = tmp_path / "id_dir"
        id_dir.mkdir()
        (id_dir / "report.txt").write_text("hello")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()

        result = stage_items(id_dir, "26.05", desktop, dry_run=True)

        assert result == ["report.txt"]
        # File still in original location
        assert (id_dir / "report.txt").exists()
        assert not (id_dir / "report.txt").is_symlink()
        assert not (desktop / "26.05 report.txt").exists()
        mock_add_tag.assert_not_called()


class TestUnstageItems:
    """unstage_items moves tagged items from desktop back to ID dirs."""

    @patch(f"{STAGING}.remove_jd_tag")
    @patch(f"{STAGING}.get_jd_tags")
    def test_unstages_tagged_items(self, mock_get_tags, mock_remove_tag, tmp_path):
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        id_dir = tmp_path / "id_dir"
        id_dir.mkdir()

        # Simulate staged file: desktop has prefixed file, id_dir has symlink
        staged = desktop / "26.05 report.txt"
        staged.write_text("hello")
        link = id_dir / "report.txt"
        link.symlink_to(staged)

        mock_get_tags.return_value = ["26.05"]

        result = unstage_items(desktop, lambda jd_id: id_dir if jd_id == "26.05" else None)

        assert len(result) == 1
        assert result[0]["name"] == "26.05 report.txt"
        assert result[0]["jd_id"] == "26.05"
        assert result[0]["dest"] == str(id_dir / "report.txt")
        # File moved back, symlink gone
        assert (id_dir / "report.txt").exists()
        assert not (id_dir / "report.txt").is_symlink()
        assert (id_dir / "report.txt").read_text() == "hello"
        assert not staged.exists()
        mock_remove_tag.assert_called_once_with(id_dir / "report.txt", "26.05")

    @patch(f"{STAGING}.remove_jd_tag")
    @patch(f"{STAGING}.get_jd_tags")
    def test_unstages_manually_tagged_items(self, mock_get_tags, mock_remove_tag, tmp_path):
        """Item tagged manually on desktop — no symlink, no prefix."""
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        id_dir = tmp_path / "id_dir"
        id_dir.mkdir()

        manual = desktop / "budget.xlsx"
        manual.write_text("data")

        mock_get_tags.return_value = ["26.05"]

        result = unstage_items(desktop, lambda jd_id: id_dir if jd_id == "26.05" else None)

        assert len(result) == 1
        assert result[0]["dest"] == str(id_dir / "budget.xlsx")
        assert (id_dir / "budget.xlsx").exists()
        assert (id_dir / "budget.xlsx").read_text() == "data"

    @patch(f"{STAGING}.remove_jd_tag")
    @patch(f"{STAGING}.get_jd_tags")
    def test_filters_by_id(self, mock_get_tags, mock_remove_tag, tmp_path):
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        id_dir_a = tmp_path / "id_dir_a"
        id_dir_a.mkdir()
        id_dir_b = tmp_path / "id_dir_b"
        id_dir_b.mkdir()

        (desktop / "26.05 a.txt").write_text("a")
        (desktop / "11.03 b.txt").write_text("b")

        def fake_get_tags(path):
            if "26.05" in path.name:
                return ["26.05"]
            if "11.03" in path.name:
                return ["11.03"]
            return []

        mock_get_tags.side_effect = fake_get_tags

        def fake_find(jd_id):
            if jd_id == "26.05":
                return id_dir_a
            if jd_id == "11.03":
                return id_dir_b
            return None

        result = unstage_items(desktop, fake_find, filter_id="26.05")

        assert len(result) == 1
        assert result[0]["jd_id"] == "26.05"
        # Only 26.05 moved back
        assert (id_dir_a / "a.txt").exists()
        # 11.03 still on desktop
        assert (desktop / "11.03 b.txt").exists()

    @patch(f"{STAGING}.remove_jd_tag")
    @patch(f"{STAGING}.get_jd_tags")
    def test_dry_run_does_not_move(self, mock_get_tags, mock_remove_tag, tmp_path):
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        id_dir = tmp_path / "id_dir"
        id_dir.mkdir()

        staged = desktop / "26.05 report.txt"
        staged.write_text("hello")
        link = id_dir / "report.txt"
        link.symlink_to(staged)

        mock_get_tags.return_value = ["26.05"]

        result = unstage_items(
            desktop,
            lambda jd_id: id_dir if jd_id == "26.05" else None,
            dry_run=True,
        )

        assert len(result) == 1
        assert result[0]["jd_id"] == "26.05"
        # Nothing moved
        assert staged.exists()
        assert link.is_symlink()
        mock_remove_tag.assert_not_called()


class TestStageCli:
    """jd stage — CLI wrapper around stage_items."""

    @patch("johnnydecimal.cli.stage_items", return_value=["recipe.txt"])
    def test_stages_id_contents(self, mock_stage, tmp_jd_root, monkeypatch):
        monkeypatch.setattr("johnnydecimal.cli.DESKTOP", tmp_jd_root / "Desktop")
        result = _run(tmp_jd_root, monkeypatch, ["stage", "26.05"])

        assert result.exit_code == 0
        assert "recipe.txt" in result.output
        mock_stage.assert_called_once()

    def test_error_when_id_not_found(self, tmp_jd_root, monkeypatch):
        result = _run(tmp_jd_root, monkeypatch, ["stage", "99.99"])

        assert result.exit_code != 0

    @patch("johnnydecimal.cli.stage_items", return_value=["recipe.txt"])
    def test_dry_run(self, mock_stage, tmp_jd_root, monkeypatch):
        monkeypatch.setattr("johnnydecimal.cli.DESKTOP", tmp_jd_root / "Desktop")
        result = _run(tmp_jd_root, monkeypatch, ["stage", "-n", "26.05"])

        assert "dry run" in result.output
        _, kwargs = mock_stage.call_args
        assert kwargs.get("dry_run") is True


class TestUnstageCli:
    """jd unstage — CLI wrapper around unstage_items."""

    @patch("johnnydecimal.cli.unstage_items", return_value=[{"name": "26.05 recipe.txt", "jd_id": "26.05", "dest": "/tmp/id_dir/recipe.txt"}])
    def test_unstages_all(self, mock_unstage, tmp_jd_root, monkeypatch):
        monkeypatch.setattr("johnnydecimal.cli.DESKTOP", tmp_jd_root / "Desktop")
        result = _run(tmp_jd_root, monkeypatch, ["unstage"])

        assert result.exit_code == 0
        assert "recipe.txt" in result.output
        mock_unstage.assert_called_once()

    @patch("johnnydecimal.cli.unstage_items", return_value=[{"name": "26.05 recipe.txt", "jd_id": "26.05", "dest": "/tmp/id_dir/recipe.txt"}])
    def test_unstages_specific_id(self, mock_unstage, tmp_jd_root, monkeypatch):
        monkeypatch.setattr("johnnydecimal.cli.DESKTOP", tmp_jd_root / "Desktop")
        result = _run(tmp_jd_root, monkeypatch, ["unstage", "26.05"])

        assert result.exit_code == 0
        _, kwargs = mock_unstage.call_args
        assert kwargs.get("filter_id") == "26.05"


class TestTagAddCli:
    """jd tag add — CLI wrapper around add_jd_tag."""

    @patch("johnnydecimal.cli.add_jd_tag")
    def test_tags_a_file(self, mock_add, tmp_jd_root, monkeypatch):
        # Create a file inside 26.05 Sourdough
        target = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough" / "recipe.txt"
        target.write_text("flour water salt")

        result = _run(tmp_jd_root, monkeypatch, ["tag", "add", "26.05", str(target)])

        assert result.exit_code == 0
        mock_add.assert_called_once_with(Path(str(target)), "26.05")

    def test_error_when_path_missing(self, tmp_jd_root, monkeypatch):
        result = _run(tmp_jd_root, monkeypatch, ["tag", "add", "26.05", "/nonexistent/file.txt"])

        assert result.exit_code != 0

    def test_error_when_id_not_found(self, tmp_jd_root, monkeypatch):
        target = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough" / "recipe.txt"
        target.write_text("flour water salt")

        result = _run(tmp_jd_root, monkeypatch, ["tag", "add", "99.99", str(target)])

        assert result.exit_code != 0


class TestTagRemoveCli:
    """jd tag remove — CLI wrapper around remove_jd_tag."""

    @patch("johnnydecimal.cli.remove_jd_tag")
    def test_removes_tag(self, mock_remove, tmp_jd_root, monkeypatch):
        target = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough" / "recipe.txt"
        target.write_text("flour water salt")

        result = _run(tmp_jd_root, monkeypatch, ["tag", "remove", str(target)])

        assert result.exit_code == 0
        mock_remove.assert_called_once_with(Path(str(target)), None)
