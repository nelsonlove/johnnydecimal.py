"""Tests for jd notes CLI commands.

Notes module is mocked — no Apple Notes access needed.
"""

import yaml
from unittest.mock import patch

from click.testing import CliRunner

from johnnydecimal.cli import cli


def _run_notes(tmp_jd_root, monkeypatch, args):
    """Run `jd notes <args>` with get_root patched."""
    from johnnydecimal.models import JDSystem

    monkeypatch.setattr("johnnydecimal.cli.get_root", lambda: JDSystem(tmp_jd_root))
    runner = CliRunner()
    return runner.invoke(cli, ["notes"] + args)


class TestNotesScan:
    def test_no_declarations(self, tmp_jd_root, monkeypatch):
        result = _run_notes(tmp_jd_root, monkeypatch, ["scan"])
        assert "No notes declarations" in result.output

    def test_declared_found(self, tmp_jd_root, write_policy, monkeypatch):
        write_policy({"notes": {"26": ["26.05"]}})
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
        with patch("johnnydecimal.notes.build_tree", return_value=tree):
            result = _run_notes(tmp_jd_root, monkeypatch, ["scan"])
        assert "Declared + found" in result.output
        assert "26.05" in result.output

    def test_declared_missing(self, tmp_jd_root, write_policy, monkeypatch):
        write_policy({"notes": {"26": ["26.05"]}})
        tree = {
            "20-29 Projects": {
                "folders": {
                    "26 Recipes": {
                        "folders": {},
                        "notes": [],
                    }
                },
                "notes": [],
            }
        }
        with patch("johnnydecimal.notes.build_tree", return_value=tree):
            result = _run_notes(tmp_jd_root, monkeypatch, ["scan"])
        assert "Declared + missing" in result.output
        assert "26.05" in result.output

    def test_undeclared_match(self, tmp_jd_root, write_policy, monkeypatch):
        write_policy({"notes": {"26": ["26.05"]}})
        tree = {
            "20-29 Projects": {
                "folders": {
                    "26 Recipes": {
                        "folders": {},
                        "notes": ["26.05 Sourdough", "26.12 Bread"],
                    }
                },
                "notes": [],
            }
        }
        with patch("johnnydecimal.notes.build_tree", return_value=tree):
            result = _run_notes(tmp_jd_root, monkeypatch, ["scan"])
        assert "Undeclared matches" in result.output
        assert "26.12" in result.output

    def test_notes_error(self, tmp_jd_root, write_policy, monkeypatch):
        from johnnydecimal.notes import NotesError
        write_policy({"notes": {"26": ["26.05"]}})
        with patch("johnnydecimal.notes.build_tree", side_effect=NotesError("fail")):
            result = _run_notes(tmp_jd_root, monkeypatch, ["scan"])
        assert result.exit_code == 1
        assert "Could not read Apple Notes" in result.output


class TestNotesValidate:
    def test_no_declarations(self, tmp_jd_root, monkeypatch):
        result = _run_notes(tmp_jd_root, monkeypatch, ["validate"])
        assert "No notes declarations" in result.output

    def test_consistent(self, tmp_jd_root, write_policy, monkeypatch):
        write_policy({"notes": {"26": ["26.05"]}})
        # Create stub, remove dir
        sourdough_dir = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"
        sourdough_dir.rmdir()
        stub = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough [Apple Notes].yaml"
        stub_data = {
            "location": "Apple Notes",
            "path": "20-29 Projects > 26 Recipes > 26.05 Sourdough",
        }
        stub.write_text(yaml.dump(stub_data))

        with patch("johnnydecimal.notes.note_exists", return_value=True), \
             patch("johnnydecimal.notes.folder_exists", return_value=True):
            result = _run_notes(tmp_jd_root, monkeypatch, ["validate"])
        assert "consistent" in result.output.lower() or result.exit_code == 0

    def test_stub_without_note(self, tmp_jd_root, write_policy, monkeypatch):
        write_policy({"notes": {"26": ["26.05"]}})
        sourdough_dir = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"
        sourdough_dir.rmdir()
        stub = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough [Apple Notes].yaml"
        stub.write_text(yaml.dump({"location": "Apple Notes", "path": "x"}))

        with patch("johnnydecimal.notes.note_exists", return_value=False), \
             patch("johnnydecimal.notes.folder_exists", return_value=True):
            result = _run_notes(tmp_jd_root, monkeypatch, ["validate"])
        assert result.exit_code == 1
        assert "stub exists but note missing" in result.output

    def test_dir_and_notes_conflict(self, tmp_jd_root, write_policy, monkeypatch):
        write_policy({"notes": {"26": ["26.05"]}})
        # 26.05 exists as directory (conflict)
        with patch("johnnydecimal.notes.note_exists", return_value=True), \
             patch("johnnydecimal.notes.folder_exists", return_value=True):
            result = _run_notes(tmp_jd_root, monkeypatch, ["validate"])
        assert "directory AND declared as Notes-backed" in result.output


