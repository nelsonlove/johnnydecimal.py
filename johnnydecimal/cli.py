import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import click

from johnnydecimal import api
from johnnydecimal.completion import JD_ID
from johnnydecimal.policy import resolve_policy, get_convention
from johnnydecimal.scope import check_scope
from johnnydecimal.util import parse_jd_id_string, format_jd_id


def enforce_scope(target: str):
    """Check agent scope and exit if out of bounds."""
    allowed, msg = check_scope(target)
    if not allowed:
        click.echo(f"ERROR: {msg}", err=True)
        raise SystemExit(1)


def get_root():
    """Get the JD root, preferring ~/Documents."""
    docs = Path.home() / "Documents"
    try:
        return api.get_system(docs)
    except Exception:
        return api.get_system(Path.cwd())


@click.group()
def cli():
    """Johnny Decimal CLI — manage your filing system."""
    pass


@cli.command()
@click.argument("category", type=JD_ID, required=False)
@click.option("--all", "show_all", is_flag=True, help="Show the full tree.")
@click.option("--area", "area_num", type=int, default=None, help="Show all categories in an area (0-9).")
def index(category, show_all, area_num):
    """Print the Johnny Decimal index.

    \b
    Examples:
        jd index 26          → category 26 and its IDs
        jd index --area 2    → all of area 20-29
        jd index --all       → full tree
    """
    jd = get_root()

    if not category and not show_all and area_num is None:
        # No args — show usage
        ctx = click.get_current_context()
        click.echo(ctx.get_help())
        return

    filter_cat = int(category) if category else None

    for area in jd.areas:
        # Area filter: --area 2 means 20-29
        if area_num is not None:
            if area._number != area_num * 10:
                continue

        # Category filter
        if filter_cat is not None:
            if not (area._number <= filter_cat <= area._end_number):
                continue

        click.echo(f"{area}")
        for cat in area.categories:
            if filter_cat is not None and cat.number != filter_cat:
                continue

            click.echo(f"  {cat}")
            for jd_id in cat.ids:
                marker = ""
                if jd_id.is_mismatched:
                    marker = " ⚠️  MISMATCHED PREFIX"
                if jd_id.path.is_symlink():
                    target = jd_id.path.resolve()
                    marker += f" → {target}"
                click.echo(f"    {jd_id}{marker}")


@cli.command("which")
@click.argument("id_str", type=JD_ID)
def which_cmd(id_str):
    """Resolve a JD ID (e.g., 26.01) to its filesystem path."""
    jd = get_root()
    result = jd.find_by_id(id_str)
    if result:
        click.echo(result.path)
    else:
        # Try partial match — just category number
        try:
            cat_num = int(id_str)
            cat = jd.find_by_category(cat_num)
            if cat:
                click.echo(cat.path)
            else:
                click.echo(f"Category {id_str} not found.", err=True)
                raise SystemExit(1)
        except ValueError:
            click.echo(f"ID {id_str} not found.", err=True)
            raise SystemExit(1)


@cli.command()
@click.argument("source")
@click.argument("id_str", type=JD_ID)
@click.option("--copy", is_flag=True, help="Copy instead of move.")
def add(source, id_str, copy):
    """Add a file or directory into JD from outside the tree.

    \b
    Examples:
        jd add ~/Downloads/report.pdf 26.01     → moves into 26.01
        jd add ~/Downloads/report.pdf 26.01 --copy  → copies into 26.01
    """
    jd = get_root()
    source_path = Path(source).expanduser().resolve()

    if not source_path.exists():
        click.echo(f"Source not found: {source}", err=True)
        raise SystemExit(1)

    # Check policy
    target = jd.find_by_id(id_str)
    if not target:
        click.echo(f"JD ID {id_str} not found.", err=True)
        raise SystemExit(1)

    policy = resolve_policy(target.path, jd.path)
    if get_convention(policy, "ids_files_only", False):
        if source_path.is_dir():
            click.echo(
                f"Policy ids_files_only=true for {id_str} — cannot add a directory.\n"
                f"Override with: jd policy set conventions.ids_files_only false {id_str}",
                err=True,
            )
            raise SystemExit(1)

    dest = target.path / source_path.name
    if dest.exists():
        click.echo(f"Destination already exists: {dest}", err=True)
        raise SystemExit(1)

    if copy:
        if source_path.is_dir():
            shutil.copytree(str(source_path), str(dest))
        else:
            shutil.copy2(str(source_path), str(dest))
        click.echo(f"Copied: {source_path.name} → {target}")
    else:
        shutil.move(str(source_path), str(dest))
        click.echo(f"Added: {source_path.name} → {target}")


@cli.group()
def new():
    """Create new JD folders (auto-numbered by default)."""
    pass


@new.command("id")
@click.argument("category", type=JD_ID)
@click.argument("name")
@click.option("--at", "explicit_seq", default=None, type=int, help="Explicit sequence number. Default: next available.")
def new_id(category, name, explicit_seq):
    """Create a new ID in a category.

    \b
    Examples:
        jd new id 26 "Mediation"        → 26.25 Mediation (next available)
        jd new id 26 "Special" --at 99  → 26.99 Special
    """
    jd = get_root()
    cat_num = int(category)
    enforce_scope(str(cat_num))
    cat = jd.find_by_category(cat_num)
    if not cat:
        click.echo(f"Category {cat_num} not found.", err=True)
        raise SystemExit(1)

    if explicit_seq is not None:
        seq = explicit_seq
        existing = jd.find_by_id(format_jd_id(cat_num, seq))
        if existing:
            click.echo(f"ID {format_jd_id(cat_num, seq)} already exists: {existing.path}", err=True)
            raise SystemExit(1)
    else:
        seq = cat.next_id()

    new_id_str = format_jd_id(cat_num, seq)

    # Check policy — warn if creating in a reserved slot without matching convention
    if seq == 0 and name.lower() not in ("", "meta"):
        click.echo(f"Note: xx.00 is conventionally category meta.", err=True)
    if seq == 1 and name.lower() != "unsorted":
        click.echo(f"Note: xx.01 is conventionally 'Unsorted'.", err=True)

    folder_name = f"{new_id_str} {name}"
    new_path = cat.path / folder_name
    new_path.mkdir(parents=True)
    click.echo(f"Created: {new_path}")


