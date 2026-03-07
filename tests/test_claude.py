"""Tests for jd claude — cascading context and CLI command."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from johnnydecimal.claude import (
    get_cascade_levels,
    collect_files_at_level,
    build_context,
    format_context,
)
from johnnydecimal.cli import cli


def _run(tmp_jd_root, monkeypatch, args):
    from johnnydecimal.models import JDSystem

    monkeypatch.setattr("johnnydecimal.cli.get_root", lambda: JDSystem(tmp_jd_root))
    runner = CliRunner()
    return runner.invoke(cli, args)


# ---------------------------------------------------------------------------
# TestCascadeLevels
# ---------------------------------------------------------------------------


class TestCascadeLevels:
    def test_id_cascade(self, tmp_jd_root):
        """ID path returns [root, area, category, id]."""
        id_path = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"
        levels = get_cascade_levels(id_path, tmp_jd_root)
        assert len(levels) == 4
        assert levels[0] == tmp_jd_root
        assert "20-29" in levels[1].name
        assert "26" in levels[2].name
        assert "26.05" in levels[3].name

    def test_category_cascade(self, tmp_jd_root):
        """Category path returns [root, area, category]."""
        cat_path = tmp_jd_root / "20-29 Projects" / "26 Recipes"
        levels = get_cascade_levels(cat_path, tmp_jd_root)
        assert len(levels) == 3
        assert levels[0] == tmp_jd_root
        assert "20-29" in levels[1].name
        assert "26" in levels[2].name

    def test_root_cascade(self, tmp_jd_root):
        """Root returns just [root]."""
        levels = get_cascade_levels(tmp_jd_root, tmp_jd_root)
        assert len(levels) == 1
        assert levels[0] == tmp_jd_root


# ---------------------------------------------------------------------------
# TestCollectFiles
# ---------------------------------------------------------------------------


class TestCollectFiles:
    def test_collects_readme(self, tmp_jd_root):
        """README.md in a meta dir is collected."""
        meta = tmp_jd_root / "00-09 Meta" / "00 Indices" / "00.00 Meta"
        readme = meta / "README.md"
        readme.write_text("root readme")
        found = collect_files_at_level(meta, ["README"], [".md"], [], [])
        assert readme in found

    def test_exclude_skips_file(self, tmp_jd_root):
        """Excluded files are not collected."""
        meta = tmp_jd_root / "00-09 Meta" / "00 Indices" / "00.00 Meta"
        readme = meta / "README.md"
        todo = meta / "TODO.md"
        readme.write_text("readme")
        todo.write_text("todo")
        found = collect_files_at_level(meta, ["README", "TODO"], [".md"], [], ["TODO.md"])
        assert readme in found
        assert todo not in found

    def test_extra_globs(self, tmp_jd_root):
        """Extra globs find additional files."""
        meta = tmp_jd_root / "00-09 Meta" / "00 Indices" / "00.00 Meta"
        notes = meta / "NOTES.md"
        notes.write_text("notes")
        found = collect_files_at_level(meta, [], [], ["*.md"], [])
        assert notes in found


# ---------------------------------------------------------------------------
# TestBuildContext
# ---------------------------------------------------------------------------


class TestBuildContext:
    def test_stem_ordering(self, tmp_jd_root):
        """READMEs come before TODOs across all levels (stem > extension > level)."""
        root_meta = tmp_jd_root / "00-09 Meta" / "00 Indices" / "00.00 Meta"
        cat_meta = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.00 Recipes - Meta"
        id_dir = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"

        (root_meta / "README.md").write_text("root readme")
        (root_meta / "TODO.md").write_text("root todo")
        (cat_meta / "README.md").write_text("cat readme")
        (cat_meta / "TODO.md").write_text("cat todo")

        files = build_context(id_dir, tmp_jd_root, stems=["README", "TODO"], extensions=[".md"])
        names = [Path(rel).name for _, rel in files]

        # All READMEs before all TODOs
        readme_indices = [i for i, n in enumerate(names) if n == "README.md"]
        todo_indices = [i for i, n in enumerate(names) if n == "TODO.md"]
        assert readme_indices, "Expected README.md files"
        assert todo_indices, "Expected TODO.md files"
        assert max(readme_indices) < min(todo_indices)


# ---------------------------------------------------------------------------
# TestFormatContext
# ---------------------------------------------------------------------------


class TestFormatContext:
    def test_format_with_headers(self, tmp_jd_root):
        """Formatted output contains headers and file content."""
        root_meta = tmp_jd_root / "00-09 Meta" / "00 Indices" / "00.00 Meta"
        readme = root_meta / "README.md"
        readme.write_text("Hello from root")

        files = build_context(tmp_jd_root, tmp_jd_root, stems=["README"], extensions=[".md"])
        output = format_context(files)
        assert "# " in output
        assert "Hello from root" in output


# ---------------------------------------------------------------------------
# TestClaudeCli
# ---------------------------------------------------------------------------


class TestClaudeCli:
    def test_show_prints_context(self, tmp_jd_root, monkeypatch):
        """--show prints collected context to stdout."""
        root_meta = tmp_jd_root / "00-09 Meta" / "00 Indices" / "00.00 Meta"
        (root_meta / "README.md").write_text("show me this")
        monkeypatch.chdir(tmp_jd_root)
        result = _run(tmp_jd_root, monkeypatch, ["claude", "--show"])
        assert "show me this" in result.output

    def test_show_no_files(self, tmp_jd_root, monkeypatch):
        """--show with no context files prints message."""
        monkeypatch.chdir(tmp_jd_root)
        result = _run(tmp_jd_root, monkeypatch, ["claude", "--show"])
        assert "No context files found" in result.output

    def test_target_not_found(self, tmp_jd_root, monkeypatch):
        """Nonexistent target yields nonzero exit."""
        result = _run(tmp_jd_root, monkeypatch, ["claude", "99.99"])
        assert result.exit_code != 0

    @patch("johnnydecimal.claude.subprocess.run")
    @patch("johnnydecimal.claude.shutil.which", return_value="/usr/bin/claude")
    def test_launch_passes_working_dir(
        self, mock_which, mock_run, tmp_jd_root, monkeypatch
    ):
        """subprocess.run is called with cwd pointing to the target dir."""
        mock_run.return_value.returncode = 0
        monkeypatch.setattr("johnnydecimal.cli.shutil.which", lambda x: "/usr/bin/claude")
        result = _run(tmp_jd_root, monkeypatch, ["claude", "26.05"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        cwd = call_kwargs.kwargs.get("cwd") or call_kwargs[1].get("cwd")
        assert "26.05" in str(cwd)
