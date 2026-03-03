"""Shared fixtures for jd-cli tests."""

import yaml
import pytest
from pathlib import Path


@pytest.fixture
def tmp_jd_root(tmp_path):
    """Build a minimal JD tree in tmp_path and return the root Path.

    Structure:
        00-09 Meta/
            00 Indices/
                00.00 Meta/
                    policy.yaml  (empty)
        10-19 Admin/
            11 Finance/
                11.00 Finance - Meta/
                11.01 Finance - Unsorted/
        20-29 Projects/
            26 Recipes/
                26.00 Recipes - Meta/
                26.05 Sourdough/
    """
    root = tmp_path / "jd-root"
    root.mkdir()

    # 00-09 Meta
    area0 = root / "00-09 Meta"
    area0.mkdir()
    cat00 = area0 / "00 Indices"
    cat00.mkdir()
    meta00 = cat00 / "00.00 Meta"
    meta00.mkdir()
    (meta00 / "policy.yaml").write_text("")

    # 10-19 Admin
    area1 = root / "10-19 Admin"
    area1.mkdir()
    cat11 = area1 / "11 Finance"
    cat11.mkdir()
    (cat11 / "11.00 Finance - Meta").mkdir()
    (cat11 / "11.01 Finance - Unsorted").mkdir()

    # 20-29 Projects
    area2 = root / "20-29 Projects"
    area2.mkdir()
    cat26 = area2 / "26 Recipes"
    cat26.mkdir()
    (cat26 / "26.00 Recipes - Meta").mkdir()
    (cat26 / "26.05 Sourdough").mkdir()

    return root


@pytest.fixture
def policy_path(tmp_jd_root):
    """Return the root policy.yaml path inside the tmp JD tree."""
    return tmp_jd_root / "00-09 Meta" / "00 Indices" / "00.00 Meta" / "policy.yaml"


@pytest.fixture
def write_policy(policy_path):
    """Return a helper that writes a dict to the root policy.yaml."""
    def _write(data: dict):
        policy_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return _write