@new.command("category")
@click.argument("area", type=JD_ID)
@click.argument("name")
@click.option("--at", "explicit_num", default=None, type=int, help="Explicit category number. Default: next available.")
@click.option("--init/--no-init", default=True, help="Also create xx.00 and xx.01.")
def new_category(area, name, explicit_num, init):
    """Create a new category in an area.

    \b
    Examples:
        jd new category 20 "Pets"        → 27 Pets (next available in 20-29)
        jd new category 20 "Pets" --at 28  → 28 Pets
    """
    jd = get_root()
    area_num = int(area)
    enforce_scope(str(area_num))

    target_area = None
    for a in jd.areas:
        if a._number <= area_num <= a._end_number:
            target_area = a
            break

    if not target_area:
        click.echo(f"No area contains number {area_num}.", err=True)
        raise SystemExit(1)

    used_cats = {c.number for c in target_area.categories}

    if explicit_num is not None:
        if explicit_num in used_cats:
            existing = jd.find_by_category(explicit_num)
            click.echo(f"Category {explicit_num} already exists: {existing.path}", err=True)
            raise SystemExit(1)
        if not (target_area._number <= explicit_num <= target_area._end_number):
            click.echo(f"Category {explicit_num} is outside area {target_area}.", err=True)
            raise SystemExit(1)
        next_cat = explicit_num
    else:
        # Skip x0 (meta category) — start from x1
        next_cat = None
        for n in range(target_area._number + 1, target_area._end_number + 1):
            if n not in used_cats:
                next_cat = n
                break
        if next_cat is None:
            click.echo(f"Area {target_area} is full — no available category numbers.", err=True)
            raise SystemExit(1)

    folder_name = f"{next_cat:02d} {name}"
    new_path = target_area.path / folder_name
    new_path.mkdir(parents=True)
    click.echo(f"Created: {new_path}")

    if init:
        meta_path = new_path / format_jd_id(next_cat, 0)
        meta_path.mkdir()
        click.echo(f"  + {format_jd_id(next_cat, 0)}")

        unsorted_path = new_path / f"{format_jd_id(next_cat, 1)} Unsorted"
        unsorted_path.mkdir()
        click.echo(f"  + {format_jd_id(next_cat, 1)} Unsorted")


