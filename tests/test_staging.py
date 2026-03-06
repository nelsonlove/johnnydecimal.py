"""Tests for johnnydecimal.staging — Finder tag helpers."""

from pathlib import Path
from unittest.mock import patch

import pytest

from johnnydecimal.staging import add_jd_tag, get_jd_tags, remove_jd_tag

STAGING = "johnnydecimal.staging"


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
