"""Tests for johnnydecimal.policy functions."""

import yaml
from johnnydecimal.policy import find_root_policy, get_links


class TestFindRootPolicy:
    def test_locates_policy_in_standard_tree(self, tmp_jd_root, policy_path):
        result = find_root_policy(tmp_jd_root)
        assert result == policy_path

    def test_returns_none_for_empty_dir(self, tmp_path):
        assert find_root_policy(tmp_path) is None


class TestGetLinks:
    def test_parses_list_form(self, tmp_jd_root, write_policy):
        write_policy({"links": {"26.05": ["~/.ssh", "~/bin"]}})
        result = get_links(tmp_jd_root)
        assert result == {"26.05": ["~/.ssh", "~/bin"]}

    def test_parses_string_form(self, tmp_jd_root, write_policy):
        write_policy({"links": {"26.05": "~/.ssh"}})
        result = get_links(tmp_jd_root)
        assert result == {"26.05": ["~/.ssh"]}

    def test_returns_empty_when_no_links(self, tmp_jd_root, policy_path):
        policy_path.write_text(yaml.dump({"conventions": {}}))
        result = get_links(tmp_jd_root)
        assert result == {}

    def test_returns_empty_when_no_policy(self, tmp_path):
        result = get_links(tmp_path)
        assert result == {}

    def test_handles_yaml_float_keys(self, tmp_jd_root, write_policy):
        """YAML parses bare 06.05 as float 6.05 — get_links should str() it."""
        write_policy({"links": {6.05: ["~/.ssh"]}})
        result = get_links(tmp_jd_root)
        assert "6.05" in result