@cli.command()
def validate():
    """Validate the JD filing system for consistency issues."""
    jd = get_root()
    issues = []
    warnings = []

    # 1. Duplicate IDs
    dupes = jd.find_duplicates()
    for id_str, path1, path2 in dupes:
        issues.append(f"ERROR: DUPLICATE ID {id_str}:\n     {path1}\n     {path2}")

    # 2. Mismatched category prefixes
    for jd_id in jd.all_ids():
        if jd_id.is_mismatched:
            issues.append(
                f"ERROR: MISMATCHED PREFIX: {jd_id.id_str} is inside category "
                f"{jd_id.category.number:02d} ({jd_id.category.name})\n"
                f"     {jd_id.path}"
            )

    # 3. Broken symlinks
    for broken in jd.broken_symlinks:
        warnings.append(f"LINK: BROKEN SYMLINK: {broken}")

    # 4. Orphan directories (skip capture/inbox categories — unfiled items are expected there)
    orphans = jd.find_orphans()
    capture_categories = {"01", "inbox", "capture"}  # category names that tolerate orphans
    for orphan in orphans:
        # Check if this orphan is inside a capture-type category
        parent_cat = orphan.parent.name[:2] if orphan.parent else ""
        parent_name = orphan.parent.name[3:].lower() if orphan.parent else ""
        if parent_cat == "01" or parent_name in capture_categories:
            continue  # expected — these are unfiled captures
        # Skip orphans inside archive dirs (xx.99)
        in_archive = any(re.match(r"\d{2}\.99\b", a.name) for a in orphan.parents)
        if in_archive:
            continue
        warnings.append(f"ORPHAN: ORPHAN: {orphan}")

    # 5. Convention: x0 should be "Meta - [Area]"
    for area in jd.areas:
        meta_num = area._number
        meta_cat = jd.find_by_category(meta_num)
        if area._number == 0:
            continue  # 00-09 Meta is the exception
        if meta_cat:
            expected_prefix = f"Meta - "
            if not meta_cat.name.startswith(expected_prefix):
                warnings.append(
                    f"CONVENTION: CONVENTION: Category {meta_num:02d} should be "
                    f"\"Meta - {area.name}\" but is \"{meta_cat.name}\"\n"
                    f"     {meta_cat.path}"
                )
        else:
            warnings.append(
                f"CONVENTION: CONVENTION: Area {area} has no meta category ({meta_num:02d})"
            )

    # 6. Convention: xx.00 should exist (category meta)
    for area in jd.areas:
        for category in area.categories:
            meta_id = format_jd_id(category.number, 0)
            meta = jd.find_by_id(meta_id)
            if not meta:
                warnings.append(
                    f"CONVENTION: CONVENTION: Category {category} missing {meta_id} (category meta)"
                )

    # 7. Convention: xx.01 should be "Unsorted"
    for area in jd.areas:
        for category in area.categories:
            unsorted_id = format_jd_id(category.number, 1)
            unsorted = jd.find_by_id(unsorted_id)
            if unsorted:
                if unsorted.name != "Unsorted":
                    warnings.append(
                        f"CONVENTION: CONVENTION: {unsorted_id} should be \"Unsorted\" "
                        f"but is \"{unsorted.name}\"\n     {unsorted.path}"
                    )
            else:
                warnings.append(
                    f"CONVENTION: CONVENTION: Category {category} missing {unsorted_id} Unsorted"
                )

    # 8. Symlink declarations in policy
    for area in jd.areas:
        area_policy = resolve_policy(area.path, jd.path)
        declared_symlinks = area_policy.get("symlinks", {})
        for cat_num_str, decl in declared_symlinks.items():
            cat_num = int(cat_num_str)
            cat = jd.find_by_category(cat_num)
            target = Path(decl.get("target", "")).expanduser()
            if cat:
                if cat.path.is_symlink():
                    actual_target = cat.path.resolve()
                    expected_target = target.resolve()
                    if actual_target != expected_target:
                        issues.append(
                            f"LINK: SYMLINK MISMATCH: {cat} points to {actual_target}\n"
                            f"     policy expects: {expected_target}"
                        )
                else:
                    warnings.append(
                        f"LINK: NOT A SYMLINK: {cat} should be symlinked to {target}\n"
                        f"     (declared in {area} policy)"
                    )
            else:
                warnings.append(
                    f"LINK: MISSING: Category {cat_num} declared as symlink to {target} but doesn't exist"
                )

    # 9. IDs containing subdirectories (when policy says files only)
    for jd_id in jd.all_ids():
        if jd_id.is_file:
            continue  # files can't contain subdirs
        policy = resolve_policy(jd_id.path, jd.path)
        if get_convention(policy, "ids_files_only", False):
            subdirs = [d for d in jd_id.path.iterdir() 
                      if d.is_dir() and not d.name.startswith(".")]
            if subdirs:
                dir_names = ", ".join(d.name for d in subdirs[:3])
                if len(subdirs) > 3:
                    dir_names += f" (+{len(subdirs) - 3} more)"
                warnings.append(
                    f"SUBDIRS IN ID: {jd_id.id_str} {jd_id.name} contains "
                    f"directories: {dir_names}\n     {jd_id.path}\n"
                    f"     (policy ids_files_only=true)"
                )

    # 10. File-IDs when policy disallows them
    for jd_id in jd.all_ids():
        if jd_id.is_file:
            policy = resolve_policy(jd_id.path.parent, jd.path)
            if not get_convention(policy, "ids_as_files", False):
                issues.append(
                    f"FILE AS ID: {jd_id.id_str} {jd_id.name} is a file, not a directory\n"
                    f"     {jd_id.path}\n"
                    f"     (policy ids_as_files=false)"
                )

    # 11. En-dash vs hyphen in area names
    for area in jd.areas:
        if "–" in area.path.name:
            warnings.append(
                f"STYLE: EN-DASH: {area.path.name} uses en-dash instead of hyphen"
            )

    # Print results
    if issues:
        click.echo("=== ISSUES (should fix) ===")
        for issue in issues:
            click.echo(issue)
        click.echo()

    if warnings:
        click.echo("=== WARNINGS (consider fixing) ===")
        for warning in warnings:
            click.echo(warning)
        click.echo()

    if not issues and not warnings:
        click.echo("No issues found!")
    else:
        click.echo(f"Found {len(issues)} issue(s) and {len(warnings)} warning(s).")


@cli.command()
@click.argument("query")
@click.option("--archived", is_flag=True, help="Include archived entries (xx.99)")
def search(query, archived):
    """Search for JD entries by name (case-insensitive)."""
    jd = get_root()
    query_lower = query.lower()
    results = []

    for area in jd.areas:
        if query_lower in area.name.lower():
            results.append(("area", str(area), area.path))
        for category in area.categories:
            if query_lower in category.name.lower():
                results.append(("category", str(category), category.path))
            for jd_id in category.ids:
                if not archived and jd_id.sequence == 99:
                    continue
                if query_lower in jd_id.name.lower():
                    results.append(("id", str(jd_id), jd_id.path))

    if results:
        for kind, label, path in results:
            click.echo(f"[{kind:>8}] {label}")
            click.echo(f"           {path}")
    else:
        click.echo(f"No results for '{query}'.")


@cli.command()
def root():
    """Print the root directory of the JD filing system."""
    jd = get_root()
    click.echo(jd.path)


def _ensure_archive_dir(parent_path, cat_num, dry_run=False):
    """Ensure xx.99 Archive dir exists under the given category path. Returns the path."""
    archive_id = f"{cat_num:02d}.99"
    # Look for existing
    for child in parent_path.iterdir():
        if child.is_dir() and child.name.startswith(archive_id):
            return child
    # Create it
    archive_path = parent_path / f"{archive_id} Archive"
    if not dry_run:
        archive_path.mkdir()
    click.echo(f"  Created {archive_path.name}")
    return archive_path


