"""Tests for inbound link validation in jd validate (step 8b)."""

from click.testing import CliRunner

from johnnydecimal.cli import cli


def _run_validate(tmp_jd_root, monkeypatch, args=None):
    """Run `jd validate` with get_root patched to tmp_jd_root."""
    from johnnydecimal.models import JDSystem

    monkeypatch.setattr("johnnydecimal.cli.get_root", lambda: JDSystem(tmp_jd_root))
    runner = CliRunner()
    return runner.invoke(cli, ["validate"] + (args or []))


class TestMissingInboundLink:
    def test_warning_when_missing(self, tmp_jd_root, write_policy, monkeypatch):
        source = str(tmp_jd_root / "ext-link")
        write_policy({"links": {"26.05": [source]}})
        result = _run_validate(tmp_jd_root, monkeypatch)
        assert "MISSING" in result.output
        assert source in result.output

    def test_fix_creates_symlink(self, tmp_jd_root, write_policy, monkeypatch):
        source = tmp_jd_root / "ext-link"
        write_policy({"links": {"26.05": [str(source)]}})
        result = _run_validate(tmp_jd_root, monkeypatch, ["--fix"])
        assert "Created inbound symlink" in result.output
        assert source.is_symlink()
        target = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"
        assert source.resolve() == target.resolve()


class TestWrongTargetInboundLink:
    def test_issue_when_wrong_target(self, tmp_jd_root, write_policy, monkeypatch):
        source = tmp_jd_root / "ext-link"
        wrong_target = tmp_jd_root / "somewhere-else"
        wrong_target.mkdir()
        source.symlink_to(wrong_target)
        write_policy({"links": {"26.05": [str(source)]}})
        result = _run_validate(tmp_jd_root, monkeypatch)
        assert "WRONG TARGET" in result.output

    def test_fix_without_force_still_issue(self, tmp_jd_root, write_policy, monkeypatch):
        source = tmp_jd_root / "ext-link"
        wrong_target = tmp_jd_root / "somewhere-else"
        wrong_target.mkdir()
        source.symlink_to(wrong_target)
        write_policy({"links": {"26.05": [str(source)]}})
        result = _run_validate(tmp_jd_root, monkeypatch, ["--fix"])
        assert "WRONG TARGET" in result.output

    def test_fix_force_recreates_symlink(self, tmp_jd_root, write_policy, monkeypatch):
        source = tmp_jd_root / "ext-link"
        wrong_target = tmp_jd_root / "somewhere-else"
        wrong_target.mkdir()
        source.symlink_to(wrong_target)
        write_policy({"links": {"26.05": [str(source)]}})
        result = _run_validate(tmp_jd_root, monkeypatch, ["--fix", "--force"])
        assert "Recreated inbound symlink" in result.output
        target = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"
        assert source.resolve() == target.resolve()

    def test_fix_force_dry_run(self, tmp_jd_root, write_policy, monkeypatch):
        source = tmp_jd_root / "ext-link"
        wrong_target = tmp_jd_root / "somewhere-else"
        wrong_target.mkdir()
        source.symlink_to(wrong_target)
        write_policy({"links": {"26.05": [str(source)]}})
        result = _run_validate(tmp_jd_root, monkeypatch, ["--fix", "--force", "--dry-run"])
        assert "WOULD FIX" in result.output
        assert "Recreated inbound symlink" in result.output
        # Dry run: symlink should still point to wrong target
        assert source.resolve() == wrong_target.resolve()


class TestNotASymlinkInboundLink:
    def test_real_file_is_issue(self, tmp_jd_root, write_policy, monkeypatch):
        source = tmp_jd_root / "ext-link"
        source.write_text("real file")
        write_policy({"links": {"26.05": [str(source)]}})
        result = _run_validate(tmp_jd_root, monkeypatch)
        assert "NOT A SYMLINK" in result.output


class TestIdNotFound:
    def test_warning_when_id_missing(self, tmp_jd_root, write_policy, monkeypatch):
        source = str(tmp_jd_root / "ext-link")
        write_policy({"links": {"99.99": [source]}})
        result = _run_validate(tmp_jd_root, monkeypatch)
        assert "not found" in result.output
