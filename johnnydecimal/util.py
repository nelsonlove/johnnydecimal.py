import re
from pathlib import Path

from johnnydecimal.exceptions import NotJohnnyDecimalDirectoryError


def is_jd_area(directory: Path) -> bool:
    """
    Check if a directory is a Johnny Decimal area.
    Areas are top-level groupings: "10-19 Personal", "20-29 Family", etc.
    Supports both hyphens and en-dashes.
    """
    if not directory.is_dir():
        return False
    return re.match(r"\d{2}[-–]\d{2} .+", directory.name) is not None


def is_jd_category(directory: Path) -> bool:
    """
    Check if a directory is a Johnny Decimal category.
    Categories are two-digit numbered dirs: "26 Recipes", "10 Meta - Personal", etc.
    Must NOT match area pattern (XX-XX) or ID pattern (XX.XX).
    """
    if not directory.is_dir():
        return False
    name = directory.name
    # Must match "NN Something" but not "NN-NN Something" (area) or "NN.NN Something" (ID)
    if re.match(r"\d{2}[-–]\d{2} ", name):
        return False
    if re.match(r"\d{2}\.\d{2} ", name):
        return False
    return re.match(r"\d{2} .+", name) is not None


def is_jd_id(directory: Path) -> bool:
    """
    Check if a directory is a Johnny Decimal ID.
    IDs have dotted notation: "26.01 Unsorted", "13.05 Lab results", etc.
    xx.00 (category meta) has no name suffix required.
    """
    if not directory.is_dir():
        return False
    # xx.00 can stand alone (no name), all others need a name
    return re.match(r"\d{2}\.\d{2}($| .+)", directory.name) is not None


def is_jd_id_file(path: Path) -> bool:
    """Check if a file (not dir) has a JD ID naming pattern."""
    if path.is_dir():
        return False
    # Match "26.01 Name.ext" or "26.00.md" etc.
    stem = path.name
    return re.match(r"\d{2}\.\d{2}($| .+)", stem) is not None


def is_jd_root(directory: Path) -> bool:
    """
    Check if a directory is the root of a Johnny Decimal filing system.
    A root has at least 3 JD area directories. Non-JD dirs are tolerated
    (orphans like FabFilter, Zoom, etc. are common in ~/Documents).
    """
    try:
        children = [d for d in directory.iterdir() if d.is_dir() and not d.name.startswith(".")]
    except PermissionError:
        return False
    area_count = sum(1 for d in children if is_jd_area(d))
    return area_count >= 3


def is_in_user_home(directory: Path) -> bool:
    """Check if a directory is in the user's home directory."""
    return directory.is_relative_to(Path.home())


def is_jd_directory(directory: Path) -> bool:
    """Check if a directory is any kind of JD directory (area, category, ID, or root)."""
    return is_jd_area(directory) or is_jd_category(directory) or is_jd_id(directory) or is_jd_root(directory)


def is_symlink_valid(path: Path) -> bool:
    """Check if a symlink target exists (returns True for non-symlinks)."""
    if path.is_symlink():
        try:
            path.resolve(strict=True)
            return True
        except (OSError, FileNotFoundError):
            return False
    return True


def get_jd_root_dir(start_path: Path) -> Path:
    """
    Find the root directory of the user's Johnny Decimal filing system
    by walking up from start_path.
    """
    path = start_path
    while not is_jd_root(path) and is_in_user_home(path):
        path = path.parent
    if is_jd_root(path):
        return path
    raise NotJohnnyDecimalDirectoryError(path)


def parse_jd_id_string(id_str: str) -> tuple[int, int]:
    """
    Parse a JD ID string like '26.01' into (category, sequence).
    Returns (26, 1) for '26.01'.
    """
    match = re.match(r"(\d{2})\.(\d{2})", id_str)
    if not match:
        raise ValueError(f"Invalid JD ID format: {id_str} (expected XX.XX)")
    return int(match.group(1)), int(match.group(2))


def format_jd_id(category: int, sequence: int) -> str:
    """Format a JD ID as a string: (26, 1) -> '26.01'."""
    return f"{category:02d}.{sequence:02d}"