def _do_archive(jd, source, dry_run=False):
    """Archive a JD ID (→ xx.99) or category (→ x0.99)."""
    enforce_scope(source)
    prefix = "(dry run) " if dry_run else ""

    # Try as full ID first
    source_id = jd.find_by_id(source)
    if source_id:
        archive_dir = _ensure_archive_dir(source_id.category.path, source_id.category.number, dry_run)
        dest = archive_dir / source_id.path.name
        if dest.exists():
            click.echo(f"Already exists in archive: {dest}", err=True)
            raise SystemExit(1)
        if not dry_run:
            source_id.path.rename(dest)
        click.echo(f"{prefix}Archived {source_id.path.name} → {archive_dir.name}/")
        return

    # Try as category
    try:
        cat_num = int(source)
    except ValueError:
        click.echo(f"Source {source} not found.", err=True)
        raise SystemExit(1)

    source_cat = jd.find_by_category(cat_num)
    if not source_cat:
        click.echo(f"Category {source} not found.", err=True)
        raise SystemExit(1)

    area = source_cat.parent
    meta_cat_num = area._number
    meta_cat = jd.find_by_category(meta_cat_num)
    if not meta_cat:
        click.echo(f"Area meta category {meta_cat_num} not found. Create it first: jd init {meta_cat_num}", err=True)
        raise SystemExit(1)

    archive_dir = _ensure_archive_dir(meta_cat.path, meta_cat_num, dry_run)
    dest = archive_dir / source_cat.path.name
    if dest.exists():
        click.echo(f"Already exists in archive: {dest}", err=True)
        raise SystemExit(1)
    if not dry_run:
        source_cat.path.rename(dest)
    click.echo(f"{prefix}Archived {source_cat.path.name} → {meta_cat_num:02d}.99 Archive/")


def _count_items(path):
    """Count non-hidden items in a directory."""
    if not path.is_dir():
        return 0
    try:
        return len([i for i in path.iterdir() if not i.name.startswith(".")])
    except PermissionError:
        return 0


def _show_conflict(archived, existing, parent, target_id):
    """Show details about a restore conflict."""
    archived_count = _count_items(archived)
    existing_count = _count_items(existing)
    click.echo(f"Cannot restore — {target_id} already exists.", err=True)
    click.echo(f"  Archived: {archived.name} ({archived_count} items)", err=True)
    click.echo(f"  Current:  {existing.name} ({existing_count} items)", err=True)
    click.echo(f"  Use --renumber to restore to next available number", err=True)


@cli.command()
@click.argument("target", type=JD_ID)
@click.option("-n", "--dry-run", is_flag=True, help="Show what would happen without doing it")
@click.option("--renumber", is_flag=True, help="If original ID is taken, restore to next available")
def restore(target, dry_run, renumber):
    """Restore an archived ID or category.

    \b
    Reverses `jd mv -a`. Finds the item in the appropriate .99 archive
    and moves it back to its original location.

    \b
    Examples:
        jd restore 86.03     → find in 86.99, restore to 86/
        jd restore 21        → find in 20.99, restore to 20-29/
        jd restore --renumber 86.03  → restore as next available if 86.03 taken
    """
    import re as _re

    jd = get_root()
    prefix = "(dry run) " if dry_run else ""

    # Try as ID: look in xx.99 inside the same category
    m = _re.match(r"(\d{2})\.(\d{2})$", target)
    if m:
        cat_num = int(m.group(1))
        cat = jd.find_by_category(cat_num)
        if not cat:
            click.echo(f"Category {cat_num} not found.", err=True)
            raise SystemExit(1)

        enforce_scope(target)

        # Find the archive dir
        archive_dir = None
        for child in cat.path.iterdir():
            if child.is_dir() and child.name.startswith(f"{cat_num:02d}.99"):
                archive_dir = child
                break
        if not archive_dir:
            click.echo(f"No archive ({cat_num:02d}.99) found in {cat}.", err=True)
            raise SystemExit(1)

        # Find the item inside archive
        found = None
        for child in archive_dir.iterdir():
            if child.name.startswith(target):
                found = child
                break
        if not found:
            click.echo(f"{target} not found in {archive_dir.name}.", err=True)
            raise SystemExit(1)

        # Check if the ID number is already taken (even with a different name)
        existing = jd.find_by_id(target)
        dest = cat.path / found.name
        if existing:
            if not renumber:
                _show_conflict(found, existing.path, cat, target)
                raise SystemExit(1)
            # Renumber: assign next available ID, keep name
            new_seq = cat.next_id()
            new_id_str = format_jd_id(cat_num, new_seq)
            name_part = found.name.split(" ", 1)[1] if " " in found.name else ""
            new_name = f"{new_id_str} {name_part}".rstrip()
            dest = cat.path / new_name
            if not dry_run:
                found.rename(dest)
            click.echo(f"{prefix}Restored {found.name} → {new_name} (renumbered)")
        else:
            if not dry_run:
                found.rename(dest)
            click.echo(f"{prefix}Restored {found.name} → {cat}/")

        # Clean up empty archive dir
        if not dry_run and archive_dir.exists():
            remaining = [i for i in archive_dir.iterdir() if not i.name.startswith(".")]
            if not remaining:
                archive_dir.rmdir()
                click.echo(f"  Removed empty {archive_dir.name}")
        return

    # Try as category: look in x0.99
    try:
        cat_num = int(target)
    except ValueError:
        click.echo(f"{target} not found.", err=True)
        raise SystemExit(1)

    enforce_scope(str(cat_num))

    # Find which area this category belongs to
    target_area = None
    for a in jd.areas:
        if a._number <= cat_num <= a._end_number:
            target_area = a
            break
    if not target_area:
        click.echo(f"No area contains category {cat_num}.", err=True)
        raise SystemExit(1)

    meta_cat_num = target_area._number
    meta_cat = jd.find_by_category(meta_cat_num)
    if not meta_cat:
        click.echo(f"Area meta category {meta_cat_num} not found.", err=True)
        raise SystemExit(1)

    # Find archive dir in x0 meta
    archive_dir = None
    for child in meta_cat.path.iterdir():
        if child.is_dir() and child.name.startswith(f"{meta_cat_num:02d}.99"):
            archive_dir = child
            break
    if not archive_dir:
        click.echo(f"No archive ({meta_cat_num:02d}.99) found.", err=True)
        raise SystemExit(1)

    # Find the category inside archive
    cat_prefix = f"{cat_num:02d} "
    found = None
    for child in archive_dir.iterdir():
        if child.name.startswith(cat_prefix):
            found = child
            break
    if not found:
        click.echo(f"Category {cat_num} not found in {archive_dir.name}.", err=True)
        raise SystemExit(1)

    dest = target_area.path / found.name
    if dest.exists():
        if not renumber:
            _show_conflict(found, dest, target_area, str(cat_num))
            raise SystemExit(1)
        # Renumber: find next available category number in this area
        used = {c.number for c in target_area.categories}
        new_num = None
        for i in range(target_area._number + 1, target_area._end_number + 1):
            if i not in used:
                new_num = i
                break
        if new_num is None:
            click.echo(f"No available category numbers in {target_area}.", err=True)
            raise SystemExit(1)
        name_part = found.name.split(" ", 1)[1] if " " in found.name else ""
        new_name = f"{new_num:02d} {name_part}".rstrip()
        dest = target_area.path / new_name
        if not dry_run:
            found.rename(dest)
        click.echo(f"{prefix}Restored {found.name} → {new_name} (renumbered)")
    else:
        if not dry_run:
            found.rename(dest)
        click.echo(f"{prefix}Restored {found.name} → {target_area}/")

    # Clean up empty archive dir
    if not dry_run and archive_dir.exists():
        remaining = [i for i in archive_dir.iterdir() if not i.name.startswith(".")]
        if not remaining:
            archive_dir.rmdir()
            click.echo(f"  Removed empty {archive_dir.name}")


