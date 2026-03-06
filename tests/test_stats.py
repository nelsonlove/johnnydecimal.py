"""Tests for jd stats command."""

from click.testing import CliRunner

from johnnydecimal.cli import cli


def _run(tmp_jd_root, monkeypatch, args):
    from johnnydecimal.models import JDSystem
    monkeypatch.setattr("johnnydecimal.cli.get_root", lambda: JDSystem(tmp_jd_root))
    runner = CliRunner()
    return runner.invoke(cli, args)


class TestStatsCli:
    def test_smoke(self, tmp_jd_root, monkeypatch):
        """Stats runs without crashing on a minimal JD tree."""
        result = _run(tmp_jd_root, monkeypatch, ["stats"])
        assert result.exit_code == 0
        assert "Johnny Decimal" in result.output
        assert "Structure" in result.output
        assert "Areas:" in result.output
        assert "Categories:" in result.output

    def test_counts_correct(self, tmp_jd_root, monkeypatch):
        """Verify basic counts match the fixture tree."""
        result = _run(tmp_jd_root, monkeypatch, ["stats"])
        assert result.exit_code == 0
        # Fixture has 3 areas, 3 categories, 5 IDs
        assert "Areas:        3" in result.output
        assert "Categories:   3" in result.output

    def test_with_files(self, tmp_jd_root, monkeypatch):
        """Stats reports file types when files exist."""
        sourdough = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"
        (sourdough / "recipe.md").write_text("flour and water")
        (sourdough / "photo.jpg").write_bytes(b"\xff\xd8")
        result = _run(tmp_jd_root, monkeypatch, ["stats"])
        assert result.exit_code == 0
        assert "File Types" in result.output
        assert ".md" in result.output
