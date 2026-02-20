import re
from abc import ABCMeta
from pathlib import Path

from johnnydecimal.util import (
    is_jd_directory, is_jd_area, is_jd_category, is_jd_id, is_jd_id_file,
    is_symlink_valid,
)
from johnnydecimal.exceptions import NotJohnnyDecimalDirectoryError


class JDAbstract(metaclass=ABCMeta):
    def __init__(self, path, parent=None):
        self.path = path
        self.parent = parent
        self._validate()
        self._number = None
        self._name = None

    @property
    def number(self):
        return self._number

    @property
    def name(self):
        return self._name

    def _validate(self):
        if not self.path.exists():
            raise FileNotFoundError(f"The path {self.path} does not exist.")


class JDDirectory(JDAbstract):
    def _validate(self):
        if not is_jd_directory(self.path):
            raise NotJohnnyDecimalDirectoryError(self.path)
        return super()._validate()


class JDSystem(JDDirectory):
    """Represents the root of a Johnny Decimal filing system."""

    def __init__(self, path):
        self.path = path
        self.areas = self._get_areas()
        self._broken_symlinks = None

    def _get_areas(self):
        areas = []
        for subdir in sorted(self.path.iterdir()):
            if is_jd_area(subdir):
                if subdir.is_symlink() and not is_symlink_valid(subdir):
                    continue  # skip broken symlinks to external drives
                areas.append(JDArea(subdir, self))
        return areas

    @property
    def broken_symlinks(self):
        """Find broken symlinks at any level (lazy, only scans JD dirs)."""
        if self._broken_symlinks is None:
            self._broken_symlinks = []
            for area in self.areas:
                for item in area.path.iterdir():
                    if item.is_symlink() and not is_symlink_valid(item):
                        self._broken_symlinks.append(item)
                for cat in area.categories:
                    for item in cat.path.iterdir():
                        if item.is_symlink() and not is_symlink_valid(item):
                            self._broken_symlinks.append(item)
        return self._broken_symlinks

    def find_by_id(self, id_str):
        """Find a JD ID folder by its dotted notation (e.g., '26.01')."""
        for area in self.areas:
            for category in area.categories:
                for jd_id in category.ids:
                    if jd_id.id_str == id_str:
                        return jd_id
        return None

    def find_by_category(self, cat_num):
        """Find a category by its number (e.g., 26)."""
        for area in self.areas:
            for category in area.categories:
                if category.number == cat_num:
                    return category
        return None

    def all_ids(self):
        """Return all JD IDs in the system."""
        ids = []
        for area in self.areas:
            for category in area.categories:
                ids.extend(category.ids)
        return ids

    def find_duplicates(self):
        """Find duplicate IDs across the system."""
        seen = {}
        dupes = []
        for jd_id in self.all_ids():
            if jd_id.id_str in seen:
                dupes.append((jd_id.id_str, seen[jd_id.id_str].path, jd_id.path))
            else:
                seen[jd_id.id_str] = jd_id
        return dupes

    def find_orphans(self):
        """Find non-JD directories inside the tree."""
        orphans = []
        for area in self.areas:
            for item in sorted(area.path.iterdir()):
                if item.is_dir() and not item.name.startswith("."):
                    if not is_jd_category(item) and not is_jd_id(item):
                        orphans.append(item)
            for category in area.categories:
                for item in sorted(category.path.iterdir()):
                    if item.is_dir() and not item.name.startswith("."):
                        if not is_jd_id(item):
                            orphans.append(item)
        return orphans

    def to_dict(self):
        """Machine-readable representation for jd.json."""
        return {
            "root": str(self.path),
            "areas": [a.to_dict() for a in self.areas],
            "broken_symlinks": [str(s) for s in self.broken_symlinks],
        }


