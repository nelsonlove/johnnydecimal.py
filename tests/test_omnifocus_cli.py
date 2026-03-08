"""Tests for jd omnifocus CLI commands.

OmniFocus module is mocked — no OmniFocus access needed.
"""

from unittest.mock import patch

from click.testing import CliRunner

from johnnydecimal.cli import cli


def _run_omnifocus(tmp_jd_root, monkeypatch, args):
    """Run `jd omnifocus <args>` with get_root patched."""
    from johnnydecimal.models import JDSystem

    monkeypatch.setattr("johnnydecimal.cli.get_root", lambda: JDSystem(tmp_jd_root))
    runner = CliRunner()
    return runner.invoke(cli, ["omnifocus"] + args)


class TestOmniFocusScan:
    def test_tagged_found(self, tmp_jd_root, monkeypatch):
        projects = [
            {"name": "Sourdough starter", "id": "p1", "status": "Active",
             "tags": ["JD:26.05"], "folder": "Recipes", "task_count": 3},
        ]
        with patch("johnnydecimal.omnifocus.list_projects_with_jd_tags", return_value=projects), \
             patch("johnnydecimal.omnifocus.list_folders", return_value=[]):
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["scan"])
        assert "Tagged + found" in result.output
        assert "26.05" in result.output

    def test_tagged_dead(self, tmp_jd_root, monkeypatch):
        projects = [
            {"name": "Ghost project", "id": "p1", "status": "Active",
             "tags": ["JD:99.99"], "folder": None, "task_count": 0},
        ]
        with patch("johnnydecimal.omnifocus.list_projects_with_jd_tags", return_value=projects), \
             patch("johnnydecimal.omnifocus.list_folders", return_value=[]):
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["scan"])
        assert "Tagged + dead" in result.output
        assert "99.99" in result.output

    def test_no_projects(self, tmp_jd_root, monkeypatch):
        with patch("johnnydecimal.omnifocus.list_projects_with_jd_tags", return_value=[]), \
             patch("johnnydecimal.omnifocus.list_folders", return_value=[]):
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["scan"])
        assert "No OmniFocus projects with JD tags found" in result.output

    def test_omnifocus_error(self, tmp_jd_root, monkeypatch):
        from johnnydecimal.omnifocus import OmniFocusError
        with patch("johnnydecimal.omnifocus.list_projects_with_jd_tags",
                   side_effect=OmniFocusError("fail")):
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["scan"])
        assert result.exit_code == 1
        assert "Could not read OmniFocus" in result.output

    def test_disabled_by_policy(self, tmp_jd_root, write_policy, monkeypatch):
        write_policy({"omnifocus": False})
        result = _run_omnifocus(tmp_jd_root, monkeypatch, ["scan"])
        assert result.exit_code == 1
        assert "disabled" in result.output


class TestOmniFocusValidate:
    def test_consistent(self, tmp_jd_root, monkeypatch):
        projects = [
            {"name": "Sourdough starter", "id": "p1", "status": "Active",
             "tags": ["JD:26.05"], "folder": "Projects", "task_count": 3},
        ]
        folders = [{"name": "Projects", "id": "f1", "parent_name": None}]
        with patch("johnnydecimal.omnifocus.list_projects_with_jd_tags", return_value=projects), \
             patch("johnnydecimal.omnifocus.list_folders", return_value=folders), \
             patch("johnnydecimal.omnifocus._run_jxa_json", return_value=[]):
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["validate"])
        # May have warnings (untracked IDs, area mismatch) but no issues
        assert result.exit_code == 0

    def test_dead_tag_is_issue(self, tmp_jd_root, monkeypatch):
        projects = [
            {"name": "Ghost", "id": "p1", "status": "Active",
             "tags": ["JD:99.99"], "folder": None, "task_count": 0},
        ]
        with patch("johnnydecimal.omnifocus.list_projects_with_jd_tags", return_value=projects), \
             patch("johnnydecimal.omnifocus.list_folders", return_value=[]), \
             patch("johnnydecimal.omnifocus._run_jxa_json", return_value=[]):
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["validate"])
        assert result.exit_code == 1
        assert "Issues" in result.output
        assert "99.99" in result.output

    def test_omnifocus_error(self, tmp_jd_root, monkeypatch):
        from johnnydecimal.omnifocus import OmniFocusError
        with patch("johnnydecimal.omnifocus.list_projects_with_jd_tags",
                   side_effect=OmniFocusError("fail")):
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["validate"])
        assert result.exit_code == 1


