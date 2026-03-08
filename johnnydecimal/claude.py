"""
jd claude — launch Claude Code with cascading JD context.

Walks up from CWD to find the nearest JD level (ID → category → area → root),
collects context files from each meta dir in the cascade, and launches Claude
with the concatenated context via --append-system-prompt.
"""

import re
import subprocess
import shutil
from pathlib import Path
from typing import Optional

from johnnydecimal.policy import find_meta_dir
from johnnydecimal.util import (
    is_jd_id, is_jd_category, is_jd_area, is_jd_root,
)


# Defaults — will be configurable via jd.yaml config.claude.include
DEFAULT_STEMS = ["README", "TODO", "CLAUDE", "AUDIT", "TIMELINE"]
DEFAULT_EXTENSIONS = [".md", ".org", ".txt"]


def find_nearest_jd_level(start: Path) -> Optional[Path]:
    """Walk up from start to find the nearest JD level (id, category, area, or root).

    Does NOT resolve symlinks — walks the logical JD path so symlinked
    IDs (e.g. 06.03 Dotfiles -> ~/repos/dotfiles) are recognized.
    """
    current = start
    home = Path.home()
    while current != current.parent and current.is_relative_to(home):
        if is_jd_id(current) or is_jd_category(current) or is_jd_area(current) or is_jd_root(current):
            return current
        current = current.parent
    return None


def get_cascade_levels(path: Path, root: Path) -> list[Path]:
    """
    Return the cascade of JD directories from root down to path.
    Each entry is a directory where we should look for context files.

    For a path like 96.05, returns:
      [root, area (90-99), category (96), id (96.05)]

    We collect files from meta dirs for root/area/category, and from
    the ID dir itself for IDs.
    """
    root_resolved = root.resolve()
    chain = []
    current = path
    while True:
        chain.append(current)
        if current.resolve() == root_resolved:
            break
        parent = current.parent
        if parent == current:
            if root not in [c.resolve() for c in chain]:
                chain.append(root)
            break
        current = parent

    chain.reverse()

    # Filter to only JD-relevant levels
    levels = []
    for d in chain:
        if is_jd_root(d) or is_jd_area(d) or is_jd_category(d) or is_jd_id(d):
            levels.append(d)
    return levels


def get_context_dir(level: Path) -> Optional[Path]:
    """
    Get the directory to scan for context files at a given JD level.
    For root/area/category: the meta dir (xx.00).
    For IDs: the ID dir itself.
    """
    if is_jd_id(level):
        return level
    return find_meta_dir(level)

def _is_area_meta_prefix(prefix: str) -> bool:
    """True if prefix is a round area number: 00, 10, 20, ..., 90."""
    try:
        return int(prefix) % 10 == 0
    except ValueError:
        return False


def get_proposals_dir(level: Path) -> Optional[Path]:
    """
    For area-level meta categories, find the sibling xx.02 *Proposals* dir.
    Only recognised for round-numbered prefixes (00, 10, 20, ..., 90).
    """
    context_dir = get_context_dir(level)
    if context_dir is None or not context_dir.is_dir():
        return None
    m = re.match(r'^([0-9]{2})\.00[ .]', context_dir.name)
    if not m or not _is_area_meta_prefix(m.group(1)):
        return None
    prefix = m.group(1)
    parent = context_dir.parent  # the xx.00's parent = area meta category dir
    for child in sorted(parent.iterdir()):
        if (child.is_dir()
                and re.match(rf'^{prefix}\.02', child.name)
                and 'Proposals' in child.name):
            return child
    return None


def get_proposals_entry(
    proposals_dir: Path, root: Path
) -> Optional[tuple]:
    """
    Return a synthetic (None, header, content) tuple listing .md files.
    Returns None if the proposals dir is empty.
    """
    md_files = sorted(
        f.name for f in proposals_dir.iterdir()
        if f.is_file() and f.suffix == '.md'
    )
    if not md_files:
        return None
    try:
        rel = str(proposals_dir.relative_to(root))
    except ValueError:
        rel = proposals_dir.name
    listing = "\n".join(f"  - {f}" for f in md_files)
    content = f"Proposals ({proposals_dir.name}):\n{listing}"
    return (None, rel, content)