class JDArea(JDDirectory):
    """Represents a JD area (e.g., '20-29 Family')."""

    def __init__(self, path, parent: JDSystem):
        self.path = path
        self.system = parent
        self.parent = parent
        # Parse: "20-29 Family" or "20–29 Family"
        match = re.match(r"(\d{2})[-–](\d{2}) (.+)", path.name)
        if match:
            self._number = int(match.group(1))
            self._end_number = int(match.group(2))
            self._name = match.group(3)
        else:
            self._number = 0
            self._end_number = 9
            self._name = path.name
        self.categories = self._get_categories()

    def _validate(self):
        pass  # Skip parent validation, we handle it in __init__

    def _get_categories(self):
        cats = []
        for subdir in sorted(self.path.iterdir()):
            if is_jd_category(subdir):
                if subdir.is_symlink() and not is_symlink_valid(subdir):
                    continue
                cats.append(JDCategory(subdir, self))
        return cats

    def to_dict(self):
        return {
            "number": self._number,
            "name": self._name,
            "path": str(self.path),
            "categories": [c.to_dict() for c in self.categories],
        }

    def __str__(self):
        return f"{self._number:02d}-{self._end_number:02d} {self._name}"


class JDCategory(JDDirectory):
    """Represents a JD category (e.g., '26 Recipes')."""

    def __init__(self, path, parent: JDArea):
        self.path = path
        self.parent = parent
        self.area = parent
        # Parse: "26 Recipes"
        match = re.match(r"(\d{2}) (.+)", path.name)
        if match:
            self._number = int(match.group(1))
            self._name = match.group(2)
        else:
            self._number = 0
            self._name = path.name
        self.ids = self._get_ids()

    def _validate(self):
        pass

    def _get_ids(self):
        ids = []
        for item in sorted(self.path.iterdir()):
            if is_jd_id(item):
                if item.is_symlink() and not is_symlink_valid(item):
                    continue
                ids.append(JDID(item, self))
            elif is_jd_id_file(item):
                ids.append(JDID(item, self))
        return ids

    def next_id(self):
        """Get the next available ID number in this category."""
        used = {jd_id.sequence for jd_id in self.ids}
        for i in range(1, 100):
            if i not in used:
                return i
        raise ValueError(f"Category {self._number} is full")

    def to_dict(self):
        return {
            "number": self._number,
            "name": self._name,
            "path": str(self.path),
            "ids": [i.to_dict() for i in self.ids],
        }

    def __str__(self):
        return f"{self._number:02d} {self._name}"


class JDID(JDDirectory):
    """Represents a JD ID (e.g., '26.01 Unsorted')."""

    def __init__(self, path, parent: JDCategory):
        self.path = path
        self.parent = parent
        self.category = parent
        # Parse: "26.01 Unsorted" or "26.00" (meta, no name required)
        match = re.match(r"(\d{2})\.(\d{2})(?:\s+(.+))?", path.name)
        if match:
            self._cat_number = int(match.group(1))
            self._sequence = int(match.group(2))
            self._name = match.group(3) or ""
        else:
            self._cat_number = 0
            self._sequence = 0
            self._name = path.name
        self._number = self._cat_number  # for compatibility

    def _validate(self):
        pass

    @property
    def sequence(self):
        return self._sequence

    @property
    def id_str(self):
        """The dotted ID string, e.g., '26.01'."""
        return f"{self._cat_number:02d}.{self._sequence:02d}"

    @property
    def is_file(self):
        """True if this ID is a file rather than a directory."""
        return not self.path.is_dir()

    @property
    def is_mismatched(self):
        """Check if this ID's category prefix doesn't match its parent category."""
        return self._cat_number != self.category.number

    def to_dict(self):
        return {
            "id": self.id_str,
            "name": self._name,
            "path": str(self.path),
            "is_symlink": self.path.is_symlink(),
            "symlink_target": str(self.path.resolve()) if self.path.is_symlink() else None,
            "mismatched": self.is_mismatched,
        }

    def __str__(self):
        return f"{self.id_str} {self._name}"
