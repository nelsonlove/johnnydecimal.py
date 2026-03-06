"""Staging — surface JD items on Desktop and return them."""

import plistlib
import re
import subprocess
from pathlib import Path

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