def collect_files_at_level(
    context_dir: Path,
    stems: list[str],
    extensions: list[str],
    extra: list[str],
    exclude: list[str],
) -> list[Path]:
    """
    Collect context files from a directory.
    Order: stem > extension (cartesian product), then extra globs.
    """
    if not context_dir or not context_dir.is_dir():
        return []

    found = []
    seen = set()

    # stem × extension cartesian product
    for stem in stems:
        for ext in extensions:
            candidate = context_dir / f"{stem}{ext}"
            if candidate.is_file() and candidate.name not in exclude and candidate not in seen:
                found.append(candidate)
                seen.add(candidate)

    # extra globs (local only)
    for pattern in extra:
        for match in sorted(context_dir.glob(pattern)):
            if match.is_file() and match.name not in exclude and match not in seen:
                found.append(match)
                seen.add(match)

    return found


def build_context(
    path: Path,
    root: Path,
    stems: Optional[list[str]] = None,
    extensions: Optional[list[str]] = None,
    extra: Optional[list[str]] = None,
    exclude: Optional[list[str]] = None,
) -> list[tuple[Path, str]]:
    """
    Build the full cascading context for a JD path.

    Returns a list of (file_path, relative_header) tuples, ordered by
    stem > extension > level (root → id).
    """
    if stems is None:
        stems = DEFAULT_STEMS[:]
    if extensions is None:
        extensions = DEFAULT_EXTENSIONS[:]
    if extra is None:
        extra = []
    if exclude is None:
        exclude = []

    levels = get_cascade_levels(path, root)

    # Collect files per level, preserving level order
    # Key: (stem_index, ext_index) or None for extras
    # We need to group by filename pattern across levels
    level_files: list[list[Path]] = []
    for level in levels:
        context_dir = get_context_dir(level)
        if context_dir is None:
            level_files.append([])
            continue
        files = collect_files_at_level(context_dir, stems, extensions, extra, exclude)
        level_files.append(files)

    # Reorder: stem > extension > level
    # First pass: collect all stem×ext matches in order
    ordered: list[Path] = []
    seen: set[Path] = set()

    for stem in stems:
        for ext in extensions:
            target_name = f"{stem}{ext}"
            for files in level_files:
                for f in files:
                    if f.name == target_name and f not in seen:
                        ordered.append(f)
                        seen.add(f)

    # Second pass: extras (anything not already included)
    for files in level_files:
        for f in files:
            if f not in seen:
                ordered.append(f)
                seen.add(f)

    # Build result with relative headers
    result = []
    for f in ordered:
        try:
            rel = f.relative_to(root)
        except ValueError:
            rel = f.name
        result.append((f, str(rel)))

    # Append proposals listings for area levels (synthetic entries, deduplicated)
    seen_proposals: set[Path] = set()
    for level in levels:
        proposals_dir = get_proposals_dir(level)
        if proposals_dir and proposals_dir not in seen_proposals:
            seen_proposals.add(proposals_dir)
            entry = get_proposals_entry(proposals_dir, root)
            if entry:
                result.append(entry)

    return result


def format_context(files: list[tuple]) -> str:
    """Format collected files into a single string with headers.

    Each entry is either:
      (Path, header)              — real file; content read from disk
      (None, header, content_str) — synthetic entry (e.g. proposals listing)
    """
    sections = []
    for item in files:
        if item[0] is None:
            # Synthetic entry: (None, header, content)
            _, rel_path, content = item
        else:
            file_path, rel_path = item[0], item[1]
            content = file_path.read_text(errors="replace").strip()
        if content:
            sections.append(f"# {rel_path}\n\n{content}")
    return "\n\n---\n\n".join(sections)


def launch_claude(working_dir: Path, context: str) -> Optional[int]:
    """Launch Claude Code with the given context."""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return None

    args = [claude_bin]
    if context:
        args.extend(["--append-system-prompt", context])

    result = subprocess.run(args, cwd=working_dir)
    return result.returncode