@cli.command()
@click.argument("source", type=JD_ID)
@click.argument("destination", required=False, default=None)
@click.option("-a", "--archive", is_flag=True, help="Archive to xx.99 (ID) or x0.99 (category)")
@click.option("-n", "--dry-run", is_flag=True, help="Show what would happen without doing it")
def mv(source, destination, archive, dry_run):
    """Move, rename, or renumber within JD. Smart about what you mean.

    \b
    Examples:
        jd mv 26.01 22.01        → renumber (both are JD IDs)
        jd mv 26.01 22           → refile to category 22, next available ID
        jd mv 26.01 "New name"   → rename (keeps number)
        jd mv 26 "New name"      → rename category
        jd mv -a 86.03           → archive to 86.99 Archive/
        jd mv -a 21              → archive to 20.99 Archive/
    """
    jd = get_root()

    if archive:
        if destination:
            click.echo("--archive doesn't take a destination.", err=True)
            raise SystemExit(1)
        _do_archive(jd, source, dry_run)
        return

    if not destination:
        click.echo("Missing destination. Use --archive or provide a destination.", err=True)
        raise SystemExit(1)

    # Resolve source — try as ID, then category
    source_id = jd.find_by_id(source)
    source_cat = None
    if not source_id:
        try:
            source_cat = jd.find_by_category(int(source))
        except ValueError:
            pass

    if not source_id and not source_cat:
        click.echo(f"Source {source} not found.", err=True)
        raise SystemExit(1)

    # Scope check — enforce on source (and destination will be checked below)
    enforce_scope(source)

    # Determine intent from destination
    dest_is_jd_id = False
    dest_is_cat_num = False
    try:
        parse_jd_id_string(destination)
        dest_is_jd_id = True
    except ValueError:
        try:
            dest_num = int(destination)
            dest_is_cat_num = True
        except ValueError:
            pass

    if dest_is_jd_id:
        # RENUMBER: jd mv 26.01 22.01
        enforce_scope(destination)
        if not source_id:
            click.echo("Cannot renumber a category to an ID.", err=True)
            raise SystemExit(1)

        existing = jd.find_by_id(destination)
        if existing:
            click.echo(f"ID {destination} already exists: {existing.path}", err=True)
            raise SystemExit(1)

        new_cat_num, new_seq = parse_jd_id_string(destination)
        target_cat = jd.find_by_category(new_cat_num)
        if not target_cat:
            click.echo(f"Target category {new_cat_num} not found.", err=True)
            raise SystemExit(1)

        name_part = source_id.name if source_id.name else ""
        new_dir_name = f"{format_jd_id(new_cat_num, new_seq)} {name_part}".rstrip()
        prefix = "(dry run) " if dry_run else ""
        new_path = target_cat.path / new_dir_name
        old_path = source_id.path
        if not dry_run:
            old_path.rename(new_path)
        click.echo(f"{prefix}{old_path.name} → {new_dir_name}")
        if source_id.category.number != new_cat_num:
            click.echo(f"  (moved from {source_id.category} to {target_cat})")

    elif dest_is_cat_num:
        # REFILE: jd mv 26.01 22 → move to category 22, next available ID
        enforce_scope(str(dest_num))
        if not source_id:
            click.echo("Cannot refile a category into another category.", err=True)
            raise SystemExit(1)

        target_cat = jd.find_by_category(dest_num)
        if not target_cat:
            click.echo(f"Category {dest_num} not found.", err=True)
            raise SystemExit(1)

        prefix = "(dry run) " if dry_run else ""
        new_seq = target_cat.next_id()
        new_id_str = format_jd_id(dest_num, new_seq)
        name_part = source_id.name if source_id.name else ""
        new_dir_name = f"{new_id_str} {name_part}".rstrip()
        new_path = target_cat.path / new_dir_name
        old_path = source_id.path
        if not dry_run:
            old_path.rename(new_path)
        click.echo(f"{prefix}{old_path.name} → {new_dir_name}")
        click.echo(f"  (moved from {source_id.category} to {target_cat})")

    else:
        # RENAME: jd mv 26.01 "New name" or jd mv 26 "New name"
        if source_id:
            new_dir_name = f"{source_id.id_str} {destination}"
            target = source_id
        elif source_cat:
            new_dir_name = f"{source_cat.number:02d} {destination}"
            target = source_cat
        else:
            click.echo(f"Source {source} not found.", err=True)
            raise SystemExit(1)

        new_path = target.path.parent / new_dir_name
        if new_path.exists():
            click.echo(f"Destination already exists: {new_path}", err=True)
            raise SystemExit(1)

        prefix = "(dry run) " if dry_run else ""
        old_path = target.path
        if not dry_run:
            old_path.rename(new_path)
        click.echo(f"{prefix}{old_path.name} → {new_dir_name}")