class TestOmniFocusOpen:
    def test_opens_project(self, tmp_jd_root, monkeypatch):
        projects = [
            {"name": "Sourdough starter", "id": "p1", "status": "Active",
             "tags": ["JD:26.05"], "folder": "Recipes", "task_count": 3},
        ]
        with patch("johnnydecimal.omnifocus.list_projects_with_jd_tags", return_value=projects), \
             patch("johnnydecimal.omnifocus.open_project") as mock_open:
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["open", "26.05"])
        assert "Opened:" in result.output
        mock_open.assert_called_once_with("Sourdough starter")

    def test_no_matching_project(self, tmp_jd_root, monkeypatch):
        with patch("johnnydecimal.omnifocus.list_projects_with_jd_tags", return_value=[]):
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["open", "26.05"])
        assert result.exit_code == 1
        assert "No OmniFocus project matching" in result.output

    def test_multiple_matches(self, tmp_jd_root, monkeypatch):
        projects = [
            {"name": "Project A", "id": "p1", "status": "Active",
             "tags": ["JD:26.05"], "folder": "Folder A", "task_count": 1},
            {"name": "Project B", "id": "p2", "status": "Active",
             "tags": ["JD:26.05"], "folder": "Folder B", "task_count": 2},
        ]
        with patch("johnnydecimal.omnifocus.list_projects_with_jd_tags", return_value=projects):
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["open", "26.05"])
        assert "Projects matching" in result.output
        assert "Project A" in result.output
        assert "Project B" in result.output


class TestOmniFocusTag:
    def test_creates_tag(self, tmp_jd_root, monkeypatch):
        with patch("johnnydecimal.omnifocus.create_tag") as mock_create:
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["tag", "26.05"])
        assert "Created tag: JD:26.05" in result.output
        mock_create.assert_called_once_with("JD:26.05")

    def test_id_not_found(self, tmp_jd_root, monkeypatch):
        result = _run_omnifocus(tmp_jd_root, monkeypatch, ["tag", "99.99"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_omnifocus_error(self, tmp_jd_root, monkeypatch):
        from johnnydecimal.omnifocus import OmniFocusError
        with patch("johnnydecimal.omnifocus.create_tag", side_effect=OmniFocusError("fail")):
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["tag", "26.05"])
        assert result.exit_code == 1
        assert "fail" in result.output


class TestOmniFocusCreate:
    def test_creates_project(self, tmp_jd_root, monkeypatch):
        with patch("johnnydecimal.omnifocus.create_tag"), \
             patch("johnnydecimal.omnifocus.list_folders", return_value=[]), \
             patch("johnnydecimal.omnifocus.create_project", return_value={"name": "26.05 Sourdough", "id": "x"}):
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["create", "26.05"])
        assert "Created project: 26.05 Sourdough" in result.output
        assert "JD:26.05" in result.output

    def test_creates_with_folder(self, tmp_jd_root, monkeypatch):
        with patch("johnnydecimal.omnifocus.create_tag"), \
             patch("johnnydecimal.omnifocus.create_project", return_value={"name": "26.05 Sourdough", "id": "x"}):
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["create", "26.05", "--folder", "Recipes"])
        assert "Created project" in result.output
        assert "Folder: Recipes" in result.output

    def test_auto_matches_folder(self, tmp_jd_root, monkeypatch):
        folders = [{"name": "Projects", "id": "f1", "parent_name": None}]
        with patch("johnnydecimal.omnifocus.create_tag"), \
             patch("johnnydecimal.omnifocus.list_folders", return_value=folders), \
             patch("johnnydecimal.omnifocus.create_project", return_value={"name": "26.05 Sourdough", "id": "x"}) as mock_create:
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["create", "26.05"])
        # Area is "Projects" which matches OF folder "Projects"
        call_args = mock_create.call_args
        assert call_args[1].get("folder") == "Projects" or (call_args[0] and len(call_args[0]) > 1)

    def test_id_not_found(self, tmp_jd_root, monkeypatch):
        result = _run_omnifocus(tmp_jd_root, monkeypatch, ["create", "99.99"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_omnifocus_error(self, tmp_jd_root, monkeypatch):
        from johnnydecimal.omnifocus import OmniFocusError
        with patch("johnnydecimal.omnifocus.create_tag", side_effect=OmniFocusError("fail")):
            result = _run_omnifocus(tmp_jd_root, monkeypatch, ["create", "26.05"])
        assert result.exit_code == 1
        assert "fail" in result.output


class TestOmniFocusDisabledByPolicy:
    """All commands should respect omnifocus: false in root policy."""

    def test_validate_disabled(self, tmp_jd_root, write_policy, monkeypatch):
        write_policy({"omnifocus": False})
        result = _run_omnifocus(tmp_jd_root, monkeypatch, ["validate"])
        assert result.exit_code == 1
        assert "disabled" in result.output

    def test_open_disabled(self, tmp_jd_root, write_policy, monkeypatch):
        write_policy({"omnifocus": False})
        result = _run_omnifocus(tmp_jd_root, monkeypatch, ["open", "26.05"])
        assert result.exit_code == 1
        assert "disabled" in result.output

    def test_tag_disabled(self, tmp_jd_root, write_policy, monkeypatch):
        write_policy({"omnifocus": False})
        result = _run_omnifocus(tmp_jd_root, monkeypatch, ["tag", "26.05"])
        assert result.exit_code == 1
        assert "disabled" in result.output

    def test_create_disabled(self, tmp_jd_root, write_policy, monkeypatch):
        write_policy({"omnifocus": False})
        result = _run_omnifocus(tmp_jd_root, monkeypatch, ["create", "26.05"])
        assert result.exit_code == 1
        assert "disabled" in result.output
