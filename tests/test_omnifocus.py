"""Tests for johnnydecimal.omnifocus — OmniFocus JXA backend.

All osascript calls are mocked — no OmniFocus access needed.
"""

import json
import subprocess

import pytest

from johnnydecimal.omnifocus import (
    OmniFocusError,
    _run_jxa,
    _run_jxa_json,
    list_jd_tags,
    list_projects_with_jd_tags,
    list_folders,
    find_project,
    create_tag,
    create_project,
    open_project,
    tag_project,
)


class TestRunJxa:
    def test_success(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout="hello\n", stderr=""),
        )
        assert _run_jxa("script") == "hello"

    def test_failure_raises(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 1, stdout="", stderr="error msg"),
        )
        with pytest.raises(OmniFocusError, match="error msg"):
            _run_jxa("script")

    def test_failure_no_stderr(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 42, stdout="", stderr=""),
        )
        with pytest.raises(OmniFocusError, match="exited 42"):
            _run_jxa("script")


class TestRunJxaJson:
    def test_parses_json(self, monkeypatch):
        data = [{"name": "JD:26.05"}]
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout=json.dumps(data), stderr=""),
        )
        assert _run_jxa_json("script") == data

    def test_empty_returns_list(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout="", stderr=""),
        )
        assert _run_jxa_json("script") == []

    def test_bad_json_raises(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout="not json", stderr=""),
        )
        with pytest.raises(OmniFocusError, match="Bad JSON"):
            _run_jxa_json("script")


class TestListJdTags:
    def test_returns_tags(self, monkeypatch):
        tags = [
            {"name": "JD:26.05", "id": "abc", "remaining_tasks": 3},
            {"name": "JD:11", "id": "def", "remaining_tasks": 0},
        ]
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout=json.dumps(tags), stderr=""),
        )
        result = list_jd_tags()
        assert len(result) == 2
        assert result[0]["name"] == "JD:26.05"


class TestListProjectsWithJdTags:
    def test_returns_projects(self, monkeypatch):
        projects = [
            {
                "name": "Sourdough starter",
                "id": "proj1",
                "status": "Active",
                "tags": ["JD:26.05", "Home"],
                "folder": "Projects",
                "task_count": 5,
            }
        ]
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout=json.dumps(projects), stderr=""),
        )
        result = list_projects_with_jd_tags()
        assert len(result) == 1
        assert result[0]["name"] == "Sourdough starter"
        assert "JD:26.05" in result[0]["tags"]


class TestListFolders:
    def test_returns_folders(self, monkeypatch):
        folders = [
            {"name": "Projects", "id": "f1", "parent_name": None},
            {"name": "Recipes", "id": "f2", "parent_name": "Projects"},
        ]
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout=json.dumps(folders), stderr=""),
        )
        result = list_folders()
        assert len(result) == 2
        assert result[1]["parent_name"] == "Projects"


class TestFindProject:
    def test_found(self, monkeypatch):
        proj = {
            "name": "Sourdough starter",
            "id": "proj1",
            "status": "Active",
            "tags": ["JD:26.05"],
            "folder": "Recipes",
            "task_count": 3,
        }
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout=json.dumps(proj), stderr=""),
        )
        result = find_project("Sourdough starter")
        assert result["name"] == "Sourdough starter"

    def test_not_found(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout="null", stderr=""),
        )
        assert find_project("Nonexistent") is None


class TestCreateTag:
    def test_creates_tag(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (called.append(a[0][4]), subprocess.CompletedProcess(a[0], 0, stdout="ok", stderr=""))[1],
        )
        create_tag("JD:26.05")
        assert len(called) == 1
        assert "JD:26.05" in called[0]

    def test_error_raises(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 1, stdout="", stderr="failed"),
        )
        with pytest.raises(OmniFocusError, match="failed"):
            create_tag("JD:26.05")


class TestCreateProject:
    def test_creates_project(self, monkeypatch):
        result_data = {"name": "26.05 Sourdough", "id": "new1"}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(
                a[0], 0, stdout=json.dumps(result_data), stderr=""
            ),
        )
        result = create_project("26.05 Sourdough", folder="Recipes", tags=["JD:26.05"])
        assert result["name"] == "26.05 Sourdough"

    def test_creates_without_folder(self, monkeypatch):
        result_data = {"name": "26.05 Sourdough", "id": "new1"}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(
                a[0], 0, stdout=json.dumps(result_data), stderr=""
            ),
        )
        result = create_project("26.05 Sourdough")
        assert result["name"] == "26.05 Sourdough"


class TestOpenProject:
    def test_opens_project(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (called.append(a[0][4]), subprocess.CompletedProcess(a[0], 0, stdout="", stderr=""))[1],
        )
        open_project("Sourdough starter")
        assert len(called) == 1
        assert "app.activate()" in called[0]
        assert "Sourdough starter" in called[0]


class TestTagProject:
    def test_tags_project(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (called.append(a[0][4]), subprocess.CompletedProcess(a[0], 0, stdout="ok", stderr=""))[1],
        )
        tag_project("Sourdough starter", "JD:26.05")
        assert len(called) == 1
        assert "Sourdough starter" in called[0]
        assert "JD:26.05" in called[0]

    def test_error_on_missing_project(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 1, stdout="", stderr="Project not found"),
        )
        with pytest.raises(OmniFocusError, match="Project not found"):
            tag_project("Nonexistent", "JD:26.05")