@cli.command()
@click.argument("category_num", type=JD_ID)
@click.option("--meta/--no-meta", default=True, help="Create xx.00 meta dir")
@click.option("--unsorted/--no-unsorted", default=True, help="Create xx.01 Unsorted dir")
def init(category_num, meta, unsorted):
    """Bootstrap a category with xx.00 (meta) and xx.01 (Unsorted)."""
    jd = get_root()
    category_num = int(category_num)
    enforce_scope(str(category_num))
    category = jd.find_by_category(category_num)
    if not category:
        click.echo(f"Category {category_num} not found.", err=True)
        raise SystemExit(1)

    created = []

    if meta:
        meta_id = format_jd_id(category_num, 0)
        meta_path = category.path / meta_id
        if not meta_path.exists():
            meta_path.mkdir()
            created.append(meta_id)
        else:
            click.echo(f"  exists: {meta_id}")

    if unsorted:
        unsorted_id = f"{format_jd_id(category_num, 1)} Unsorted"
        unsorted_path = category.path / unsorted_id
        if not unsorted_path.exists():
            unsorted_path.mkdir()
            created.append(unsorted_id)
        else:
            click.echo(f"  exists: {unsorted_id}")

    if created:
        for c in created:
            click.echo(f"  created: {category.path / c}")
    else:
        click.echo(f"Category {category_num:02d} already bootstrapped.")


@cli.command("init-all")
@click.option("--meta/--no-meta", default=True)
@click.option("--unsorted/--no-unsorted", default=True)
@click.option("--dry-run", is_flag=True, help="Show what would be created")
def init_all(meta, unsorted, dry_run):
    """Bootstrap all categories with xx.00 and xx.01."""
    jd = get_root()
    total_created = 0

    for area in jd.areas:
        for category in area.categories:
            to_create = []

            if meta:
                meta_id = format_jd_id(category.number, 0)
                meta_path = category.path / meta_id
                if not meta_path.exists():
                    to_create.append((meta_path, meta_id))

            if unsorted:
                unsorted_name = f"{format_jd_id(category.number, 1)} Unsorted"
                unsorted_path = category.path / unsorted_name
                if not unsorted_path.exists():
                    to_create.append((unsorted_path, unsorted_name))

            if to_create:
                click.echo(f"{category}")
                for path, name in to_create:
                    if dry_run:
                        click.echo(f"  would create: {name}")
                    else:
                        path.mkdir()
                        click.echo(f"  created: {name}")
                    total_created += 1

    if dry_run:
        click.echo(f"\nWould create {total_created} directories.")
    else:
        click.echo(f"\nCreated {total_created} directories.")


@cli.group()
def policy():
    """Manage .johnnydecimal.yaml policy files."""
    pass


def _resolve_jd_path(jd, id_or_path):
    """Resolve a JD ID, category number, or path to a filesystem path."""
    if not id_or_path:
        return jd.path
    target = jd.find_by_id(id_or_path)
    if target:
        return target.path
    try:
        cat_num = int(id_or_path)
        cat = jd.find_by_category(cat_num)
        if cat:
            return cat.path
    except ValueError:
        pass
    p = Path(id_or_path).resolve()
    if p.exists():
        return p
    click.echo(f"Not found: {id_or_path}", err=True)
    raise SystemExit(1)


@policy.command("show")
@click.argument("id_or_path", type=JD_ID, required=False)
@click.option("--resolved/--local", default=True, help="Show resolved (cascaded) or local-only policy")
def policy_show(id_or_path, resolved):
    """Show policy for a path or JD ID. Default: resolved (cascaded)."""
    import yaml as _yaml
    from johnnydecimal.policy import load_policy_file

    jd = get_root()
    path = _resolve_jd_path(jd, id_or_path)

    if resolved:
        result = resolve_policy(path, jd.path)
        click.echo(f"# Resolved policy for: {path}")
    else:
        result = load_policy_file(path)
        if result is None:
            click.echo(f"No .johnnydecimal.yaml at {path}")
            return
        click.echo(f"# Local policy at: {path}")

    click.echo(_yaml.dump(result, default_flow_style=False, sort_keys=False))


@policy.command("get")
@click.argument("key")
@click.argument("id_or_path", type=JD_ID, required=False)
def policy_get(key, id_or_path):
    """Get a single policy value. Use dot notation: symlinks.92.target, conventions.ids_files_only"""
    jd = get_root()
    path = _resolve_jd_path(jd, id_or_path)
    resolved = resolve_policy(path, jd.path)

    # Navigate dot-separated key through full resolved dict
    value = resolved
    for part in key.split("."):
        if isinstance(value, dict):
            # Try string key first, then int (YAML parses bare numbers as int)
            if part in value:
                value = value[part]
            else:
                try:
                    int_key = int(part)
                    if int_key in value:
                        value = value[int_key]
                    else:
                        value = None
                        break
                except ValueError:
                    value = None
                    break
        else:
            value = None
            break

    if value is None:
        click.echo(f"(not set)", err=True)
        raise SystemExit(1)
    else:
        click.echo(value)


