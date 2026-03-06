import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import click

from johnnydecimal import api
from johnnydecimal.completion import JD_ID
from johnnydecimal.policy import resolve_policy, get_convention, get_volumes, get_links, find_root_policy
from johnnydecimal.scope import check_scope
from johnnydecimal.staging import add_jd_tag, remove_jd_tag
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
        meta_name = f"{format_jd_id(next_cat, 0)} {name} - Meta"
        meta_path = new_path / meta_name
        meta_path.mkdir()
        click.echo(f"  + {meta_name}")

        unsorted_name = f"{format_jd_id(next_cat, 1)} {name} - Unsorted"
        unsorted_path = new_path / unsorted_name
        unsorted_path.mkdir()
        click.echo(f"  + {unsorted_name}")


@cli.command()
@click.option("--fix", is_flag=True, help="Auto-fix safe issues (conventions, en-dashes, broken symlinks)")
@click.option("-n", "--dry-run", is_flag=True, help="With --fix: show what would be changed without changing it")
@click.option("--force", is_flag=True, help="With --fix: also fix wrong-target inbound links (delete + recreate)")
def validate(fix, dry_run, force):
    """Validate the JD filing system for consistency issues."""
    if dry_run and not fix:
        click.echo("--dry-run only makes sense with --fix", err=True)
        raise SystemExit(1)
    do_fix = fix and not dry_run
    jd = get_root()
    issues = []
    warnings = []
    fixed = []

    # 0. Fix en-dashes first (renaming areas affects paths used by later checks)
    for area in jd.areas:
        if "–" in area.path.name:
            if fix:
                new_name = area.path.name.replace("–", "-")
                new_path = area.path.parent / new_name
                if do_fix:
                    area.path.rename(new_path)
                    area.path = new_path
                fixed.append(f"STYLE: Renamed {area.path.name}: en-dash → hyphen")
            else:
                warnings.append(
                    f"STYLE: EN-DASH: {area.path.name} uses en-dash instead of hyphen"
                )

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
    #    Distinguish volume symlinks (pointing to /Volumes) from truly broken ones.
    #    Volume symlinks are expected to break when the drive is unmounted — never auto-delete them.
    for broken in jd.broken_symlinks:
        raw_target = str(broken.readlink())
        if raw_target.startswith("/Volumes"):
            # Extract volume name from path like /Volumes/LaCie SSD/...
            vol_name = Path(raw_target).parts[2] if len(Path(raw_target).parts) > 2 else raw_target
            warnings.append(
                f"VOLUME: UNMOUNTED: {broken.name} → {raw_target}\n"
                f"     volume '{vol_name}' is not mounted (this is expected when the drive is disconnected)"
            )
        elif fix:
            if do_fix:
                broken.unlink()
            fixed.append(f"LINK: Removed broken symlink: {broken}")
        else:
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
        warnings.append(f"ORPHAN: {orphan}")

    # 5. Convention: x0 should be "[Area] - Meta"
    for area in jd.areas:
        meta_num = area._number
        meta_cat = jd.find_by_category(meta_num)
        if area._number == 0:
            continue  # 00-09 Meta is the exception
        if meta_cat:
            expected_suffix = " - Meta"
            if not meta_cat.name.endswith(expected_suffix):
                if fix:
                    new_name = f"{meta_num:02d} {area.name} - Meta"
                    new_path = meta_cat.path.parent / new_name
                    if do_fix:
                        meta_cat.path.rename(new_path)
                        meta_cat.path = new_path
                    fixed.append(
                        f"CONVENTION: Renamed {meta_cat.path.name} → {new_name}"
                    )
                else:
                    warnings.append(
                        f"CONVENTION: Category {meta_num:02d} should be "
                        f"\"{area.name} - Meta\" but is \"{meta_cat.name}\"\n"
                        f"     {meta_cat.path}"
                    )
        else:
            warnings.append(
                f"CONVENTION: Area {area} has no meta category ({meta_num:02d})"
            )

    # 6. Convention: xx.00 should exist and be named "[Category] - Meta"
    for area in jd.areas:
        for category in area.categories:
            meta_id = format_jd_id(category.number, 0)
            if category.number == 0:
                continue  # 00 Indices is special — skip
            elif category.number % 10 == 0:
                expected_meta_name = f"{area.name} - Meta"
            else:
                expected_meta_name = f"{category.name} - Meta"
            meta = jd.find_by_id(meta_id)
            if not meta:
                if fix:
                    meta_name = f"{meta_id} {expected_meta_name}"
                    meta_path = category.path / meta_name
                    if do_fix:
                        meta_path.mkdir()
                    fixed.append(f"CONVENTION: Created {meta_path}")
                else:
                    warnings.append(
                        f"CONVENTION: Category {category} missing {meta_id} (category meta)"
                    )
            elif meta.name != expected_meta_name:
                if fix:
                    new_name = f"{meta_id} {expected_meta_name}"
                    new_path = meta.path.parent / new_name
                    if do_fix:
                        meta.path.rename(new_path)
                        meta.path = new_path
                    fixed.append(
                        f"CONVENTION: Renamed {meta.path.name} → {new_name}"
                    )
                else:
                    warnings.append(
                        f"CONVENTION: {meta_id} should be \"{expected_meta_name}\" "
                        f"but is \"{meta.name}\"\n     {meta.path}"
                    )

    # 7. Convention: xx.01 should be "[Category] - Unsorted"
    for area in jd.areas:
        for category in area.categories:
            unsorted_id = format_jd_id(category.number, 1)
            if category.number == 0:
                continue  # 00 Indices is special — skip
            elif category.number % 10 == 0:
                expected_unsorted_name = f"{area.name} - Unsorted"
            else:
                expected_unsorted_name = f"{category.name} - Unsorted"
            unsorted = jd.find_by_id(unsorted_id)
            if unsorted:
                if unsorted.name != expected_unsorted_name:
                    if fix:
                        new_name = f"{unsorted_id} {expected_unsorted_name}"
                        new_path = unsorted.path.parent / new_name
                        if do_fix:
                            unsorted.path.rename(new_path)
                            unsorted.path = new_path
                        fixed.append(
                            f"CONVENTION: Renamed {unsorted.path.name} → {new_name}"
                        )
                    else:
                        warnings.append(
                            f"CONVENTION: {unsorted_id} should be \"{expected_unsorted_name}\" "
                            f"but is \"{unsorted.name}\"\n     {unsorted.path}"
                        )
            else:
                if fix:
                    unsorted_name = f"{unsorted_id} {expected_unsorted_name}"
                    unsorted_path = category.path / unsorted_name
                    if do_fix:
                        unsorted_path.mkdir()
                    fixed.append(f"CONVENTION: Created {unsorted_path}")
                else:
                    warnings.append(
                        f"CONVENTION: Category {category} missing {unsorted_id} {expected_unsorted_name}"
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

    # 8b. Inbound link declarations in policy
    declared_links = get_links(jd.path)
    for jd_id_str, ext_paths in declared_links.items():
        target_obj = jd.find_by_id(jd_id_str)
        if not target_obj:
            warnings.append(
                f"LINK: Inbound link declared for {jd_id_str} but ID not found in tree"
            )
            continue
        for ext in ext_paths:
            ext_expanded = Path(ext).expanduser()
            if ext_expanded.is_symlink():
                actual = ext_expanded.resolve()
                expected = target_obj.path.resolve()
                if actual != expected:
                    if fix and force:
                        if do_fix:
                            ext_expanded.unlink()
                            ext_expanded.symlink_to(target_obj.path)
                        fixed.append(
                            f"LINK: Recreated inbound symlink {ext} → {target_obj.path}"
                        )
                    else:
                        issues.append(
                            f"LINK: WRONG TARGET: {ext} → {actual}\n"
                            f"     expected: {expected}"
                        )
            elif ext_expanded.exists():
                issues.append(
                    f"LINK: NOT A SYMLINK: {ext} exists but is not a symlink to {jd_id_str}"
                )
            else:
                if fix:
                    if do_fix:
                        ext_expanded.parent.mkdir(parents=True, exist_ok=True)
                        ext_expanded.symlink_to(target_obj.path)
                    fixed.append(f"LINK: Created inbound symlink {ext} → {target_obj.path}")
                else:
                    warnings.append(
                        f"LINK: MISSING: {ext} should symlink to {jd_id_str} {target_obj.name}"
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
    volumes = get_volumes(jd.path)
    volume_names = set(volumes.keys())
    for jd_id in jd.all_ids():
        if jd_id.is_file:
            # Check if this is a volume reference (alias file with [Volume Name])
            vol_match = re.match(r"\d{2}\.\d{2} .+ \[(.+)\]$", jd_id.path.name)
            if vol_match:
                ref_name = vol_match.group(1)
                if ref_name in volume_names:
                    warnings.append(
                        f"VOLUME: {jd_id.id_str} {jd_id.name} is an alias for {ref_name}\n"
                        f"     {jd_id.path}\n"
                        f"     (run 'jd volume link' to convert to symlink)"
                    )
                else:
                    warnings.append(
                        f"VOLUME: UNDECLARED: {jd_id.id_str} {jd_id.name} references unknown volume '{ref_name}'\n"
                        f"     {jd_id.path}\n"
                        f"     (add '{ref_name}' to policy.yaml under 'volumes:' to manage it)"
                    )
                continue

            # Check if this is an Apple Notes stub (handled by jd notes validate)
            notes_match = re.match(r"\d{2}\.\d{2} .+ \[Apple Notes\]", jd_id.path.name)
            if notes_match:
                continue

            policy = resolve_policy(jd_id.path.parent, jd.path)
            if not get_convention(policy, "ids_as_files", False):
                issues.append(
                    f"FILE AS ID: {jd_id.id_str} {jd_id.name} is a file, not a directory\n"
                    f"     {jd_id.path}\n"
                    f"     (policy ids_as_files=false)"
                )

    # 11. Git repos inside the tree (iCloud corruption risk)
    #     Skip IDs reached through symlinks (e.g. 92 → ~/Repositories) —
    #     those repos aren't actually in iCloud.
    root_policy = resolve_policy(jd.path, jd.path)
    if get_convention(root_policy, "no_git_repos", True):
        root_real = jd.path.resolve()
        for jd_id in jd.all_ids():
            if jd_id.is_file:
                continue
            # Skip if any ancestor is a symlink (repo lives outside iCloud)
            if jd_id.path.resolve() != jd_id.path and \
               not str(jd_id.path.resolve()).startswith(str(root_real)):
                continue
            git_dir = jd_id.path / ".git"
            if git_dir.exists():
                issues.append(
                    f"GIT REPO: {jd_id.id_str} {jd_id.name} contains a .git directory\n"
                    f"     {jd_id.path}\n"
                    f"     (git repos in iCloud risk corruption — symlink to an external location)"
                )

    # 12. Cross-volume validation — check mounted external drives
    volumes = volumes if volumes else get_volumes(jd.path)
    for vol_name, conf in volumes.items():
        mount = conf["mount"]
        vol_root_suffix = conf["root"]
        if not mount.exists():
            continue  # already reported as VOLUME: UNMOUNTED if symlinked

        tree_root = mount / vol_root_suffix if vol_root_suffix else mount
        if not tree_root.is_dir():
            warnings.append(
                f"VOLUME: Cannot find {tree_root}\n"
                f"     (check the 'root' setting in policy.yaml)"
            )
            continue

        # Use JDSystem directly — volumes may have fewer than 3 areas
        # (the normal api.get_system() requires 3+ areas)
        from johnnydecimal.models import JDSystem
        try:
            vol_jd = JDSystem(tree_root)
        except Exception:
            warnings.append(
                f"VOLUME: Cannot load JD tree on {vol_name} at {tree_root}\n"
                f"     (check the 'root' setting in policy.yaml)"
            )
            continue
        if not vol_jd.areas:
            warnings.append(
                f"VOLUME: No JD areas found on {vol_name} at {tree_root}\n"
                f"     (expected area directories like '80-89 Media')"
            )
            continue

        # 12a. Duplicate IDs within the volume
        for id_str, path1, path2 in vol_jd.find_duplicates():
            issues.append(
                f"[{vol_name}] DUPLICATE ID {id_str}:\n"
                f"     {path1}\n     {path2}"
            )

        # 12b. Mismatched category prefixes on the volume
        for jd_id in vol_jd.all_ids():
            if jd_id.is_mismatched:
                issues.append(
                    f"[{vol_name}] MISMATCHED PREFIX: {jd_id.id_str} is inside category "
                    f"{jd_id.category.number:02d} ({jd_id.category.name})\n"
                    f"     {jd_id.path}"
                )

        # 12c. Orphan directories on the volume
        for orphan in vol_jd.find_orphans():
            parent_cat = orphan.parent.name[:2] if orphan.parent else ""
            if parent_cat == "01":
                continue
            warnings.append(
                f"[{vol_name}] ORPHAN: {orphan.name}\n     {orphan}"
            )

        # 12d. Cross-check: aliases in main tree should match content on the volume
        for jd_id in jd.all_ids():
            if jd_id.path.is_symlink() or jd_id.path.is_dir():
                continue
            m = re.match(r"\d{2}\.\d{2} .+ \[(.+)\]$", jd_id.path.name)
            if m and m.group(1) == vol_name:
                # This alias references this volume — check if the ID exists there
                vol_target = vol_jd.find_by_id(jd_id.id_str)
                if not vol_target:
                    warnings.append(
                        f"[{vol_name}] ALIAS MISMATCH: {jd_id.id_str} {jd_id.name} "
                        f"references this volume but ID not found on drive"
                    )

        # 12e. Cross-check: linked symlinks should resolve to valid IDs on the volume
        for jd_id in jd.all_ids():
            if not jd_id.path.is_symlink():
                continue
            try:
                target = jd_id.path.resolve(strict=True)
                if str(target).startswith(str(mount)):
                    vol_target = vol_jd.find_by_id(jd_id.id_str)
                    if not vol_target:
                        warnings.append(
                            f"[{vol_name}] LINK MISMATCH: {jd_id.id_str} symlinks into "
                            f"{vol_name} but ID not found in volume's JD tree"
                        )
                    elif vol_target.path.resolve() != target:
                        warnings.append(
                            f"[{vol_name}] LINK MISMATCH: {jd_id.id_str} points to {target}\n"
                            f"     but volume's JD tree has {vol_target.path}"
                        )
            except (OSError, FileNotFoundError):
                pass  # broken symlinks already handled in section 3

        click.echo(f"Validated volume: {vol_name} ({tree_root})")

    # Print results
    if fixed:
        header = "=== WOULD FIX ===" if dry_run else "=== FIXED ==="
        click.echo(header)
        for f in fixed:
            click.echo(f)
        click.echo()

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

    if not issues and not warnings and not fixed:
        click.echo("No issues found!")
    else:
        parts = []
        if fixed:
            parts.append(f"{len(fixed)} fixed")
        if issues:
            parts.append(f"{len(issues)} issue(s)")
        if warnings:
            parts.append(f"{len(warnings)} warning(s)")
        click.echo(f"Found {', '.join(parts)}.")


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
        meta_name = f"{meta_id} {category.name} - Meta"
        meta_path = category.path / meta_name
        if not meta_path.exists():
            meta_path.mkdir()
            created.append(meta_name)
        else:
            click.echo(f"  exists: {meta_id}")

    if unsorted:
        if category_num % 10 == 0:
            unsorted_base = category.area.name
        else:
            unsorted_base = category.name
        unsorted_name = f"{format_jd_id(category_num, 1)} {unsorted_base} - Unsorted"
        unsorted_path = category.path / unsorted_name
        if not unsorted_path.exists():
            unsorted_path.mkdir()
            created.append(unsorted_name)
        else:
            click.echo(f"  exists: {unsorted_name}")

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
                meta_name = f"{format_jd_id(category.number, 0)} {category.name} - Meta"
                meta_path = category.path / meta_name
                if not meta_path.exists():
                    to_create.append((meta_path, meta_name))

            if unsorted:
                if category.number % 10 == 0:
                    unsorted_base = area.name
                else:
                    unsorted_base = category.name
                unsorted_name = f"{format_jd_id(category.number, 1)} {unsorted_base} - Unsorted"
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
    from johnnydecimal.policy import find_meta_dir
    meta_dir = find_meta_dir(jd.path)
    if not meta_dir or not meta_dir.exists():
        click.echo("Meta directory (00.00) not found", err=True)
        raise SystemExit(1)

    index_path = meta_dir / "Index.md"
    index_path.write_text("\n".join(lines) + "\n")
    click.echo(f"Generated: {index_path}")

    # Also write jd.json
    json_path = meta_dir / "jd.json"
    json_path.write_text(json.dumps(jd.to_dict(), indent=2) + "\n")
    click.echo(f"Generated: {json_path}")


@cli.group()
def volume():
    """Manage external volumes linked into the JD tree."""
    pass


def _find_volume_references(jd, volumes):
    """
    Find all IDs that are volume references (alias files with [Volume Name] suffix).

    Returns list of (jd_id, volume_name) tuples.
    """
    refs = []
    volume_names = set(volumes.keys())
    for jd_id in jd.all_ids():
        if jd_id.path.is_symlink() or jd_id.path.is_dir():
            continue
        # Check if name matches XX.YY Something [Volume Name]
        m = re.match(r"\d{2}\.\d{2} .+ \[(.+)\]$", jd_id.path.name)
        if m and m.group(1) in volume_names:
            refs.append((jd_id, m.group(1)))
    return refs


@volume.command("list")
def volume_list():
    """Show configured volumes and their mount status."""
    jd = get_root()
    volumes = get_volumes(jd.path)

    if not volumes:
        click.echo("No volumes declared in root policy.yaml.")
        click.echo("Add a 'volumes' key to your root policy file.")
        return

    refs = _find_volume_references(jd, volumes)

    for name, conf in volumes.items():
        mount = conf["mount"]
        mounted = mount.exists()
        status = "mounted" if mounted else "not mounted"
        count = sum(1 for _, vn in refs if vn == name)
        click.echo(f"{name:<20s} {str(mount):<30s} {status:<14s} ({count} IDs)")


@volume.command("link")
@click.option("-n", "--dry-run", is_flag=True, help="Show what would happen without making changes")
def volume_link(dry_run):
    """Replace volume alias files with symlinks to mounted volumes."""
    jd = get_root()
    volumes = get_volumes(jd.path)

    if not volumes:
        click.echo("No volumes declared in root policy.yaml.")
        return

    refs = _find_volume_references(jd, volumes)
    if not refs:
        click.echo("No volume references found.")
        return

    prefix = "(dry run) " if dry_run else ""
    linked = 0
    skipped = 0

    for vol_name, conf in volumes.items():
        mount = conf["mount"]
        vol_root = conf["root"]
        vol_refs = [(jd_id, vn) for jd_id, vn in refs if vn == vol_name]

        if not vol_refs:
            continue

        if not mount.exists():
            click.echo(f"\n{vol_name}: skipped — not mounted ({mount})")
            skipped += len(vol_refs)
            continue

        click.echo(f"\n{vol_name}: ({mount})")
        jd_root = mount / vol_root if vol_root else mount
        try:
            volume_jd = api.get_system(jd_root)
        except Exception as e:
            click.echo(f"  ERROR: Cannot load JD tree at {jd_root}: {e}")
            skipped += len(vol_refs)
            continue

        for jd_id, _ in vol_refs:
            target = volume_jd.find_by_id(jd_id.id_str)
            if not target:
                click.echo(f"  SKIP: {jd_id.id_str} not found on volume")
                skipped += 1
                continue

            # New symlink name: strip the [Volume Name] suffix
            old_name = jd_id.path.name
            new_name = re.sub(r"\s*\[.+\]$", "", old_name)
            symlink_path = jd_id.path.parent / new_name

            click.echo(f"  {old_name}")
            click.echo(f"    → {target.path}")

            if not dry_run:
                jd_id.path.unlink()
                symlink_path.symlink_to(target.path)

            linked += 1

    click.echo(f"\n{prefix}{linked} linked, {skipped} skipped.")


@volume.command("scan")
def volume_scan():
    """Scan the tree for volume references and show their status.

    Reports:
    - Alias files waiting to be linked (per volume)
    - Already-linked symlinks pointing to volume mount paths
    - Broken symlinks that were previously linked
    - Undeclared volume names (aliases referencing unknown volumes)
    """
    jd = get_root()
    volumes = get_volumes(jd.path)
    volume_names = set(volumes.keys())

    aliases = []      # (jd_id, vol_name) — alias files for declared volumes
    linked = []       # (jd_id, vol_name) — symlinks pointing into a volume mount
    broken = []       # (jd_id, target) — broken symlinks that pointed to /Volumes
    undeclared = {}   # vol_name → [jd_id] — aliases for undeclared volume names

    for jd_id in jd.all_ids():
        # Check symlinks: already linked or broken
        if jd_id.path.is_symlink():
            try:
                target = jd_id.path.resolve(strict=True)
                target_str = str(target)
                for vname, conf in volumes.items():
                    if target_str.startswith(str(conf["mount"])):
                        linked.append((jd_id, vname))
                        break
            except (OSError, FileNotFoundError):
                raw_target = jd_id.path.readlink()
                if str(raw_target).startswith("/Volumes"):
                    broken.append((jd_id, raw_target))
            continue

        # Check alias files: [Volume Name] suffix
        if jd_id.path.is_dir():
            continue
        m = re.match(r"\d{2}\.\d{2} .+ \[(.+)\]$", jd_id.path.name)
        if m:
            ref_name = m.group(1)
            if ref_name in volume_names:
                aliases.append((jd_id, ref_name))
            else:
                undeclared.setdefault(ref_name, []).append(jd_id)

    # Group aliases by volume
    alias_by_vol = {}
    for jd_id, vname in aliases:
        alias_by_vol.setdefault(vname, []).append(jd_id)

    linked_by_vol = {}
    for jd_id, vname in linked:
        linked_by_vol.setdefault(vname, []).append(jd_id)

    # Report per declared volume
    for vname, conf in volumes.items():
        mount = conf["mount"]
        mounted = mount.exists()
        status = "mounted" if mounted else "not mounted"
        vol_aliases = alias_by_vol.get(vname, [])
        vol_linked = linked_by_vol.get(vname, [])

        click.echo(f"{vname} ({status})")

        if vol_aliases:
            click.echo(f"  {len(vol_aliases)} alias(es) — waiting to link:")
            for jd_id in vol_aliases:
                click.echo(f"    {jd_id.id_str} {jd_id.name}")
            if mounted:
                click.echo(f"  → run: jd volume link")

        if vol_linked:
            click.echo(f"  {len(vol_linked)} linked:")
            for jd_id in vol_linked:
                click.echo(f"    {jd_id.id_str} {jd_id.name}")

        if not vol_aliases and not vol_linked:
            click.echo(f"  no references")

        click.echo()

    # Broken volume symlinks
    if broken:
        click.echo(f"BROKEN ({len(broken)} symlinks to /Volumes):")
        for jd_id, target in broken:
            click.echo(f"  {jd_id.id_str} {jd_id.name} → {target}")
        click.echo()

    # Undeclared volumes
    if undeclared:
        click.echo(f"UNDECLARED ({len(undeclared)} volume names not in policy):")
        for ref_name, ids in undeclared.items():
            click.echo(f"  [{ref_name}] ({len(ids)} IDs)")
            for jd_id in ids:
                click.echo(f"    {jd_id.id_str} {jd_id.name}")
        click.echo("  → add these to policy.yaml under 'volumes:' to manage them")
        click.echo()

    # Summary
    click.echo(f"Total: {len(aliases)} aliases, {len(linked)} linked, {len(broken)} broken")


def _find_index_dir(jd):
    """Find or create the external drives index directory (00.02)."""
    # Look for an existing 00.02 dir (External drives / similar)
    cat_00 = jd.find_by_category(0)
    if cat_00:
        for jd_id in cat_00.ids:
            if jd_id.sequence == 2:
                return jd_id.path

        # Create 00.02 if it doesn't exist
        new_path = cat_00.path / "00.02 External drives"
        new_path.mkdir(exist_ok=True)
        return new_path

    return None


@volume.command("index")
@click.argument("name", required=False)
def volume_index(name):
    """Generate a tree index for a mounted external volume.

    Saves to 00.02 External drives/Index ({name}).txt.
    Without NAME, indexes all mounted volumes.
    """
    import subprocess

    jd = get_root()
    volumes = get_volumes(jd.path)

    if not volumes:
        click.echo("No volumes declared in root policy.yaml.")
        return

    index_dir = _find_index_dir(jd)
    if not index_dir:
        click.echo("Cannot find or create index directory (00.02).", err=True)
        raise SystemExit(1)

    if name:
        if name not in volumes:
            click.echo(f"Unknown volume: {name}", err=True)
            click.echo(f"Declared volumes: {', '.join(volumes.keys())}")
            raise SystemExit(1)
        targets = {name: volumes[name]}
    else:
        targets = volumes

    for vol_name, conf in targets.items():
        mount = conf["mount"]
        vol_root = conf["root"]

        if not mount.exists():
            click.echo(f"{vol_name}: skipped — not mounted ({mount})")
            continue

        tree_root = mount / vol_root if vol_root else mount
        if not tree_root.exists():
            click.echo(f"{vol_name}: skipped — root path not found ({tree_root})")
            continue

        output_file = index_dir / f"Index ({vol_name}).txt"

        click.echo(f"{vol_name}: indexing {tree_root} ...")
        result = subprocess.run(
            ["tree", "-I", ".DS_Store|.git|__pycache__|.Trash|.Spotlight-V100|.fseventsd",
             str(tree_root)],
            capture_output=True, text=True,
        )

        if result.returncode != 0:
            click.echo(f"  ERROR: tree failed: {result.stderr.strip()}", err=True)
            continue

        output_file.write_text(result.stdout)
        lines = result.stdout.count("\n")
        size_kb = len(result.stdout.encode()) / 1024
        click.echo(f"  → {output_file}")
        click.echo(f"    {lines:,} lines, {size_kb:,.0f} KB")


# ---------------------------------------------------------------------------
# Apple Notes integration
# ---------------------------------------------------------------------------

@cli.group()
def notes():
    """Apple Notes integration — scan, validate, stub, create, open."""
    pass


def _notes_folder_path(jd, jd_id_obj):
    """Build the Notes folder path segments for a JD ID.

    Returns e.g. ["20-29 Projects", "26 Recipes"] for an ID in category 26.
    """
    area = jd_id_obj.category.parent
    return [str(area), str(jd_id_obj.category)]


def _notes_id_display(jd_id_obj):
    """Human-readable note name: '26.05 Sourdough'."""
    return str(jd_id_obj)


@notes.command("scan")
def notes_scan():
    """Scan Apple Notes for JD-matching folders and compare against policy.

    Reports three buckets:
      - Declared + found (in policy and exists in Notes)
      - Declared + missing (in policy but not in Notes)
      - Undeclared matches (in Notes with JD naming but not in policy)
    """
    from johnnydecimal.notes import build_tree, NotesError
    from johnnydecimal.policy import get_notes_declarations

    jd = get_root()
    declarations = get_notes_declarations(jd.path)

    if not declarations:
        click.echo("No notes declarations in root policy.yaml.")
        click.echo("Add a 'notes:' section to declare Notes-backed IDs.")
        return

    try:
        tree = build_tree()
    except NotesError as exc:
        click.echo(f"ERROR: Could not read Apple Notes: {exc}", err=True)
        raise SystemExit(1)

    declared_found = []
    declared_missing = []
    undeclared = []

    # Check declared IDs
    for cat_str, ids in declarations.items():
        cat_num = int(cat_str)
        cat = jd.find_by_category(cat_num)
        if not cat:
            click.echo(f"WARNING: Declared category {cat_str} not found in JD tree.", err=True)
            continue

        area = cat.parent
        area_name = str(area)
        cat_name = str(cat)

        # Check if area folder exists in Notes
        area_tree = tree.get(area_name, {})
        cat_tree = area_tree.get("folders", {}).get(cat_name, {})

        if ids == "all":
            # All IDs in this category should be in Notes
            for jd_id in cat.ids:
                note_name = _notes_id_display(jd_id)
                notes_list = cat_tree.get("notes", [])
                if note_name in notes_list:
                    declared_found.append(f"{jd_id.id_str} {jd_id.name}")
                else:
                    declared_missing.append(f"{jd_id.id_str} {jd_id.name}")
        else:
            for id_str in ids:
                jd_id = jd.find_by_id(str(id_str))
                if not jd_id:
                    declared_missing.append(f"{id_str} (ID not found in tree)")
                    continue
                note_name = _notes_id_display(jd_id)
                notes_list = cat_tree.get("notes", [])
                if note_name in notes_list:
                    declared_found.append(f"{jd_id.id_str} {jd_id.name}")
                else:
                    declared_missing.append(f"{jd_id.id_str} {jd_id.name}")

    # Scan Notes for undeclared JD matches
    for area_name, area_data in tree.items():
        area_match = re.match(r"(\d{2})[-–](\d{2}) ", area_name)
        if not area_match:
            continue
        for cat_name, cat_data in area_data.get("folders", {}).items():
            cat_match = re.match(r"(\d{2}) ", cat_name)
            if not cat_match:
                continue
            cat_str = cat_match.group(1)
            for note_name in cat_data.get("notes", []):
                id_match = re.match(r"(\d{2}\.\d{2})", note_name)
                if not id_match:
                    continue
                id_str = id_match.group(1)
                # Skip if declared
                if cat_str in declarations:
                    val = declarations[cat_str]
                    if val == "all" or id_str in val:
                        continue
                undeclared.append(f"{id_str} {note_name}  (in {area_name} > {cat_name})")

    # Report
    if declared_found:
        click.echo(f"\nDeclared + found ({len(declared_found)}):")
        for item in sorted(declared_found):
            click.echo(f"  ✓ {item}")

    if declared_missing:
        click.echo(f"\nDeclared + missing ({len(declared_missing)}):")
        for item in sorted(declared_missing):
            click.echo(f"  ✗ {item}")

    if undeclared:
        click.echo(f"\nUndeclared matches ({len(undeclared)}):")
        for item in sorted(undeclared):
            click.echo(f"  ? {item}")

    if not declared_found and not declared_missing and not undeclared:
        click.echo("No matches found.")


@notes.command("validate")
def notes_validate():
    """Check consistency between Notes stubs, Apple Notes, and policy.

    Validates for declared Notes-backed IDs:
      - Stub file exists in filesystem ↔ note exists in Notes
      - Stub YAML path matches actual Notes location
      - No duplicate IDs (same ID as directory AND in Notes)
    """
    from johnnydecimal.notes import note_exists, folder_exists, NotesError
    from johnnydecimal.policy import get_notes_declarations

    jd = get_root()
    declarations = get_notes_declarations(jd.path)

    if not declarations:
        click.echo("No notes declarations in root policy.yaml.")
        return

    issues = []
    warnings = []

    for cat_str, ids in declarations.items():
        cat_num = int(cat_str)
        cat = jd.find_by_category(cat_num)
        if not cat:
            warnings.append(f"Category {cat_str}: not found in JD tree")
            continue

        area = cat.parent
        area_folder = [str(area)]
        cat_folder = [str(area), str(cat)]

        # Check area + category folders exist in Notes
        try:
            if not folder_exists(area_folder):
                warnings.append(f"Category {cat_str}: area folder '{area}' missing in Notes")
            if not folder_exists(cat_folder):
                warnings.append(f"Category {cat_str}: category folder '{cat}' missing in Notes")
        except NotesError as exc:
            issues.append(f"Category {cat_str}: Notes error: {exc}")
            continue

        # Determine which IDs to check
        if ids == "all":
            id_list = [jd_id.id_str for jd_id in cat.ids]
        else:
            id_list = [str(i) for i in ids]

        for id_str in id_list:
            jd_id = jd.find_by_id(str(id_str))
            if not jd_id:
                warnings.append(f"{id_str}: declared in policy but not found in JD tree")
                continue

            note_name = _notes_id_display(jd_id)

            # Check stub file exists
            stub_pattern = re.compile(
                rf"{re.escape(jd_id.id_str)} .+ \[Apple Notes\]\.(yaml|yml)$"
            )
            stub_files = [
                f for f in jd_id.category.path.iterdir()
                if stub_pattern.match(f.name)
            ]

            # Check note exists in Notes
            try:
                has_note = note_exists(cat_folder, note_name)
            except NotesError:
                has_note = None  # Can't check

            # Check for directory-based ID (conflict)
            if jd_id.path.is_dir():
                issues.append(
                    f"{jd_id.id_str}: exists as directory AND declared as Notes-backed\n"
                    f"     {jd_id.path}"
                )

            if stub_files and has_note is False:
                issues.append(
                    f"{jd_id.id_str}: stub exists but note missing in Notes\n"
                    f"     stub: {stub_files[0].name}"
                )
            elif not stub_files and has_note is True:
                warnings.append(
                    f"{jd_id.id_str}: note exists in Notes but no stub file\n"
                    f"     (run 'jd notes stub {jd_id.id_str}' to create)"
                )

            # Validate stub YAML content if stub exists
            if stub_files:
                import yaml
                try:
                    with open(stub_files[0]) as f:
                        stub_data = yaml.safe_load(f) or {}
                    expected_path = " > ".join(cat_folder + [note_name])
                    actual_path = stub_data.get("path", "")
                    if actual_path != expected_path:
                        warnings.append(
                            f"{jd_id.id_str}: stub path mismatch\n"
                            f"     expected: {expected_path}\n"
                            f"     actual:   {actual_path}"
                        )
                except (yaml.YAMLError, OSError):
                    warnings.append(f"{jd_id.id_str}: could not read stub YAML")

    # Report
    if issues:
        click.echo(f"\nIssues ({len(issues)}):")
        for issue in issues:
            click.echo(f"  ✗ {issue}")
    if warnings:
        click.echo(f"\nWarnings ({len(warnings)}):")
        for warning in warnings:
            click.echo(f"  ! {warning}")
    if not issues and not warnings:
        click.echo("All Notes declarations are consistent.")

    if issues:
        raise SystemExit(1)


@notes.command("stub")
@click.argument("id_str", type=JD_ID)
def notes_stub(id_str):
    """Create a YAML stub file for a Notes-backed ID.

    The stub marks this ID as living in Apple Notes rather than the filesystem.

    \b
    Example:
        jd notes stub 26.05  → creates 26.05 Sourdough [Apple Notes].yaml
    """
    import yaml
    from johnnydecimal.notes import note_exists, NotesError

    jd = get_root()
    jd_id = jd.find_by_id(id_str)
    if not jd_id:
        click.echo(f"ID {id_str} not found in JD tree.", err=True)
        raise SystemExit(1)

    area = jd_id.category.parent
    cat_folder = [str(area), str(jd_id.category)]
    note_name = _notes_id_display(jd_id)
    notes_path = " > ".join(cat_folder + [note_name])

    # Verify note exists in Notes
    try:
        if not note_exists(cat_folder, note_name):
            click.echo(
                f"WARNING: Note '{note_name}' not found in Notes.\n"
                f"  Expected in: {' > '.join(cat_folder)}\n"
                f"  Creating stub anyway."
            )
    except NotesError as exc:
        click.echo(f"WARNING: Could not check Notes: {exc}")

    # Create stub file
    stub_name = f"{jd_id.id_str} {jd_id.name} [Apple Notes].yaml"
    stub_path = jd_id.category.path / stub_name

    if stub_path.exists():
        click.echo(f"Stub already exists: {stub_name}")
        return

    stub_data = {
        "location": "Apple Notes",
        "path": notes_path,
    }
    with open(stub_path, "w") as f:
        yaml.dump(stub_data, f, default_flow_style=False, sort_keys=False)

    click.echo(f"Created: {stub_name}")


@notes.command("create")
@click.argument("id_str", type=JD_ID)
@click.option("--folder", is_flag=True, help="Create a folder instead of a note.")
@click.option("--stub", is_flag=True, help="Also create a filesystem stub.")
def notes_create(id_str, folder, stub):
    """Create a note (or folder) in Apple Notes for a JD ID.

    Ensures area and category folders exist, then creates the note.

    \b
    Examples:
        jd notes create 26.05          → create note "26.05 Sourdough"
        jd notes create 26.05 --stub   → also create stub file
        jd notes create 26.05 --folder → create folder instead of note
    """
    import yaml
    from johnnydecimal.notes import (
        create_folder, create_note, folder_exists, note_exists, NotesError,
    )

    jd = get_root()
    jd_id = jd.find_by_id(id_str)
    if not jd_id:
        click.echo(f"ID {id_str} not found in JD tree.", err=True)
        raise SystemExit(1)

    area = jd_id.category.parent
    area_folder = [str(area)]
    cat_folder = [str(area), str(jd_id.category)]
    note_name = _notes_id_display(jd_id)

    try:
        # Ensure area folder exists
        if not folder_exists(area_folder):
            create_folder(area_folder)
            click.echo(f"Created folder: {area}")

        # Ensure category folder exists
        if not folder_exists(cat_folder):
            create_folder(cat_folder)
            click.echo(f"Created folder: {jd_id.category}")

        if folder:
            # Create subfolder for the ID
            id_folder = cat_folder + [note_name]
            if folder_exists(id_folder):
                click.echo(f"Folder already exists: {note_name}")
            else:
                create_folder(id_folder)
                click.echo(f"Created folder: {note_name}")
        else:
            # Create note
            if note_exists(cat_folder, note_name):
                click.echo(f"Note already exists: {note_name}")
            else:
                create_note(cat_folder, note_name)
                click.echo(f"Created note: {note_name}")
    except NotesError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        raise SystemExit(1)

    # Optionally create stub
    if stub:
        notes_path = " > ".join(cat_folder + [note_name])
        stub_name = f"{jd_id.id_str} {jd_id.name} [Apple Notes].yaml"
        stub_path = jd_id.category.path / stub_name
        if stub_path.exists():
            click.echo(f"Stub already exists: {stub_name}")
        else:
            stub_data = {
                "location": "Apple Notes",
                "path": notes_path,
            }
            with open(stub_path, "w") as f:
                yaml.dump(stub_data, f, default_flow_style=False, sort_keys=False)
            click.echo(f"Created stub: {stub_name}")


@notes.command("open")
@click.argument("id_str", type=JD_ID)
def notes_open(id_str):
    """Open a note in Apple Notes.

    \b
    Example:
        jd notes open 26.05  → opens "26.05 Sourdough" in Notes.app
    """
    from johnnydecimal.notes import open_note, NotesError

    jd = get_root()
    jd_id = jd.find_by_id(id_str)
    if not jd_id:
        click.echo(f"ID {id_str} not found in JD tree.", err=True)
        raise SystemExit(1)

    area = jd_id.category.parent
    cat_folder = [str(area), str(jd_id.category)]
    note_name = _notes_id_display(jd_id)

    try:
        open_note(cat_folder, note_name)
        click.echo(f"Opened: {note_name}")
    except NotesError as exc:
        click.echo(f"ERROR: Could not open note: {exc}", err=True)
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Finder tag management
# ---------------------------------------------------------------------------

@cli.group()
def tag():
    """Manage JD Finder tags."""
    pass


@tag.command("add")
@click.argument("jd_id", type=JD_ID)
@click.argument("path", type=click.Path(exists=True))
def tag_add(jd_id, path):
    """Add a JD Finder tag to a file or folder.

    \b
    Examples:
        jd tag add 26.05 ~/Desktop/recipe.pdf
    """
    jd = get_root()
    found = jd.find_by_id(jd_id)
    if not found:
        click.echo(f"JD ID {jd_id} not found in tree.", err=True)
        raise SystemExit(1)

    target = Path(path)
    add_jd_tag(target, jd_id)
    click.echo(f"Tagged {target.name} with JD:{jd_id}")


@tag.command("remove")
@click.argument("path", type=click.Path(exists=True))
@click.option("--id", "jd_id", type=JD_ID, default=None, help="Remove only this JD tag (default: all).")
def tag_remove(path, jd_id):
    """Remove JD Finder tag(s) from a file or folder.

    \b
    Examples:
        jd tag remove ~/Desktop/recipe.pdf          → remove all JD tags
        jd tag remove --id 26.05 ~/Desktop/recipe.pdf  → remove only JD:26.05
    """
    target = Path(path)
    remove_jd_tag(target, jd_id)
    if jd_id:
        click.echo(f"Removed JD:{jd_id} tag from {target.name}")
    else:
        click.echo(f"Removed all JD tags from {target.name}")


# ---------------------------------------------------------------------------
# OmniFocus integration
# ---------------------------------------------------------------------------

@cli.group()
def omnifocus():
    """OmniFocus integration — scan, validate, open, tag, create."""
    pass


def _omnifocus_check_enabled(jd):
    """Check if OmniFocus integration is enabled. Exits if disabled."""
    from johnnydecimal.policy import is_omnifocus_enabled
    if not is_omnifocus_enabled(jd.path):
        click.echo("OmniFocus integration is disabled (omnifocus: false in root policy.yaml).", err=True)
        raise SystemExit(1)


def _parse_jd_tags(tags: list[str]) -> list[str]:
    """Extract JD IDs from tag names. E.g. ['JD:26.05', 'Work'] -> ['26.05']."""
    import re
    result = []
    for tag in tags:
        m = re.match(r"^JD:(\d{2}(?:\.\d{2})?)$", tag)
        if m:
            result.append(m.group(1))
    return result


@omnifocus.command("scan")
def omnifocus_scan():
    """Compare JD tags in OmniFocus against the JD tree.

    Reports three buckets:
      - Tagged + found (OF project has JD tag, ID exists in JD)
      - Tagged + dead (OF project has JD tag, ID missing from JD)
      - Active IDs without OF project (advisory)
    """
    from johnnydecimal.omnifocus import list_projects_with_jd_tags, OmniFocusError

    jd = get_root()
    _omnifocus_check_enabled(jd)

    try:
        projects = list_projects_with_jd_tags()
    except OmniFocusError as exc:
        click.echo(f"ERROR: Could not read OmniFocus: {exc}", err=True)
        raise SystemExit(1)

    tagged_found = []
    tagged_dead = []

    # Track which JD IDs have OF projects
    of_tracked_ids = set()

    for proj in projects:
        jd_ids = _parse_jd_tags(proj["tags"])
        for jd_id_str in jd_ids:
            jd_id = jd.find_by_id(jd_id_str) if "." in jd_id_str else None
            cat = jd.find_by_category(int(jd_id_str)) if "." not in jd_id_str else None

            if jd_id or cat:
                tagged_found.append(
                    f"{jd_id_str}  ←  {proj['name']}"
                    + (f"  ({proj['folder']})" if proj.get("folder") else "")
                )
                of_tracked_ids.add(jd_id_str)
            else:
                tagged_dead.append(
                    f"{jd_id_str}  ←  {proj['name']} (ID not in JD tree)"
                )

    # Find active JD IDs without OF projects (advisory)
    untracked = []
    for area in jd.areas:
        for cat in area.categories:
            for jd_id in cat.ids:
                if jd_id.sequence in (0, 1, 99):
                    continue
                if jd_id.id_str not in of_tracked_ids:
                    # Only report IDs with actual content
                    if jd_id.path.is_dir():
                        try:
                            items = [i for i in jd_id.path.iterdir() if not i.name.startswith(".")]
                            if items:
                                untracked.append(f"{jd_id.id_str} {jd_id.name}")
                        except PermissionError:
                            pass

    # Report
    if tagged_found:
        click.echo(f"\nTagged + found ({len(tagged_found)}):")
        for item in sorted(tagged_found):
            click.echo(f"  ✓ {item}")

    if tagged_dead:
        click.echo(f"\nTagged + dead ({len(tagged_dead)}):")
        for item in sorted(tagged_dead):
            click.echo(f"  ✗ {item}")

    if untracked:
        click.echo(f"\nActive IDs without OF project ({len(untracked)}):")
        for item in sorted(untracked):
            click.echo(f"  ? {item}")

    if not tagged_found and not tagged_dead and not untracked:
        click.echo("No OmniFocus projects with JD tags found.")


@omnifocus.command("validate")
def omnifocus_validate():
    """Check consistency between OmniFocus and the JD tree.

    Validates:
      1. OF projects with JD tags → does the tagged ID exist?
      2. Active JD IDs → is there an OF project? (advisory)
      3. Orphan OF projects → no JD tag (advisory)
      4. OF folder structure → matches JD areas? (advisory)
    """
    from johnnydecimal.omnifocus import (
        list_projects_with_jd_tags, list_folders, OmniFocusError,
    )

    jd = get_root()
    _omnifocus_check_enabled(jd)

    try:
        projects = list_projects_with_jd_tags()
        of_folders = list_folders()
    except OmniFocusError as exc:
        click.echo(f"ERROR: Could not read OmniFocus: {exc}", err=True)
        raise SystemExit(1)

    issues = []
    warnings = []

    # 1. Check JD tags point to valid IDs
    of_tracked_ids = set()
    for proj in projects:
        jd_ids = _parse_jd_tags(proj["tags"])
        for jd_id_str in jd_ids:
            jd_id = jd.find_by_id(jd_id_str) if "." in jd_id_str else None
            cat = jd.find_by_category(int(jd_id_str)) if "." not in jd_id_str else None
            if jd_id or cat:
                of_tracked_ids.add(jd_id_str)
            else:
                issues.append(f"OF project '{proj['name']}' has tag JD:{jd_id_str} but ID not found in JD tree")

    # 2. Active IDs without OF projects (advisory)
    for area in jd.areas:
        for cat in area.categories:
            for jd_id in cat.ids:
                if jd_id.sequence in (0, 1, 99):
                    continue
                if jd_id.id_str not in of_tracked_ids:
                    if jd_id.path.is_dir():
                        try:
                            items = [i for i in jd_id.path.iterdir() if not i.name.startswith(".")]
                            if items:
                                warnings.append(f"{jd_id.id_str} {jd_id.name}: active ID with no OF project")
                        except PermissionError:
                            pass

    # 3. All OF projects, check for orphans (no JD tag at all)
    try:
        from johnnydecimal.omnifocus import _run_jxa_json
        all_projects_script = """\
var app = Application('OmniFocus');
var doc = app.defaultDocument;
var projects = doc.flattenedProjects();
var result = [];
for (var i = 0; i < projects.length; i++) {
    var p = projects[i];
    if (p.status().toString() === "active status") {
        var tagNames = [];
        var tags = p.tags();
        for (var j = 0; j < tags.length; j++) tagNames.push(tags[j].name());
        var folderName = null;
        try { if (p.parentFolder()) folderName = p.parentFolder().name(); } catch(e) {}
        result.push({name: p.name(), tags: tagNames, folder: folderName});
    }
}
JSON.stringify(result);
"""
        all_active = _run_jxa_json(all_projects_script)
        for proj in all_active:
            jd_ids = _parse_jd_tags(proj["tags"])
            if not jd_ids:
                warnings.append(
                    f"OF project '{proj['name']}' has no JD tag"
                    + (f" (in {proj['folder']})" if proj.get("folder") else "")
                )
    except OmniFocusError:
        pass  # Non-critical

    # 4. OF folder structure vs JD areas (advisory)
    top_folders = {f["name"] for f in of_folders if f["parent_name"] is None}
    for area in jd.areas:
        area_name = area._name
        if not any(area_name.lower() in f.lower() for f in top_folders):
            warnings.append(f"JD area '{area}' has no matching OF top-level folder")

    # Report
    if issues:
        click.echo(f"\nIssues ({len(issues)}):")
        for issue in issues:
            click.echo(f"  ✗ {issue}")
    if warnings:
        click.echo(f"\nWarnings ({len(warnings)}):")
        for warning in warnings:
            click.echo(f"  ! {warning}")
    if not issues and not warnings:
        click.echo("OmniFocus and JD tree are consistent.")

    if issues:
        raise SystemExit(1)


@omnifocus.command("open")
@click.argument("id_str", type=JD_ID)
def omnifocus_open(id_str):
    """Open the OmniFocus project tagged with a JD ID.

    \b
    Example:
        jd omnifocus open 26.05  → opens OF project tagged JD:26.05
    """
    from johnnydecimal.omnifocus import list_projects_with_jd_tags, open_project, OmniFocusError

    jd = get_root()
    _omnifocus_check_enabled(jd)

    try:
        projects = list_projects_with_jd_tags()
    except OmniFocusError as exc:
        click.echo(f"ERROR: Could not read OmniFocus: {exc}", err=True)
        raise SystemExit(1)

    # Find projects tagged with this ID
    tag_name = f"JD:{id_str}"
    matches = [p for p in projects if tag_name in p["tags"]]

    if not matches:
        click.echo(f"No OmniFocus project tagged with {tag_name}.", err=True)
        raise SystemExit(1)

    if len(matches) == 1:
        try:
            open_project(matches[0]["name"])
            click.echo(f"Opened: {matches[0]['name']}")
        except OmniFocusError as exc:
            click.echo(f"ERROR: {exc}", err=True)
            raise SystemExit(1)
    else:
        click.echo(f"Multiple projects tagged {tag_name}:")
        for proj in matches:
            folder = f" ({proj['folder']})" if proj.get("folder") else ""
            click.echo(f"  {proj['name']}{folder}")


@omnifocus.command("tag")
@click.argument("id_str", type=JD_ID)
def omnifocus_tag(id_str):
    """Create a JD:xx.xx tag in OmniFocus for a JD ID.

    \b
    Example:
        jd omnifocus tag 26.05  → creates JD:26.05 tag in OF
    """
    from johnnydecimal.omnifocus import create_tag, OmniFocusError

    jd = get_root()
    _omnifocus_check_enabled(jd)

    # Validate ID exists in JD tree
    jd_id = jd.find_by_id(id_str)
    if not jd_id:
        click.echo(f"ID {id_str} not found in JD tree.", err=True)
        raise SystemExit(1)

    tag_name = f"JD:{id_str}"
    try:
        create_tag(tag_name)
        click.echo(f"Created tag: {tag_name}")
    except OmniFocusError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        raise SystemExit(1)


@omnifocus.command("create")
@click.argument("id_str", type=JD_ID)
@click.option("--folder", "folder_name", default=None, help="Place project in this OF folder.")
def omnifocus_create(id_str, folder_name):
    """Create an OmniFocus project for a JD ID with a JD tag.

    \b
    Examples:
        jd omnifocus create 26.05              → create "26.05 Sourdough" with JD:26.05 tag
        jd omnifocus create 26.05 --folder Recipes  → place in OF folder "Recipes"
    """
    from johnnydecimal.omnifocus import create_tag, create_project, OmniFocusError

    jd = get_root()
    _omnifocus_check_enabled(jd)

    jd_id = jd.find_by_id(id_str)
    if not jd_id:
        click.echo(f"ID {id_str} not found in JD tree.", err=True)
        raise SystemExit(1)

    project_name = str(jd_id)
    tag_name = f"JD:{id_str}"

    try:
        # Ensure tag exists
        create_tag(tag_name)

        # If no folder specified, try to match JD area name against OF folders
        if not folder_name:
            from johnnydecimal.omnifocus import list_folders
            of_folders = list_folders()
            area_name = jd_id.category.parent._name
            for f in of_folders:
                if area_name.lower() in f["name"].lower():
                    folder_name = f["name"]
                    break

        result = create_project(project_name, folder=folder_name, tags=[tag_name])
        click.echo(f"Created project: {project_name}")
        if folder_name:
            click.echo(f"  Folder: {folder_name}")
        click.echo(f"  Tag: {tag_name}")
    except OmniFocusError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        raise SystemExit(1)


@cli.command("mcp")
def mcp_cmd():
    """Start the Johnny Decimal MCP server (stdio transport).

    Configure in Claude settings:

        \b
        {
          "mcpServers": {
            "jd": { "command": "jd", "args": ["mcp"] }
          }
        }
    """
    try:
        from johnnydecimal.mcp_server import run
    except ImportError:
        click.echo("MCP server requires the 'mcp' package.", err=True)
        click.echo("Install with: pip install 'johnnydecimal[mcp]'", err=True)
        raise SystemExit(1)
    run()


@cli.command("symlinks")
@click.option("--check", is_flag=True, help="Exit 1 if any inbound link is missing or wrong.")
@click.option("--fix", is_flag=True, help="Create missing inbound symlinks.")
def symlinks_cmd(check, fix):
    """Show everything that lives outside iCloud via symlinks.

    Lists every symlink in the JD tree grouped by target location,
    with git repo status (remote, clean/dirty) where applicable.

    Also shows declared inbound links (external paths that should
    symlink into the JD tree) from policy.yaml.
    """
    import subprocess

    jd = get_root()
    links = []  # (id_str, name, target_path, is_broken)

    for area in jd.areas:
        # Check area-level symlinks
        if area.path.is_symlink():
            try:
                target = area.path.resolve(strict=True)
                links.append((str(area), area._name, target, False))
            except (OSError, FileNotFoundError):
                links.append((str(area), area._name, area.path.readlink(), True))
            continue

        for category in area.categories:
            if category.path.is_symlink():
                try:
                    target = category.path.resolve(strict=True)
                    links.append((f"{category.number:02d}", category.name, target, False))
                except (OSError, FileNotFoundError):
                    links.append((f"{category.number:02d}", category.name, category.path.readlink(), True))
                continue

            for jd_id in category.ids:
                if jd_id.path.is_symlink():
                    try:
                        target = jd_id.path.resolve(strict=True)
                        links.append((jd_id.id_str, jd_id.name or "(meta)", target, False))
                    except (OSError, FileNotFoundError):
                        links.append((jd_id.id_str, jd_id.name or "(meta)", jd_id.path.readlink(), True))

    if not links:
        click.echo("No symlinks found in the JD tree.")
        return

    # Group by target parent directory
    groups = {}
    for id_str, name, target, is_broken in links:
        if is_broken:
            key = str(target)
        else:
            # Group by top-level location (~/repos, /Volumes/X, etc.)
            parts = Path(target).parts
            if len(parts) >= 3 and parts[1] == "Volumes":
                key = f"/Volumes/{parts[2]}"
            elif len(parts) >= 4 and parts[1] == "Users":
                key = f"~/{parts[3]}"
            else:
                key = str(Path(target).parent)
        groups.setdefault(key, []).append((id_str, name, target, is_broken))

    # Git status helper
    def git_status(path):
        git_dir = Path(path) / ".git"
        if not git_dir.exists():
            return None
        try:
            remote = subprocess.run(
                ["git", "-C", str(path), "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=5,
            )
            has_remote = remote.returncode == 0
            dirty = subprocess.run(
                ["git", "-C", str(path), "status", "--porcelain"],
                capture_output=True, text=True, timeout=5,
            )
            is_dirty = bool(dirty.stdout.strip())
            return {"remote": has_remote, "dirty": is_dirty}
        except Exception:
            return None

    for location, entries in sorted(groups.items()):
        click.echo(f"{location}  ({len(entries)} items)")
        for id_str, name, target, is_broken in entries:
            if is_broken:
                click.echo(f"  {id_str} {name}  →  BROKEN ({target})")
                continue

            suffix = ""
            git = git_status(target)
            if git is not None:
                parts = []
                if git["remote"]:
                    parts.append("has remote")
                else:
                    parts.append("NO REMOTE")
                if git["dirty"]:
                    parts.append("dirty")
                else:
                    parts.append("clean")
                suffix = f"  [{', '.join(parts)}]"

            click.echo(f"  {id_str} {name}  →  {target}{suffix}")
        click.echo()

    # Summary
    broken_count = sum(1 for _, _, _, b in links if b)
    click.echo(f"{len(links)} symlinks total, {len(groups)} locations", nl=False)
    if broken_count:
        click.echo(f", {broken_count} broken")
    else:
        click.echo()

    # --- Inbound links from policy ---
    declared = get_links(jd.path)
    if declared:
        click.echo()
        click.echo("Declared inbound links:")
        has_problem = False
        fixed_links = []

        for jd_id_str, ext_paths in sorted(declared.items()):
            # Resolve the JD ID to a path
            target_obj = jd.find_by_id(jd_id_str)
            if not target_obj:
                click.echo(f"  {jd_id_str} (not found in tree)")
                has_problem = True
                for ext in ext_paths:
                    click.echo(f"    {ext}  →  SKIPPED (ID not found)")
                continue

            click.echo(f"  {jd_id_str} {target_obj.name or '(meta)'}")
            for ext in ext_paths:
                ext_expanded = Path(ext).expanduser()
                if ext_expanded.is_symlink():
                    actual = ext_expanded.resolve()
                    expected = target_obj.path.resolve()
                    if actual == expected:
                        click.echo(f"    {ext}  →  OK")
                    else:
                        click.echo(f"    {ext}  →  WRONG TARGET (points to {actual})")
                        has_problem = True
                elif ext_expanded.exists():
                    click.echo(f"    {ext}  →  EXISTS (not a symlink)")
                    has_problem = True
                else:
                    if fix:
                        ext_expanded.parent.mkdir(parents=True, exist_ok=True)
                        ext_expanded.symlink_to(target_obj.path)
                        click.echo(f"    {ext}  →  CREATED")
                        fixed_links.append(ext)
                    else:
                        click.echo(f"    {ext}  →  MISSING")
                        has_problem = True

        if fixed_links:
            click.echo()
            click.echo(f"Fixed {len(fixed_links)} missing inbound links.")

        if check and has_problem:
            raise SystemExit(1)


@cli.command("ln")
@click.argument("source", type=click.Path())
@click.argument("jd_id", type=JD_ID)
@click.option("--remove", is_flag=True, help="Remove the inbound link instead of creating it.")
def ln_cmd(source, jd_id, remove):
    """Create or remove an inbound symlink and declare it in policy.

    \b
    Creates a symlink at SOURCE pointing into the JD tree at JD_ID,
    and records it in policy.yaml so `jd validate` tracks it.

    \b
    Examples:
        jd ln ~/.ssh 06.05              create symlink + add to policy
        jd ln --remove ~/.ssh 06.05     remove symlink + remove from policy
    """
    import yaml as _yaml

    jd = get_root()

    # Resolve the JD ID
    target_obj = jd.find_by_id(jd_id)
    if not target_obj:
        click.echo(f"JD ID {jd_id} not found.", err=True)
        raise SystemExit(1)

    source_path = Path(source).expanduser()

    if remove:
        # Remove mode: delete symlink + remove from policy
        if source_path.is_symlink():
            source_path.unlink()
            click.echo(f"Removed symlink {source}")
        elif source_path.exists():
            click.echo(f"{source} exists but is not a symlink — not removing.", err=True)
            raise SystemExit(1)
        else:
            click.echo(f"{source} does not exist (already removed).")

        # Remove from policy
        policy_path = find_root_policy(jd.path)
        if policy_path:
            with open(policy_path) as f:
                data = _yaml.safe_load(f) or {}
            links = data.get("links", {})
            # YAML may parse bare JD IDs as floats (e.g. 06.05 → 6.05)
            # Try both string and numeric keys
            key = None
            for k in links:
                if str(k) == jd_id:
                    key = k
                    break
            if key is not None and source in links[key]:
                links[key].remove(source)
                if not links[key]:
                    del links[key]
                if not links:
                    data.pop("links", None)
                _clean_empty_dicts(data)
                with open(policy_path, "w") as f:
                    _yaml.dump(data, f, default_flow_style=False, sort_keys=False)
                click.echo(f"Removed {source} from policy links[{jd_id}]")
            else:
                click.echo(f"{source} not found in policy links for {jd_id}.")
        return

    # Create mode: safety checks
    if source_path.exists() and not source_path.is_symlink():
        click.echo(
            f"{source} exists and is not a symlink.\n"
            f"Move it first, then run this command.",
            err=True,
        )
        raise SystemExit(1)

    if source_path.is_symlink():
        actual = source_path.resolve()
        expected = target_obj.path.resolve()
        if actual == expected:
            click.echo(f"Symlink already correct: {source} → {target_obj.path}")
        else:
            click.echo(
                f"{source} is a symlink but points to {actual}\n"
                f"Expected: {expected}",
                err=True,
            )
            raise SystemExit(1)
    else:
        # Create the symlink
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.symlink_to(target_obj.path)
        click.echo(f"Created symlink {source} → {target_obj.path}")

    # Update policy
    policy_path = find_root_policy(jd.path)
    if not policy_path:
        click.echo("WARNING: No root policy.yaml found — symlink created but not recorded.", err=True)
        return

    with open(policy_path) as f:
        data = _yaml.safe_load(f) or {}

    links = data.setdefault("links", {})
    # Find existing key for this JD ID (handle YAML float parsing)
    key = None
    for k in links:
        if str(k) == jd_id:
            key = k
            break
    if key is None:
        key = jd_id
    if key not in links:
        links[key] = []
    if source not in links[key]:
        links[key].append(source)

    with open(policy_path, "w") as f:
        _yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    click.echo(f"Added {source} to policy links[{jd_id}]")


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


@cli.command("open")
@click.argument("target", type=JD_ID)
def open_cmd(target):
    """Open a JD location in Finder (macOS) or file manager."""
    import subprocess
    import platform

    jd = get_root()

    # Resolve target
    result = jd.find_by_id(target)
    if not result:
        try:
            result = jd.find_by_category(int(target))
        except ValueError:
            pass

    if not result:
        click.echo(f"{target} not found.", err=True)
        raise SystemExit(1)

    path = result.path
    if platform.system() == "Darwin":
        subprocess.run(["open", str(path)])
    elif platform.system() == "Linux":
        subprocess.run(["xdg-open", str(path)])
    else:
        click.echo(str(path))


def _resolve_target(jd, target):
    """Resolve a JD target string to a path.

    Tries in order: dotted ID, area range, category number, area number, name search.
    """
    # Try as dotted ID (e.g. 26.01)
    result = jd.find_by_id(target)
    if result:
        return result.path

    # Try as area range (e.g. "20-29")
    match = re.match(r"^(\d{2})[-–](\d{2})$", target)
    if match:
        num = int(match.group(1))
        for area in jd.areas:
            if area._number == num:
                return area.path

    # Try as category number (e.g. 26)
    try:
        result = jd.find_by_category(int(target))
        if result:
            return result.path
    except ValueError:
        pass

    # Try as area start number (e.g. 20 → 20-29 area) — fallback when no category matches
    try:
        num = int(target)
        for area in jd.areas:
            if area._number == num:
                return area.path
    except ValueError:
        pass

    # Name search (case-insensitive) — matches completion-inserted names
    target_lower = target.lower()
    matches = []
    for area in jd.areas:
        if area._name.lower() == target_lower:
            matches.append(("area", str(area), area.path))
        for category in area.categories:
            if category.name.lower() == target_lower:
                matches.append(("category", str(category), category.path))
            for jd_id in category.ids:
                if jd_id.name and jd_id.name.lower() == target_lower:
                    matches.append(("id", jd_id.id_str, jd_id.path))

    if len(matches) == 1:
        return matches[0][2]
    if len(matches) > 1:
        click.echo("Ambiguous name, matches:", err=True)
        for kind, label, path in matches:
            click.echo(f"  {label}", err=True)
        raise SystemExit(1)

    return None


@cli.command("cd")
@click.argument("target", required=False, type=JD_ID)
@click.option("--setup", is_flag=True, hidden=True,
              help="Print shell wrapper function for jd cd.")
def cd_cmd(target, setup):
    """Print the path to a JD location (use with shell wrapper to cd).

    TARGET can be a JD ID (26.01), category (26), area (20-29), or name (Recipes).

    Shell setup — add to your .zshrc:

        \b
        jd() {
          if [[ "$1" == "cd" ]]; then
            shift
            local target
            target=$(command jd cd "$@")
            if [[ $? -eq 0 && -n "$target" ]]; then
              builtin cd "$target"
            fi
          else
            command jd "$@"
          fi
        }
    """
    if setup:
        click.echo("""\
jd() {
  if [[ "$1" == "cd" ]]; then
    shift
    local target
    target=$(command jd cd "$@")
    if [[ $? -eq 0 && -n "$target" ]]; then
      builtin cd "$target"
    fi
  else
    command jd "$@"
  fi
}""")
        return

    if not target:
        click.echo("Usage: jd cd TARGET", err=True)
        raise SystemExit(1)

    jd = get_root()
    path = _resolve_target(jd, target)

    if not path:
        click.echo(f"{target} not found.", err=True)
        raise SystemExit(1)

    click.echo(str(path))
