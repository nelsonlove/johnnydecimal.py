"""Tests for the jd ln command."""

import yaml
from click.testing import CliRunner

from johnnydecimal.cli import cli


def _run_ln(tmp_jd_root, monkeypatch, args):
    """Run `jd ln` with get_root patched to tmp_jd_root."""
    from johnnydecimal.models import JDSystem

    monkeypatch.setattr("johnnydecimal.cli.get_root", lambda: JDSystem(tmp_jd_root))
    runner = CliRunner()
    return runner.invoke(cli, ["ln"] + args)


class TestLnCreate:
    def test_creates_symlink_and_updates_policy(self, tmp_jd_root, policy_path, monkeypatch):
        source = str(tmp_jd_root / "ext-link")
        result = _run_ln(tmp_jd_root, monkeypatch, [source, "26.05"])
        assert result.exit_code == 0
        assert "Created symlink" in result.output

        # Symlink exists and points to correct target
        link = tmp_jd_root / "ext-link"
        assert link.is_symlink()
        target = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"
        assert link.resolve() == target.resolve()

        # Policy updated
        with open(policy_path) as f:
            data = yaml.safe_load(f) or {}
        assert source in data["links"]["26.05"]

    def test_idempotent_when_already_correct(self, tmp_jd_root, monkeypatch):
        source = tmp_jd_root / "ext-link"
        target = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"
        source.symlink_to(target)
        result = _run_ln(tmp_jd_root, monkeypatch, [str(source), "26.05"])
        assert result.exit_code == 0
        assert "already correct" in result.output


class TestLnErrors:
    def test_error_when_source_is_real_file(self, tmp_jd_root, monkeypatch):
        source = tmp_jd_root / "ext-link"
        source.write_text("real file")
        result = _run_ln(tmp_jd_root, monkeypatch, [str(source), "26.05"])
        assert result.exit_code != 0
        assert "not a symlink" in result.output

    def test_error_when_symlink_wrong_target(self, tmp_jd_root, monkeypatch):
        source = tmp_jd_root / "ext-link"
        wrong = tmp_jd_root / "somewhere-else"
        wrong.mkdir()
        source.symlink_to(wrong)
        result = _run_ln(tmp_jd_root, monkeypatch, [str(source), "26.05"])
        assert result.exit_code != 0
        assert "points to" in result.output

    def test_error_when_id_not_found(self, tmp_jd_root, monkeypatch):
        source = str(tmp_jd_root / "ext-link")
        result = _run_ln(tmp_jd_root, monkeypatch, [source, "99.99"])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestLnRemove:
    def test_removes_symlink_and_cleans_policy(self, tmp_jd_root, policy_path, write_policy, monkeypatch):
        source = tmp_jd_root / "ext-link"
        target = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"
        source.symlink_to(target)
        write_policy({"links": {"26.05": [str(source)]}})

        result = _run_ln(tmp_jd_root, monkeypatch, ["--remove", str(source), "26.05"])
        assert result.exit_code == 0
        assert "Removed symlink" in result.output
        assert not source.exists()

        with open(policy_path) as f:
            data = yaml.safe_load(f) or {}
        assert "links" not in data or "26.05" not in data.get("links", {})