@policy.command("set")
@click.argument("key")
@click.argument("value")
@click.argument("id_or_path", type=JD_ID, required=False)
def policy_set(key, value, id_or_path):
    """Set a policy value at a specific level. Writes to policy.yaml in the meta dir.

    Examples:
        jd policy set conventions.ids_files_only true 80
        jd policy set conventions.naming.separator "-" 26.01
    """
    import yaml as _yaml
    from johnnydecimal.policy import find_meta_dir, POLICY_FILENAME

    jd = get_root()
    path = _resolve_jd_path(jd, id_or_path)
    meta = find_meta_dir(path)
    if not meta:
        click.echo(f"No meta dir (xx.00) found for {path}. Run: jd init <category>", err=True)
        raise SystemExit(1)
    policy_path = meta / POLICY_FILENAME

    # Load existing or start fresh
    existing = load_policy_file(path) or {}

    # Parse value
    parsed = _parse_value(value)

    # Set nested key
    parts = key.split(".")
    current = existing
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = parsed

    # Write
    with open(policy_path, "w") as f:
        _yaml.dump(existing, f, default_flow_style=False, sort_keys=False)

    click.echo(f"Set {key}={parsed} at {policy_path}")


@policy.command("unset")
@click.argument("key")
@click.argument("id_or_path", type=JD_ID, required=False)
def policy_unset(key, id_or_path):
    """Remove a policy key at a specific level (inherits from parent)."""
    import yaml as _yaml
    from johnnydecimal.policy import find_meta_dir, load_policy_file, POLICY_FILENAME

    jd = get_root()
    path = _resolve_jd_path(jd, id_or_path)
    meta = find_meta_dir(path)
    if not meta:
        click.echo(f"No meta dir (xx.00) found for {path}.", err=True)
        raise SystemExit(1)
    policy_path = meta / POLICY_FILENAME

    existing = load_policy_file(path)
    if not existing:
        click.echo(f"No policy file at {path}", err=True)
        raise SystemExit(1)

    # Remove nested key
    parts = key.split(".")
    current = existing
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            click.echo(f"Key {key} not found in local policy.", err=True)
            raise SystemExit(1)
        current = current[part]

    if parts[-1] not in current:
        click.echo(f"Key {key} not found in local policy.", err=True)
        raise SystemExit(1)

    del current[parts[-1]]

    # Clean up empty parent dicts
    _clean_empty_dicts(existing)

    if existing:
        with open(policy_path, "w") as f:
            _yaml.dump(existing, f, default_flow_style=False, sort_keys=False)
        click.echo(f"Removed {key} from {policy_path}")
    else:
        policy_path.unlink()
        click.echo(f"Removed {key} — policy file was empty, deleted {policy_path}")


@policy.command("where")
@click.argument("id_or_path", type=JD_ID, required=False)
def policy_where(id_or_path):
    """Show which policy.yaml files affect a path."""
    from johnnydecimal.policy import find_meta_dir, POLICY_FILENAME

    jd = get_root()
    path = _resolve_jd_path(jd, id_or_path)

    # Walk from path up to root, checking for meta dirs with policy files
    chain = []
    current = path
    root_resolved = jd.path.resolve()
    while True:
        chain.append(current)
        if current.resolve() == root_resolved:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    chain.reverse()

    found = False
    for dir_path in chain:
        meta = find_meta_dir(dir_path)
        if meta:
            policy_file = meta / POLICY_FILENAME
            if policy_file.exists():
                click.echo(f"  ✓ {meta.name}/{POLICY_FILENAME}  ({dir_path.name})")
                found = True
                continue
        click.echo(f"    {dir_path.name}/")

    if not found:
        click.echo("\nNo policy files found — using defaults only.")


def _parse_value(value_str: str):
    """Parse a string value into appropriate Python type."""
    if value_str.lower() == "true":
        return True
    if value_str.lower() == "false":
        return False
    if value_str.lower() == "null" or value_str.lower() == "none":
        return None
    try:
        return int(value_str)
    except ValueError:
        pass
    try:
        return float(value_str)
    except ValueError:
        pass
    # Strip quotes if present
    if (value_str.startswith('"') and value_str.endswith('"')) or \
       (value_str.startswith("'") and value_str.endswith("'")):
        return value_str[1:-1]
    return value_str


def _clean_empty_dicts(d: dict):
    """Remove empty nested dicts recursively."""
    keys_to_remove = []
    for key, value in d.items():
        if isinstance(value, dict):
            _clean_empty_dicts(value)
            if not value:
                keys_to_remove.append(key)
    for key in keys_to_remove:
        del d[key]


@cli.command("json")
def json_cmd():
    """Output the full index as JSON (for agent consumption)."""
    jd = get_root()
    click.echo(json.dumps(jd.to_dict(), indent=2))


@cli.command("generate-index")
def generate_index():
    """Regenerate 00.00 Index.md from the filesystem."""
    jd = get_root()
    lines = []
    lines.append("# Johnny.Decimal Master Index")
    lines.append(f"\n> **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> **Root:** `{jd.path}`")
    lines.append("")

    # Broken symlinks
    if jd.broken_symlinks:
        lines.append("## ⚠️ Broken Symlinks")
        for s in jd.broken_symlinks:
            lines.append(f"- `{s}`")
        lines.append("")

    # Tree
    lines.append("## Index")
    lines.append("")
    for area in jd.areas:
        lines.append(f"### {area}")
        for category in area.categories:
            lines.append(f"- **{category}**")
            for jd_id in category.ids:
                marker = ""
                if jd_id.is_mismatched:
                    marker = " ⚠️ MISMATCHED"
                if jd_id.path.is_symlink():
                    marker += " (symlink)"
                lines.append(f"  - {jd_id}{marker}")
        lines.append("")

    # Write to 00.00 Index.md
    index_path = jd.path / "00-09 Meta" / "00 Indices" / "00.00 Index.md"
    if not index_path.parent.exists():
        click.echo(f"Index directory not found: {index_path.parent}", err=True)
        raise SystemExit(1)

    index_path.write_text("\n".join(lines) + "\n")
    click.echo(f"Generated: {index_path}")

    # Also write jd.json
    json_path = index_path.parent / "jd.json"
    json_path.write_text(json.dumps(jd.to_dict(), indent=2) + "\n")
    click.echo(f"Generated: {json_path}")