class TestNotesStub:
    def test_creates_stub(self, tmp_jd_root, monkeypatch):
        with patch("johnnydecimal.notes.note_exists", return_value=True):
            result = _run_notes(tmp_jd_root, monkeypatch, ["stub", "26.05"])
        assert "Created:" in result.output
        assert "[Apple Notes].yaml" in result.output

        # Check stub file content
        stub = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough [Apple Notes].yaml"
        assert stub.exists()
        data = yaml.safe_load(stub.read_text())
        assert data["location"] == "Apple Notes"
        assert "26.05 Sourdough" in data["path"]

    def test_idempotent(self, tmp_jd_root, monkeypatch):
        stub = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough [Apple Notes].yaml"
        stub.write_text("existing")

        with patch("johnnydecimal.notes.note_exists", return_value=True):
            result = _run_notes(tmp_jd_root, monkeypatch, ["stub", "26.05"])
        assert "already exists" in result.output

    def test_id_not_found(self, tmp_jd_root, monkeypatch):
        result = _run_notes(tmp_jd_root, monkeypatch, ["stub", "99.99"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_warns_when_note_missing(self, tmp_jd_root, monkeypatch):
        with patch("johnnydecimal.notes.note_exists", return_value=False):
            result = _run_notes(tmp_jd_root, monkeypatch, ["stub", "26.05"])
        assert "not found in Notes" in result.output
        # Still creates stub
        stub = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough [Apple Notes].yaml"
        assert stub.exists()


class TestNotesCreate:
    def test_creates_note(self, tmp_jd_root, monkeypatch):
        with patch("johnnydecimal.notes.folder_exists", return_value=True), \
             patch("johnnydecimal.notes.note_exists", return_value=False), \
             patch("johnnydecimal.notes.create_note") as mock_create:
            result = _run_notes(tmp_jd_root, monkeypatch, ["create", "26.05"])
        assert "Created note:" in result.output
        mock_create.assert_called_once()

    def test_creates_folder_flag(self, tmp_jd_root, monkeypatch):
        with patch("johnnydecimal.notes.folder_exists", side_effect=[True, True, False]), \
             patch("johnnydecimal.notes.create_folder") as mock_folder:
            result = _run_notes(tmp_jd_root, monkeypatch, ["create", "26.05", "--folder"])
        assert "Created folder:" in result.output
        mock_folder.assert_called_once()

    def test_creates_stub_flag(self, tmp_jd_root, monkeypatch):
        with patch("johnnydecimal.notes.folder_exists", return_value=True), \
             patch("johnnydecimal.notes.note_exists", return_value=False), \
             patch("johnnydecimal.notes.create_note"):
            result = _run_notes(tmp_jd_root, monkeypatch, ["create", "26.05", "--stub"])
        assert "Created stub:" in result.output
        stub = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough [Apple Notes].yaml"
        assert stub.exists()

    def test_id_not_found(self, tmp_jd_root, monkeypatch):
        result = _run_notes(tmp_jd_root, monkeypatch, ["create", "99.99"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_note_already_exists(self, tmp_jd_root, monkeypatch):
        with patch("johnnydecimal.notes.folder_exists", return_value=True), \
             patch("johnnydecimal.notes.note_exists", return_value=True):
            result = _run_notes(tmp_jd_root, monkeypatch, ["create", "26.05"])
        assert "already exists" in result.output


class TestNotesOpen:
    def test_opens_note(self, tmp_jd_root, monkeypatch):
        with patch("johnnydecimal.notes.open_note") as mock_open:
            result = _run_notes(tmp_jd_root, monkeypatch, ["open", "26.05"])
        assert "Opened:" in result.output
        mock_open.assert_called_once()

    def test_id_not_found(self, tmp_jd_root, monkeypatch):
        result = _run_notes(tmp_jd_root, monkeypatch, ["open", "99.99"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_notes_error(self, tmp_jd_root, monkeypatch):
        from johnnydecimal.notes import NotesError
        with patch("johnnydecimal.notes.open_note", side_effect=NotesError("fail")):
            result = _run_notes(tmp_jd_root, monkeypatch, ["open", "26.05"])
        assert result.exit_code == 1
        assert "Could not open note" in result.output


class TestValidateSkipsNotesStubs:
    """Test that jd validate step 10 skips [Apple Notes] stubs."""

    def test_notes_stub_not_flagged(self, tmp_jd_root, monkeypatch):
        from johnnydecimal.models import JDSystem

        # Remove directory, create stub file
        sourdough_dir = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough"
        sourdough_dir.rmdir()
        stub = tmp_jd_root / "20-29 Projects" / "26 Recipes" / "26.05 Sourdough [Apple Notes].yaml"
        stub.write_text(yaml.dump({"location": "Apple Notes", "path": "x"}))

        monkeypatch.setattr("johnnydecimal.cli.get_root", lambda: JDSystem(tmp_jd_root))
        runner = CliRunner()
        result = runner.invoke(cli, ["validate"])
        # Should NOT report "FILE AS ID" for the Apple Notes stub
        assert "FILE AS ID" not in result.output
