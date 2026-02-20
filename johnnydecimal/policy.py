"""
Declarative policy system for Johnny Decimal.

Policy files (.johnnydecimal.yaml) can live at any level of the tree
and cascade like .editorconfig — most specific wins.

Resolution order: ID dir → category dir → area dir → root dir → defaults.
"""

import yaml
from pathlib import Path
from typing import Any, Optional


# System defaults — apply when no policy file overrides
DEFAULTS = {
    "conventions": {
        "meta_category": True,       # x0 = "Meta - [Area]"
        "meta_id": True,             # xx.00 = category meta
        "unsorted_id": True,         # xx.01 = "Unsorted"
        "ids_files_only": False,     # allow subdirs inside IDs
        "ids_as_files": False,       # allow IDs to be files (not dirs)
        "capture_category": "01",    # which category is the capture inbox
        "naming": {
            "separator": "-",        # hyphen, not en-dash
            "case": "sentence",      # sentence case for names
            "no_trailing_spaces": True,
            "no_special_chars": True,  # avoid :, *, ? etc.
        },
    },
    "ignore": [
        ".DS_Store",
        ".git",
        "__pycache__",
        ".Trash",
        "*.pyc",
    ],
}

POLICY_FILENAME = "policy.yaml"


def find_meta_dir(path: Path) -> Optional[Path]:
    """
    Find the meta dir (xx.00) for a given JD path.
    
    - If path IS a meta dir (xx.00), return it.
    - If path is an ID (xx.yy), look for xx.00 in the same category.
    - If path is a category (xx), look for xx.00 inside it.
    - If path is an area (xx-xx), look for x0 meta category, then x0.00 inside it.
    - If path is root, look for 00 Indices/00.00 (or 00.00 in any meta category).
    """
    import re
    
    name = path.name
    
    # Is this already a meta dir (xx.00)?
    if re.match(r"\d{2}\.00$", name):
        return path
    
    # Is this an ID (xx.yy)? → sibling xx.00
    m = re.match(r"(\d{2})\.\d{2}", name)
    if m:
        cat_num = m.group(1)
        meta = path.parent / f"{cat_num}.00"
        if meta.exists():
            return meta
        return None
    
    # Is this a category (xx Name)? → child xx.00
    m = re.match(r"(\d{2}) ", name)
    if m:
        cat_num = m.group(1)
        meta = path / f"{cat_num}.00"
        if meta.exists():
            return meta
        return None
    
    # Is this an area (xx-xx Name)? → find x0 meta category, then x0.00
    m = re.match(r"(\d)(\d)[-–]\d{2} ", name)
    if m:
        area_digit = m.group(1)
        meta_cat_num = f"{area_digit}0"
        # Look for the x0 category dir
        for child in path.iterdir():
            if child.is_dir() and child.name.startswith(f"{meta_cat_num} "):
                meta = child / f"{meta_cat_num}.00"
                if meta.exists():
                    return meta
                return None
        return None
    
    # Root — look for 00-09 area → 00 category → 00.00
    for area_child in path.iterdir():
        if area_child.is_dir() and re.match(r"00[-–]09 ", area_child.name):
            for cat_child in area_child.iterdir():
                if cat_child.is_dir() and cat_child.name.startswith("00 "):
                    meta = cat_child / "00.00"
                    if meta.exists():
                        return meta
    return None


def load_policy_file(path: Path) -> Optional[dict]:
    """Load policy.yaml from the meta dir for a given path."""
    meta = find_meta_dir(path)
    if meta:
        policy_path = meta / POLICY_FILENAME
        if policy_path.exists():
            try:
                with open(policy_path) as f:
                    return yaml.safe_load(f) or {}
            except (yaml.YAMLError, OSError):
                return None
    return None


def deep_merge(base: dict, override: dict) -> dict:
    """
    Deep merge two dicts. Override values win.
    Lists are replaced, not appended.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def match_pattern(pattern: str, dir_name: str) -> bool:
    """
    Match a JD pattern against a directory name.
    
    Supported patterns:
      "*.00"  — any xx.00 (category meta)
      "*.01"  — any xx.01 (unsorted)
      "*.NN"  — any xx.NN
      "x0"    — any area meta category (10, 20, 30, ..., 90) but not 00
      "NN"    — specific category number
      "NN.MM" — specific ID
    """
    import re
    
    # "*.NN" — match any ID with this sequence number
    m = re.match(r"^\*\.(\d{2})$", pattern)
    if m:
        seq = m.group(1)
        return bool(re.match(rf"\d{{2}}\.{seq}($|\s)", dir_name))
    
    # "x0" — area meta categories (10, 20, 30, ..., 90)
    if pattern == "x0":
        m2 = re.match(r"(\d)0\s", dir_name)
        return bool(m2) and m2.group(1) != "0"
    
    # "NN.MM" — specific ID
    if re.match(r"\d{2}\.\d{2}$", pattern):
        return dir_name.startswith(pattern)
    
    # "NN" — specific category
    if re.match(r"\d{2}$", pattern):
        return bool(re.match(rf"^{pattern}\s", dir_name))
    
    return False


def resolve_policy(path: Path, root: Path) -> dict:
    """
    Resolve the effective policy for a given path by walking up
    from path to root, collecting and merging policy files.
    
    Resolution order at each level:
    1. Base conventions from policy file
    2. Pattern matches from that same policy file
    
    Most specific level (closest to path) wins.
    """
    # Don't resolve symlinks — walk the logical JD path
    # so symlinked categories still pick up area/root policy
    root_resolved = root.resolve()

    # Walk from path up to root
    chain = []
    current = path
    while True:
        chain.append(current)
        if current.resolve() == root_resolved:
            break
        parent = current.parent
        if parent == current:
            # Hit filesystem root without finding JD root — add it manually
            if root not in chain:
                chain.append(root)
            break
        current = parent

    # Reverse so root is first (base), path is last (override)
    chain.reverse()

    # Start with defaults
    effective = DEFAULTS.copy()

    # The target dir name (what we match patterns against)
    target_name = path.resolve().name

    # Layer on each policy file from root → path
    for dir_path in chain:
        policy = load_policy_file(dir_path)
        if policy:
            # First apply base conventions
            base = {k: v for k, v in policy.items() if k != "patterns"}
            if base:
                effective = deep_merge(effective, base)

            # Then apply matching patterns
            patterns = policy.get("patterns", {})
            for pattern, pattern_policy in patterns.items():
                if match_pattern(pattern, target_name):
                    effective = deep_merge(effective, 
                                          {"conventions": pattern_policy} if "conventions" not in pattern_policy 
                                          else pattern_policy)

    return effective


def get_convention(policy: dict, key: str, default: Any = None) -> Any:
    """Get a convention value from a resolved policy."""
    conventions = policy.get("conventions", {})
    if "." in key:
        # Nested key like "naming.separator"
        parts = key.split(".")
        current = conventions
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return default
        return current if current is not None else default
    return conventions.get(key, default)
