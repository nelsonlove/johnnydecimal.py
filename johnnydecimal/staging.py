"""Staging — surface JD items on Desktop and return them."""

import plistlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

XATTR_KEY = "com.apple.metadata:_kMDItemUserTags"
JD_TAG_RE = re.compile(r"^JD:(\d{2}\.\d{2})$")


def _read_finder_tags(path: Path) -> list[str]:
    """Read Finder tags from a path via xattr.

    Run ``xattr -px com.apple.metadata:_kMDItemUserTags <path>``.
    Output is space-separated hex lines.  Join, decode hex to bytes,
    parse with ``plistlib.loads()``.  Return ``[]`` if xattr returns
    non-zero.
    """
    try:
        result = subprocess.run(
            ["xattr", "-px", XATTR_KEY, str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return []

    hex_str = result.stdout.replace(" ", "").replace("\n", "")
    raw = bytes.fromhex(hex_str)
    return plistlib.loads(raw)


def _write_finder_tags(path: Path, tags: list[str]) -> None:
    """Write Finder tags to a path via xattr."""
    raw = plistlib.dumps(tags, fmt=plistlib.FMT_BINARY)
    hex_str = raw.hex()
    subprocess.run(
        ["xattr", "-wx", XATTR_KEY, hex_str, str(path)],
        check=True,
    )


def get_jd_tags(path: Path) -> list[str]:
    """Return JD ID strings (e.g. ``["26.05", "11.03"]``) from Finder tags."""
    tags = _read_finder_tags(path)
    results = []
    for tag in tags:
        m = JD_TAG_RE.match(tag)
        if m:
            results.append(m.group(1))
    return results


def add_jd_tag(path: Path, jd_id: str) -> None:
    """Add a ``JD:<jd_id>`` Finder tag.  No-op if already present."""
    tags = _read_finder_tags(path)
    jd_tag = f"JD:{jd_id}"
    if jd_tag in tags:
        return
    tags.append(jd_tag)
    _write_finder_tags(path, tags)


def remove_jd_tag(path: Path, jd_id: str | None = None) -> None:
    """Remove JD Finder tag(s).

    If *jd_id* is given, remove only ``JD:<jd_id>``.
    If *None*, remove all ``JD:*`` tags.  Only write if changed.
    """
    tags = _read_finder_tags(path)
    if jd_id is not None:
        new_tags = [t for t in tags if t != f"JD:{jd_id}"]
    else:
        new_tags = [t for t in tags if not JD_TAG_RE.match(t)]
    if new_tags != tags:
        _write_finder_tags(path, new_tags)


def stage_items(
    id_dir: Path,
    jd_id: str,
    desktop: Path,
    dry_run: bool = False,
) -> list[str]:
    """Move real items from *id_dir* to *desktop* with an ID prefix.

    For each top-level item (skipping dotfiles and existing symlinks):
    * Move to ``desktop / "{jd_id} {item.name}"``
    * Tag the moved file with ``add_jd_tag``
    * Leave a symlink at the original location pointing to the desktop copy

    If *dry_run* is ``True``, collect names but perform no filesystem changes.
    Returns a list of item names that were (or would be) staged.
    """
    staged: list[str] = []
    for item in sorted(id_dir.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_symlink():
            continue
        staged.append(item.name)
        if not dry_run:
            dest = desktop / f"{jd_id} {item.name}"
            shutil.move(str(item), str(dest))
            add_jd_tag(dest, jd_id)
            item.symlink_to(dest)
    return staged


def _strip_id_prefix(name: str, jd_id: str) -> str:
    """Remove a leading ``"{jd_id} "`` prefix if present."""
    prefix = f"{jd_id} "
    if name.startswith(prefix):
        return name[len(prefix):]
    return name


def unstage_items(
    desktop: Path,
    find_id_dir: Callable[[str], Path | None],
    filter_id: str | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Move JD-tagged items from *desktop* back to their ID directories.

    For each top-level item on *desktop* (skipping dotfiles):
    * Read JD tags — skip if none
    * Use the first JD tag as the jd_id; skip if *filter_id* is set and
      doesn't match
    * Look up the ID directory via *find_id_dir* — skip if ``None``
    * Strip the ID prefix from the desktop name to recover the original name
    * Remove any symlink at the destination, move the item back, and remove
      the JD tag

    If *dry_run* is ``True``, collect results but perform no filesystem changes.
    Returns a list of dicts with keys ``name``, ``jd_id``, ``dest``.
    """
    results: list[dict] = []
    for item in sorted(desktop.iterdir()):
        if item.name.startswith("."):
            continue
        jd_tags = get_jd_tags(item)
        if not jd_tags:
            continue
        jd_id = jd_tags[0]
        if filter_id is not None and jd_id != filter_id:
            continue
        id_dir = find_id_dir(jd_id)
        if id_dir is None:
            continue
        original_name = _strip_id_prefix(item.name, jd_id)
        dest = id_dir / original_name
        if not dry_run:
            if dest.is_symlink():
                dest.unlink()
            shutil.move(str(item), str(dest))
            remove_jd_tag(dest, jd_id)
        results.append({"name": item.name, "jd_id": jd_id, "dest": str(dest)})
    return results
