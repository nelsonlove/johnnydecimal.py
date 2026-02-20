"""
Agent scoping for Johnny Decimal.

Agents declare which areas/categories they can write to via a jd.yaml file
in their workspace directory. Reads are always allowed.

Scope file format (jd.yaml):
    scope:
      - "20-29"       # entire area
      - "42"          # single category
      - "86.03"       # single ID (rare, but allowed)
    # scope: all      # unrestricted (Rex)

Resolution:
    1. JD_AGENT_SCOPE env var (path to jd.yaml)
    2. ./jd.yaml in CWD
    3. No scope file = unrestricted (backward compat)
"""

import os
import re
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None


def find_scope_file() -> Optional[Path]:
    """Find the agent scope file, if any."""
    # 1. Explicit env var
    env_path = os.environ.get("JD_AGENT_SCOPE")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
        return None

    # 2. CWD
    cwd_scope = Path.cwd() / "jd.yaml"
    if cwd_scope.exists():
        return cwd_scope

    return None


def load_scope(scope_file: Optional[Path] = None) -> Optional[list]:
    """
    Load scope from a jd.yaml file.
    Returns None if no scope (unrestricted) or list of scope patterns.
    """
    if scope_file is None:
        scope_file = find_scope_file()
    if scope_file is None:
        return None  # unrestricted

    if yaml is None:
        return None  # can't parse, fail open

    try:
        with open(scope_file) as f:
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError):
        return None

    scope = data.get("scope")
    if scope == "all" or scope is None:
        return None  # unrestricted
    if isinstance(scope, list):
        return [str(s) for s in scope]
    return None


def is_in_scope(target: str, scope: list) -> bool:
    """
    Check if a JD target (area, category number, or ID) is within scope.

    target: "20-29", "21", "26.01", etc.
    scope: list of patterns like ["20-29", "42", "86.03"]
    """
    for pattern in scope:
        pattern = str(pattern).strip()

        # Area range: "20-29"
        m = re.match(r"(\d{2})-(\d{2})$", pattern)
        if m:
            low, high = int(m.group(1)), int(m.group(2))
            # Extract the leading number from target
            target_num = _extract_number(target)
            if target_num is not None and low <= target_num <= high:
                return True
            continue

        # Specific category: "42"
        if re.match(r"\d{2}$", pattern):
            target_num = _extract_number(target)
            if target_num is not None and target_num == int(pattern):
                return True
            # Also match IDs within this category: "42.xx"
            if re.match(rf"^{pattern}\.", target):
                return True
            continue

        # Specific ID: "86.03"
        if re.match(r"\d{2}\.\d{2}$", pattern):
            if target == pattern:
                return True
            continue

    return False


def _extract_number(target: str) -> Optional[int]:
    """Extract the leading category/area number from a target string."""
    # "26.01" → 26
    m = re.match(r"(\d{2})\.\d{2}$", target)
    if m:
        return int(m.group(1))
    # "21" → 21
    m = re.match(r"(\d{2})$", target)
    if m:
        return int(m.group(1))
    # "20-29" → 20
    m = re.match(r"(\d{2})-\d{2}$", target)
    if m:
        return int(m.group(1))
    return None


def check_scope(target: str, scope_file: Optional[Path] = None) -> tuple[bool, Optional[str]]:
    """
    Check if an operation on target is allowed by agent scope.
    Returns (allowed, message).
    """
    scope = load_scope(scope_file)
    if scope is None:
        return True, None  # unrestricted

    if is_in_scope(target, scope):
        return True, None

    return False, f"Out of scope: {target} is not in agent scope {scope}"
