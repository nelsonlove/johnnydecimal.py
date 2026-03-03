"""Tests for johnnydecimal.notes — Apple Notes JXA backend.

All osascript calls are mocked — no Apple Notes access needed.
"""

import json
import subprocess

import pytest

from johnnydecimal.notes import (
    NotesError,
    _run_jxa,
    _run_jxa_json,
    _folder_chain_js,
    list_folders,
    list_notes,
    folder_exists,
    note_exists,
    create_folder,
    create_note,
    open_note,
    build_tree,
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
        with pytest.raises(NotesError, match="error msg"):
            _run_jxa("script")

    def test_failure_no_stderr(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 42, stdout="", stderr=""),
        )
        with pytest.raises(NotesError, match="exited 42"):
            _run_jxa("script")


class TestRunJxaJson:
    def test_parses_json(self, monkeypatch):
        data = [{"name": "test"}]
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
        with pytest.raises(NotesError, match="Bad JSON"):
            _run_jxa_json("script")


class TestFolderChainJs:
    def test_single_segment(self):
        result = _folder_chain_js(["20-29 Projects"])
        assert result == 'app.accounts.byName("iCloud").folders.byName("20-29 Projects")'

    def test_nested(self):
        result = _folder_chain_js(["20-29 Projects", "26 Recipes"])
        assert 'folders.byName("20-29 Projects").folders.byName("26 Recipes")' in result

    def test_custom_account(self):
        result = _folder_chain_js(["Folder"], account="Work")
        assert 'accounts.byName("Work")' in result

    def test_escapes_quotes(self):
        result = _folder_chain_js(['He said "hi"'])
        assert r'\"hi\"' in result


class TestListFolders:
    def test_returns_folder_list(self, monkeypatch):
        folders = [{"name": "Test", "id": "x1", "parent_name": None, "parent_id": None}]
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout=json.dumps(folders), stderr=""),
        )
        result = list_folders()
        assert result == folders


class TestListNotes:
    def test_returns_note_list(self, monkeypatch):
        notes = [{"name": "26.05 Sourdough", "id": "n1",
                  "creation_date": "2024-01-01T00:00:00Z",
                  "modification_date": "2024-06-01T00:00:00Z"}]
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout=json.dumps(notes), stderr=""),
        )
        result = list_notes(["20-29 Projects", "26 Recipes"])
        assert len(result) == 1
        assert result[0]["name"] == "26.05 Sourdough"


class TestFolderExists:
    def test_exists(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout="true", stderr=""),
        )
        assert folder_exists(["20-29 Projects"]) is True

    def test_not_exists(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout="false", stderr=""),
        )
        assert folder_exists(["Nonexistent"]) is False


class TestNoteExists:
    def test_exists(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout="true", stderr=""),
        )
        assert note_exists(["20-29 Projects", "26 Recipes"], "26.05 Sourdough") is True

    def test_not_exists(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout="false", stderr=""),
        )
        assert note_exists(["20-29 Projects", "26 Recipes"], "99.99 Nope") is False


class TestCreateFolder:
    def test_creates_missing_folders(self, monkeypatch):
        calls = []

        def mock_run(*args, **kwargs):
            cmd = args[0]
            script = cmd[4]  # -e argument
            calls.append(script)
            # folder_exists checks return false, then creation succeeds
            if "f.name()" in script:
                return subprocess.CompletedProcess(cmd, 0, stdout="false", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        create_folder(["20-29 Projects", "26 Recipes"])
        # Should have checked existence of each segment, then created each
        assert len(calls) >= 2  # At minimum: check + create for each segment

    def test_skips_existing(self, monkeypatch):
        calls = []

        def mock_run(*args, **kwargs):
            cmd = args[0]
            script = cmd[4]
            calls.append("check" if "f.name()" in script else "create")
            if "f.name()" in script:
                return subprocess.CompletedProcess(cmd, 0, stdout="true", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        create_folder(["20-29 Projects"])
        # Should only check, never create
        assert "create" not in calls


class TestCreateNote:
    def test_creates_note(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (called.append(a[0][4]), subprocess.CompletedProcess(a[0], 0, stdout="", stderr=""))[1],
        )
        create_note(["20-29 Projects", "26 Recipes"], "26.05 Sourdough")
        assert len(called) == 1
        assert "26.05 Sourdough" in called[0]


class TestOpenNote:
    def test_opens_note(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (called.append(a[0][4]), subprocess.CompletedProcess(a[0], 0, stdout="", stderr=""))[1],
        )
        open_note(["20-29 Projects", "26 Recipes"], "26.05 Sourdough")
        assert len(called) == 1
        assert "app.activate()" in called[0]
        assert "26.05 Sourdough" in called[0]


class TestBuildTree:
    def test_returns_nested_dict(self, monkeypatch):
        tree = {
            "20-29 Projects": {
                "folders": {
                    "26 Recipes": {
                        "folders": {},
                        "notes": ["26.05 Sourdough"],
                    }
                },
                "notes": [],
            }
        }
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout=json.dumps(tree), stderr=""),
        )
        result = build_tree()
        assert "20-29 Projects" in result
        assert "26 Recipes" in result["20-29 Projects"]["folders"]