if __name__ == "__main__":
    cli()


@cli.command()
@click.option("-n", "--top", default=10, help="Number of results to show")
@click.option("--all", "show_all", is_flag=True, help="Show all, not just top N")
def triage(top, show_all):
    """Show where attention is needed most — busiest unsorted dirs, emptiest categories."""
    jd = get_root()

    unsorted_counts = []
    empty_cats = []
    file_id_counts = []

    for area in jd.areas:
        for category in area.categories:
            # Count items in xx.01 Unsorted
            unsorted = None
            for jd_id in category.ids:
                if jd_id.sequence == 1:
                    unsorted = jd_id
                    break
            if unsorted and unsorted.path.is_dir():
                try:
                    items = [i for i in unsorted.path.iterdir() if not i.name.startswith(".")]
                    if items:
                        unsorted_counts.append((len(items), category, unsorted))
                except PermissionError:
                    pass

            # Empty categories (only have .00 and/or .01, nothing else)
            real_ids = [i for i in category.ids if i.sequence not in (0, 1, 99)]
            if not real_ids:
                empty_cats.append(category)

            # File-IDs that should probably be dirs
            for jd_id in category.ids:
                if jd_id.is_file:
                    file_id_counts.append((category, jd_id))

    # Sort unsorted by count descending
    unsorted_counts.sort(key=lambda x: x[0], reverse=True)

    if unsorted_counts:
        click.echo("BUSIEST UNSORTED (items needing filing):")
        shown = unsorted_counts if show_all else unsorted_counts[:top]
        for count, cat, unsorted_id in shown:
            click.echo(f"  {count:4d}  {cat} ({unsorted_id.id_str})")
        if not show_all and len(unsorted_counts) > top:
            click.echo(f"  ... and {len(unsorted_counts) - top} more (use --all)")
        click.echo()

    if file_id_counts:
        click.echo(f"FILE-IDS ({len(file_id_counts)} files acting as IDs):")
        shown = file_id_counts if show_all else file_id_counts[:top]
        for cat, jd_id in shown:
            click.echo(f"       {jd_id.id_str} {jd_id.name}  ({cat.name})")
        if not show_all and len(file_id_counts) > top:
            click.echo(f"  ... and {len(file_id_counts) - top} more")
        click.echo()

    if empty_cats:
        click.echo(f"EMPTY CATEGORIES ({len(empty_cats)} with no real content):")
        shown = empty_cats if show_all else empty_cats[:top]
        for cat in shown:
            click.echo(f"       {cat}")
        if not show_all and len(empty_cats) > top:
            click.echo(f"  ... and {len(empty_cats) - top} more")
        click.echo()

    total_unsorted = sum(c for c, _, _ in unsorted_counts)
    click.echo(f"Total: {total_unsorted} unsorted items across {len(unsorted_counts)} categories")


@cli.command("ls")
@click.argument("target", type=JD_ID, required=False, default=None)
@click.option("-a", "--area", type=int, help="List entire area by leading digit (e.g., 2 for 20-29)")
@click.option("-L", "--level", type=int, default=None, help="Max depth (like tree -L)")
@click.option("-d", "--dirs-only", is_flag=True, help="Only show directories")
@click.pass_context
def ls_cmd(ctx, target, area, level, dirs_only):
    """List contents of JD locations using tree.

    \b
    Examples:
        jd ls                → list all areas
        jd ls 26             → tree of category 26
        jd ls 26.01          → tree of 26.01
        jd ls --area 2       → tree of 20-29
        jd ls -L 1 26        → one level deep
    """
    import subprocess

    jd = get_root()

    # Resolve target to one or more paths
    paths = []

    if area is not None:
        for a in jd.areas:
            if a._number // 10 == area:
                paths.append(a.path)
                break
        if not paths:
            click.echo(f"No area matching digit {area}.", err=True)
            raise SystemExit(1)

    elif target is None:
        # No target: list areas as a summary (no tree)
        for a in jd.areas:
            cat_count = len(a.categories)
            id_count = sum(len(c.ids) for c in a.categories)
            click.echo(f"{a}  ({cat_count} categories, {id_count} IDs)")
        return

    else:
        # Try as ID
        jd_id = jd.find_by_id(target)
        if jd_id:
            paths.append(jd_id.path)
        else:
            # Try as category
            try:
                cat = jd.find_by_category(int(target))
                if cat:
                    paths.append(cat.path)
            except ValueError:
                pass

        if not paths:
            click.echo(f"{target} not found.", err=True)
            raise SystemExit(1)

    # Build tree command
    if shutil.which("tree") is None:
        # Fallback: plain ls -R
        for p in paths:
            click.echo(str(p))
            ls_cmd = ["ls", "-R"]
            if dirs_only:
                ls_cmd += ["-d"]
            ls_cmd.append(str(p))
            subprocess.run(ls_cmd)
        return

    cmd = ["tree", "-I", ".DS_Store|.git|__pycache__|.Trash"]
    if level is not None:
        cmd += ["-L", str(level)]
    if dirs_only:
        cmd += ["-d"]
    cmd += [str(p) for p in paths]

    subprocess.run(cmd)
