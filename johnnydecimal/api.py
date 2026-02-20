from pathlib import Path

from johnnydecimal.exceptions import NotJohnnyDecimalDirectoryError
from johnnydecimal.models import JDSystem
from johnnydecimal.util import (
    is_jd_area, is_jd_category, is_jd_id, is_jd_root, get_jd_root_dir,
)


def get_areas(root: Path) -> list[Path]:
    """Get the area directories in a JD filing system."""
    return [subdir for subdir in sorted(root.iterdir()) if is_jd_area(subdir)]


def get_categories(area: Path) -> list[Path]:
    """Get the category directories in a JD area."""
    return [subdir for subdir in sorted(area.iterdir()) if is_jd_category(subdir)]


def get_ids(category: Path) -> list[Path]:
    """Get the ID directories in a JD category."""
    return [subdir for subdir in sorted(category.iterdir()) if is_jd_id(subdir)]


def get_system(path: Path) -> JDSystem:
    """
    Load a JD system from a path. Walks up to find the root if needed.
    """
    root = get_jd_root_dir(path)
    if is_jd_root(root):
        return JDSystem(root)
    else:
        raise NotJohnnyDecimalDirectoryError(path)
