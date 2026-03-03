"""MCP server for Johnny Decimal — exposes the JD filing system as structured tools."""

import json
import re
import shutil
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from johnnydecimal import api
from johnnydecimal.policy import resolve_policy, get_convention, get_volumes, get_links, find_root_policy

mcp = FastMCP("Johnny Decimal", json_response=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_root():
    """Get the JD root, preferring ~/Documents."""
    docs = Path.home() / "Documents"
    try:
        return api.get_system(docs)
    except Exception:
        return api.get_system(Path.cwd())


def _resolve_target(jd, target: str):
    """Resolve a JD target string to a (type, object) tuple.

    Tries: dotted ID, area range, category number, area number, name search.
    """
    # Dotted ID (e.g. 26.01)
    result = jd.find_by_id(target)
    if result:
        return ("id", result)

    # Area range (e.g. "20-29")
    m = re.match(r"^(\d{2})[-–](\d{2})$", target)
    if m:
        num = int(m.group(1))
        for area in jd.areas:
            if area._number == num:
                return ("area", area)

    # Category number (e.g. 26)
    try:
        result = jd.find_by_category(int(target))
        if result:
            return ("category", result)
    except ValueError:
        pass

    # Area start number (e.g. 20 → 20-29 area)
    try:
        num = int(target)
        for area in jd.areas:
            if area._number == num:
                return ("area", area)
    except ValueError:
        pass

    # Name search (case-insensitive, exact match)
    target_lower = target.lower()
    matches = []
    for area in jd.areas:
        if area._name.lower() == target_lower:
            matches.append(("area", area))
        for category in area.categories:
            if category.name.lower() == target_lower:
                matches.append(("category", category))
            for jd_id in category.ids:
                if jd_id.name and jd_id.name.lower() == target_lower:
                    matches.append(("id", jd_id))

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return ("ambiguous", matches)

    return (None, None)


def _obj_to_dict(kind, obj):
    """Convert a resolved JD object to a serializable dict."""
    if kind == "area":
        return {
            "type": "area",
            "number": obj._number,
            "range": f"{obj._number:02d}-{obj._end_number:02d}",
            "name": obj._name,
            "path": str(obj.path),
        }
    elif kind == "category":
        return {
            "type": "category",
            "number": obj.number,
            "name": obj.name,
            "area": obj.area._name,
            "path": str(obj.path),
        }
    elif kind == "id":
        return {
            "type": "id",
            "id": obj.id_str,
            "name": obj.name,
            "category": obj.category.name,
            "path": str(obj.path),
            "is_file": obj.is_file,
        }
    return {}


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("jd://tree")
def tree_resource() -> str:
    """Full Johnny Decimal system tree — areas, categories, IDs with paths."""
    jd = _get_root()
    return json.dumps(jd.to_dict(), indent=2)


@mcp.resource("jd://policy")
def policy_resource() -> str:
    """Root-level policy configuration (conventions, patterns, volumes)."""
    jd = _get_root()
    policy = resolve_policy(jd.path, jd.path)
    return json.dumps(policy, indent=2, default=str)


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------

@mcp.tool()
def jd_index(area: int | None = None) -> dict:
    """List the Johnny Decimal tree structure.

    Returns all areas, categories, and IDs. Optionally filter by area digit
    (e.g. area=2 returns only the 20-29 area).
    """
    jd = _get_root()
    data = jd.to_dict()
    if area is not None:
        data["areas"] = [
            a for a in data["areas"] if a["number"] // 10 == area
        ]
    return data


@mcp.tool()
def jd_find(target: str) -> dict:
    """Resolve a JD target to its filesystem path and metadata.

    Target can be a JD ID (26.01), category number (26), area range (20-29),
    area number (20), or name (Recipes). Returns type, path, and details.
    """
    jd = _get_root()
    kind, obj = _resolve_target(jd, target)

    if kind is None:
        return {"error": f"{target} not found"}
    if kind == "ambiguous":
        return {
            "error": "Ambiguous name",
            "matches": [_obj_to_dict(k, o) for k, o in obj],
        }

    return _obj_to_dict(kind, obj)


@mcp.tool()
def jd_search(query: str, archived: bool = False) -> list[dict]:
    """Search JD entries by name (case-insensitive substring match).

    Returns matching areas, categories, and IDs. Set archived=True to
    include archived entries (xx.99).
    """
    jd = _get_root()
    q = query.lower()
    results = []

    for area in jd.areas:
        if q in area._name.lower():
            results.append(_obj_to_dict("area", area))
        for category in area.categories:
            if q in category.name.lower():
                results.append(_obj_to_dict("category", category))
            for jd_id in category.ids:
                if not archived and jd_id.sequence == 99:
                    continue
                if jd_id.name and q in jd_id.name.lower():
                    results.append(_obj_to_dict("id", jd_id))

    return results


@mcp.tool()
def jd_ls(target: str) -> dict:
    """List the actual file contents of a JD location.

    Unlike jd_index which shows JD structure, this shows what files and
    folders are inside a given area, category, or ID folder.
    """
    jd = _get_root()
    kind, obj = _resolve_target(jd, target)

    if kind is None:
        return {"error": f"{target} not found"}
    if kind == "ambiguous":
        return {"error": "Ambiguous name, be more specific"}

    path = obj.path
    if not path.is_dir():
        return {
            "path": str(path),
            "type": "file",
            "size": path.stat().st_size,
        }

    entries = []
    for item in sorted(path.iterdir()):
        if item.name.startswith("."):
            continue
        entry = {"name": item.name, "type": "dir" if item.is_dir() else "file"}
        if item.is_symlink():
            entry["symlink_target"] = str(item.resolve())
        if item.is_file():
            try:
                entry["size"] = item.stat().st_size
            except OSError:
                pass
        entries.append(entry)

    return {"path": str(path), "entries": entries}


@mcp.tool()
def jd_triage(top: int = 10) -> dict:
    """Show where attention is needed — busiest unsorted dirs, empty categories.

    Returns structured triage data for the filing system.
    """
    jd = _get_root()

    unsorted_counts = []
    empty_cats = []

    for area in jd.areas:
        for category in area.categories:
            unsorted = None
            for jd_id in category.ids:
                if jd_id.sequence == 1:
                    unsorted = jd_id
                    break
            if unsorted and unsorted.path.is_dir():
                try:
                    items = [i for i in unsorted.path.iterdir() if not i.name.startswith(".")]
                    if items:
                        unsorted_counts.append({
                            "count": len(items),
                            "category": str(category),
                            "id": unsorted.id_str,
                            "path": str(unsorted.path),
                        })
                except PermissionError:
                    pass

            real_ids = [i for i in category.ids if i.sequence not in (0, 1, 99)]
            if not real_ids:
                empty_cats.append({
                    "category": str(category),
                    "path": str(category.path),
                })

    unsorted_counts.sort(key=lambda x: x["count"], reverse=True)

    total_unsorted = sum(u["count"] for u in unsorted_counts)
    return {
        "busiest_unsorted": unsorted_counts[:top],
        "empty_categories": empty_cats[:top],
        "total_unsorted_items": total_unsorted,
        "total_unsorted_categories": len(unsorted_counts),
    }


@mcp.tool()
def jd_policy(target: str | None = None, key: str | None = None) -> dict:
    """Get the effective policy for a JD location.

    Without target, returns root policy. With target, returns the resolved
    (cascaded) policy for that location. With key, returns just that value
    (e.g. key="naming.separator").
    """
    jd = _get_root()

    if target:
        kind, obj = _resolve_target(jd, target)
        if kind is None:
            return {"error": f"{target} not found"}
        if kind == "ambiguous":
            return {"error": "Ambiguous target"}
        path = obj.path
    else:
        path = jd.path

    policy = resolve_policy(path, jd.path)

    if key:
        value = get_convention(policy, key)
        return {"key": key, "value": value, "path": str(path)}

    return policy


# ---------------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------------

@mcp.tool()
def jd_new_id(category: str, name: str) -> dict:
    """Create a new auto-numbered ID in a category.

    Category can be a number (26) or name (Recipes). Returns the created
    ID's number and path.
    """
    jd = _get_root()
    kind, obj = _resolve_target(jd, category)

    if kind != "category":
        return {"error": f"Category '{category}' not found"}

    cat = obj
    seq = cat.next_id()
    id_str = f"{cat.number:02d}.{seq:02d}"
    dir_name = f"{id_str} {name}"
    new_path = cat.path / dir_name

    # Check policy
    policy = resolve_policy(cat.path, jd.path)
    if get_convention(policy, "ids_as_files", False):
        new_path.touch()
    else:
        new_path.mkdir()

        # Create meta/unsorted structure if policy says so
        if get_convention(policy, "meta_id", True) and seq != 0:
            pass  # meta is only for .00
        # For .00, it's the meta dir itself — already created

    new_path.mkdir(exist_ok=True)

    return {"id": id_str, "name": name, "path": str(new_path)}


@mcp.tool()
def jd_new_category(area: str, name: str) -> dict:
    """Create a new category in an area.

    Area can be a number (20), range (20-29), or name. Auto-numbers the
    category. Returns the created category's number and path.
    """
    jd = _get_root()
    kind, obj = _resolve_target(jd, area)

    if kind != "area":
        return {"error": f"Area '{area}' not found"}

    area_obj = obj

    # Find next available category number
    used = {cat.number for cat in area_obj.categories}
    cat_num = None
    for i in range(area_obj._number, area_obj._end_number + 1):
        if i not in used:
            cat_num = i
            break

    if cat_num is None:
        return {"error": f"Area {area_obj} is full"}

    dir_name = f"{cat_num:02d} {name}"
    new_path = area_obj.path / dir_name
    new_path.mkdir()

    return {"number": cat_num, "name": name, "path": str(new_path)}


@mcp.tool()
def jd_add(source_path: str, target_id: str, copy: bool = False) -> dict:
    """Add a file or directory into a JD ID from outside the tree.

    Moves by default. Set copy=True to copy instead.
    """
    jd = _get_root()
    source = Path(source_path).expanduser().resolve()

    if not source.exists():
        return {"error": f"Source not found: {source_path}"}

    result = jd.find_by_id(target_id)
    if not result:
        return {"error": f"JD ID {target_id} not found"}

    # Policy check
    policy = resolve_policy(result.path, jd.path)
    if get_convention(policy, "ids_files_only", False) and source.is_dir():
        return {"error": f"Policy ids_files_only=true for {target_id} — cannot add a directory"}

    dest = result.path / source.name
    if dest.exists():
        return {"error": f"Destination already exists: {dest}"}

    if copy:
        if source.is_dir():
            shutil.copytree(str(source), str(dest))
        else:
            shutil.copy2(str(source), str(dest))
        action = "copied"
    else:
        shutil.move(str(source), str(dest))
        action = "moved"

    return {"action": action, "source": str(source), "destination": str(dest)}


@mcp.tool()
def jd_move(source: str, destination: str | None = None, archive: bool = False) -> dict:
    """Move or archive a JD entry.

    With archive=True, moves to xx.99 (ID) or x0.99 (category).
    Otherwise moves source to destination.
    """
    jd = _get_root()
    kind, obj = _resolve_target(jd, source)

    if kind is None:
        return {"error": f"{source} not found"}
    if kind == "ambiguous":
        return {"error": "Ambiguous source"}

    if archive:
        if kind == "id":
            cat = obj.category
            archive_id = f"{cat.number:02d}.99"
            archive_dir = cat.path / f"{archive_id} Archive"
            archive_dir.mkdir(exist_ok=True)
            dest = archive_dir / obj.path.name
            shutil.move(str(obj.path), str(dest))
            return {"action": "archived", "source": str(obj.path), "destination": str(dest)}
        else:
            return {"error": "Archive is only supported for IDs"}

    if not destination:
        return {"error": "destination is required when not archiving"}

    dest_kind, dest_obj = _resolve_target(jd, destination)
    if dest_kind is None:
        return {"error": f"Destination {destination} not found"}

    dest_path = dest_obj.path / obj.path.name
    shutil.move(str(obj.path), str(dest_path))
    return {"action": "moved", "source": str(obj.path), "destination": str(dest_path)}


@mcp.tool()
def jd_restore(id_str: str, renumber: bool = False) -> dict:
    """Restore an archived entry from xx.99.

    Looks for the ID inside the archive folder (xx.99) and moves it back.
    Set renumber=True to assign next available number if original is taken.
    """
    jd = _get_root()

    # Parse the ID to find its category
    m = re.match(r"(\d{2})\.(\d{2})", id_str)
    if not m:
        return {"error": f"Invalid ID format: {id_str}"}

    cat_num = int(m.group(1))
    cat = jd.find_by_category(cat_num)
    if not cat:
        return {"error": f"Category {cat_num:02d} not found"}

    # Find the archive dir
    archive_dir = None
    for jd_id in cat.ids:
        if jd_id.sequence == 99:
            archive_dir = jd_id.path
            break

    if not archive_dir or not archive_dir.is_dir():
        return {"error": f"No archive (xx.99) in category {cat_num:02d}"}

    # Find the entry in archive
    target = None
    for item in archive_dir.iterdir():
        if item.name.startswith(id_str):
            target = item
            break

    if not target:
        return {"error": f"{id_str} not found in archive"}

    # Check if original location is free
    dest = cat.path / target.name
    if dest.exists() and renumber:
        seq = cat.next_id()
        new_id = f"{cat_num:02d}.{seq:02d}"
        new_name = re.sub(r"^\d{2}\.\d{2}", new_id, target.name)
        dest = cat.path / new_name

    if dest.exists():
        return {"error": f"Destination exists: {dest}. Use renumber=True to assign a new number."}

    shutil.move(str(target), str(dest))
    return {"action": "restored", "source": str(target), "destination": str(dest)}


@mcp.tool()
def jd_init(category: str, meta: bool = True, unsorted: bool = True) -> dict:
    """Initialize meta structure (xx.00, xx.01) for a category.

    Creates the meta dir (xx.00) and unsorted dir (xx.01 Unsorted) if
    they don't already exist.
    """
    jd = _get_root()
    kind, obj = _resolve_target(jd, category)

    if kind != "category":
        return {"error": f"Category '{category}' not found"}

    cat = obj
    created = []

    if meta:
        meta_name = f"{cat.number:02d}.00"
        meta_path = cat.path / meta_name
        if not meta_path.exists():
            meta_path.mkdir()
            created.append(str(meta_path))

    if unsorted:
        unsorted_name = f"{cat.number:02d}.01 {cat.name} - Unsorted"
        unsorted_path = cat.path / unsorted_name
        if not unsorted_path.exists():
            unsorted_path.mkdir()
            created.append(str(unsorted_path))

    return {"category": str(cat), "created": created}


@mcp.tool()
def jd_validate(fix: bool = False, dry_run: bool = False, force: bool = False) -> dict:
    """Run validation checks on the JD filing system.

    Returns structured issues found. With fix=True, auto-fixes safe issues
    (naming conventions, broken symlinks). With dry_run=True, shows what
    fix would do without doing it. With force=True and fix=True, also
    fixes wrong-target inbound links (delete + recreate).
    """
    jd = _get_root()
    issues = []
    warnings = []
    fixed = []
    do_fix = fix and not dry_run

    # Duplicates
    for id_str, path1, path2 in jd.find_duplicates():
        issues.append({
            "type": "duplicate",
            "id": id_str,
            "paths": [str(path1), str(path2)],
        })

    # Orphans
    for orphan in jd.find_orphans():
        warnings.append({
            "type": "orphan",
            "path": str(orphan),
        })

    # Broken symlinks — protect volume symlinks (unmounted drives)
    for broken in jd.broken_symlinks:
        raw_target = str(broken.readlink())
        if raw_target.startswith("/Volumes"):
            vol_name = Path(raw_target).parts[2] if len(Path(raw_target).parts) > 2 else raw_target
            warnings.append({
                "type": "volume_unmounted",
                "path": str(broken),
                "target": raw_target,
                "volume": vol_name,
            })
        elif fix:
            entry = {"type": "broken_symlink", "path": str(broken)}
            if do_fix:
                broken.unlink()
            entry["fixed"] = True
            fixed.append(entry)
        else:
            issues.append({"type": "broken_symlink", "path": str(broken)})

    # Volume aliases (declared and undeclared)
    volumes = get_volumes(jd.path)
    volume_names = set(volumes.keys())
    for jd_id in jd.all_ids():
        if jd_id.is_file and not jd_id.path.is_symlink():
            vol_match = re.match(r"\d{2}\.\d{2} .+ \[(.+)\]$", jd_id.path.name)
            if vol_match:
                ref_name = vol_match.group(1)
                if ref_name in volume_names:
                    warnings.append({
                        "type": "volume_alias",
                        "id": jd_id.id_str,
                        "volume": ref_name,
                        "path": str(jd_id.path),
                    })
                else:
                    warnings.append({
                        "type": "volume_undeclared",
                        "id": jd_id.id_str,
                        "volume": ref_name,
                        "path": str(jd_id.path),
                    })

    # Cross-volume validation — check mounted external drives
    volume_results = []
    for vol_name, conf in volumes.items():
        mount = conf["mount"]
        vol_root_suffix = conf["root"]
        if not mount.exists():
            continue

        tree_root = mount / vol_root_suffix if vol_root_suffix else mount
        if not tree_root.is_dir():
            warnings.append({
                "type": "volume_bad_root",
                "volume": vol_name,
                "path": str(tree_root),
            })
            continue

        from johnnydecimal.models import JDSystem
        try:
            vol_jd = JDSystem(tree_root)
        except Exception:
            warnings.append({
                "type": "volume_load_error",
                "volume": vol_name,
                "path": str(tree_root),
            })
            continue
        if not vol_jd.areas:
            warnings.append({
                "type": "volume_no_areas",
                "volume": vol_name,
                "path": str(tree_root),
            })
            continue

        vol_issues = []

        # Duplicate IDs within the volume
        for id_str, path1, path2 in vol_jd.find_duplicates():
            vol_issues.append({
                "type": "duplicate",
                "id": id_str,
                "paths": [str(path1), str(path2)],
            })

        # Mismatched category prefixes on the volume
        for vid in vol_jd.all_ids():
            if vid.is_mismatched:
                vol_issues.append({
                    "type": "mismatched_prefix",
                    "id": vid.id_str,
                    "category": f"{vid.category.number:02d}",
                    "path": str(vid.path),
                })

        # Orphan directories on the volume
        vol_orphans = []
        for orphan in vol_jd.find_orphans():
            parent_cat = orphan.parent.name[:2] if orphan.parent else ""
            if parent_cat != "01":
                vol_orphans.append(str(orphan))

        # Cross-check: aliases should match content on volume
        alias_mismatches = []
        for jd_id in jd.all_ids():
            if jd_id.path.is_symlink() or jd_id.path.is_dir():
                continue
            m = re.match(r"\d{2}\.\d{2} .+ \[(.+)\]$", jd_id.path.name)
            if m and m.group(1) == vol_name:
                vol_target = vol_jd.find_by_id(jd_id.id_str)
                if not vol_target:
                    alias_mismatches.append({
                        "id": jd_id.id_str,
                        "name": jd_id.name,
                    })

        # Cross-check: linked symlinks should resolve to valid IDs
        link_mismatches = []
        for jd_id in jd.all_ids():
            if not jd_id.path.is_symlink():
                continue
            try:
                target = jd_id.path.resolve(strict=True)
                if str(target).startswith(str(mount)):
                    vol_target = vol_jd.find_by_id(jd_id.id_str)
                    if not vol_target:
                        link_mismatches.append({
                            "id": jd_id.id_str,
                            "target": str(target),
                        })
                    elif vol_target.path.resolve() != target:
                        link_mismatches.append({
                            "id": jd_id.id_str,
                            "target": str(target),
                            "expected": str(vol_target.path),
                        })
            except (OSError, FileNotFoundError):
                pass

        volume_results.append({
            "volume": vol_name,
            "root": str(tree_root),
            "areas": len(vol_jd.areas),
            "issues": vol_issues,
            "orphans": vol_orphans,
            "alias_mismatches": alias_mismatches,
            "link_mismatches": link_mismatches,
        })

    # Inbound link declarations in policy
    declared_links = get_links(jd.path)
    for jd_id_str, ext_paths in declared_links.items():
        target_obj = jd.find_by_id(jd_id_str)
        if not target_obj:
            for ext in ext_paths:
                warnings.append({
                    "type": "inbound_link_id_not_found",
                    "id": jd_id_str,
                    "source": ext,
                })
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
                        fixed.append({
                            "type": "inbound_link_recreated",
                            "source": ext,
                            "target": str(target_obj.path),
                        })
                    else:
                        issues.append({
                            "type": "inbound_link_wrong_target",
                            "source": ext,
                            "actual": str(actual),
                            "expected": str(expected),
                        })
            elif ext_expanded.exists():
                issues.append({
                    "type": "inbound_link_not_a_symlink",
                    "source": ext,
                    "id": jd_id_str,
                })
            else:
                if fix:
                    if do_fix:
                        ext_expanded.parent.mkdir(parents=True, exist_ok=True)
                        ext_expanded.symlink_to(target_obj.path)
                    fixed.append({
                        "type": "inbound_link_created",
                        "source": ext,
                        "target": str(target_obj.path),
                    })
                else:
                    warnings.append({
                        "type": "inbound_link_missing",
                        "source": ext,
                        "id": jd_id_str,
                        "target_name": target_obj.name,
                    })

    return {
        "issues": issues,
        "warnings": warnings,
        "fixed": fixed,
        "volumes": volume_results,
        "summary": {
            "issues": len(issues),
            "warnings": len(warnings),
            "fixed": len(fixed),
            "volumes_checked": len(volume_results),
        },
    }


# ---------------------------------------------------------------------------
# Volume tools
# ---------------------------------------------------------------------------

@mcp.tool()
def jd_volume_list() -> dict:
    """List declared external volumes, their mount status, and reference counts."""
    jd = _get_root()
    volumes = get_volumes(jd.path)

    if not volumes:
        return {"volumes": [], "message": "No volumes declared in root policy.yaml"}

    # Count aliases per volume
    volume_names = set(volumes.keys())
    alias_counts = {name: 0 for name in volume_names}
    linked_counts = {name: 0 for name in volume_names}

    for jd_id in jd.all_ids():
        if jd_id.path.is_symlink():
            try:
                target = str(jd_id.path.resolve(strict=True))
                for vname, conf in volumes.items():
                    if target.startswith(str(conf["mount"])):
                        linked_counts[vname] += 1
                        break
            except (OSError, FileNotFoundError):
                pass
        elif jd_id.is_file:
            m = re.match(r"\d{2}\.\d{2} .+ \[(.+)\]$", jd_id.path.name)
            if m and m.group(1) in volume_names:
                alias_counts[m.group(1)] += 1

    result = []
    for name, conf in volumes.items():
        mount = conf["mount"]
        result.append({
            "name": name,
            "mount": str(mount),
            "mounted": mount.exists(),
            "aliases": alias_counts[name],
            "linked": linked_counts[name],
        })

    return {"volumes": result}


@mcp.tool()
def jd_volume_scan() -> dict:
    """Scan the tree for all volume references — aliases, linked symlinks, broken links.

    Provides a full picture of external volume state.
    """
    jd = _get_root()
    volumes = get_volumes(jd.path)
    volume_names = set(volumes.keys())

    aliases = []
    linked = []
    broken = []
    undeclared = {}

    for jd_id in jd.all_ids():
        if jd_id.path.is_symlink():
            try:
                target = jd_id.path.resolve(strict=True)
                target_str = str(target)
                for vname, conf in volumes.items():
                    if target_str.startswith(str(conf["mount"])):
                        linked.append({"id": jd_id.id_str, "name": jd_id.name, "volume": vname})
                        break
            except (OSError, FileNotFoundError):
                raw_target = str(jd_id.path.readlink())
                if raw_target.startswith("/Volumes"):
                    broken.append({"id": jd_id.id_str, "name": jd_id.name, "target": raw_target})
            continue

        if jd_id.path.is_dir():
            continue
        m = re.match(r"\d{2}\.\d{2} .+ \[(.+)\]$", jd_id.path.name)
        if m:
            ref_name = m.group(1)
            entry = {"id": jd_id.id_str, "name": jd_id.name}
            if ref_name in volume_names:
                entry["volume"] = ref_name
                aliases.append(entry)
            else:
                undeclared.setdefault(ref_name, []).append(entry)

    return {
        "aliases": aliases,
        "linked": linked,
        "broken": broken,
        "undeclared": {k: v for k, v in undeclared.items()},
        "summary": {
            "aliases": len(aliases),
            "linked": len(linked),
            "broken": len(broken),
            "undeclared_volumes": len(undeclared),
        },
    }


@mcp.tool()
def jd_volume_index(name: str | None = None) -> dict:
    """Generate a tree index for mounted external volumes.

    Runs tree on the volume's JD root and saves to 00.02 External drives/.
    Without name, indexes all mounted volumes. Returns paths to generated files.
    """
    import subprocess

    jd = _get_root()
    volumes = get_volumes(jd.path)

    if not volumes:
        return {"error": "No volumes declared in root policy.yaml"}

    # Find 00.02 index dir
    cat_00 = jd.find_by_category(0)
    index_dir = None
    if cat_00:
        for jd_id in cat_00.ids:
            if jd_id.sequence == 2:
                index_dir = jd_id.path
                break
        if not index_dir:
            index_dir = cat_00.path / "00.02 External drives"
            index_dir.mkdir(exist_ok=True)

    if not index_dir:
        return {"error": "Cannot find or create index directory (00.02)"}

    if name:
        if name not in volumes:
            return {"error": f"Unknown volume: {name}", "declared": list(volumes.keys())}
        targets = {name: volumes[name]}
    else:
        targets = volumes

    results = []
    for vol_name, conf in targets.items():
        mount = conf["mount"]
        vol_root = conf["root"]

        if not mount.exists():
            results.append({"volume": vol_name, "status": "skipped", "reason": "not mounted"})
            continue

        tree_root = mount / vol_root if vol_root else mount
        if not tree_root.exists():
            results.append({"volume": vol_name, "status": "skipped", "reason": f"root not found: {tree_root}"})
            continue

        output_file = index_dir / f"Index ({vol_name}).txt"
        result = subprocess.run(
            ["tree", "-I", ".DS_Store|.git|__pycache__|.Trash|.Spotlight-V100|.fseventsd",
             str(tree_root)],
            capture_output=True, text=True,
        )

        if result.returncode != 0:
            results.append({"volume": vol_name, "status": "error", "reason": result.stderr.strip()})
            continue

        output_file.write_text(result.stdout)
        lines = result.stdout.count("\n")
        results.append({
            "volume": vol_name,
            "status": "indexed",
            "path": str(output_file),
            "lines": lines,
        })

    return {"results": results}


# ---------------------------------------------------------------------------
# Policy write tools
# ---------------------------------------------------------------------------

@mcp.tool()
def jd_policy_set(key: str, value: str, target: str | None = None) -> dict:
    """Set a convention value in the policy file for a JD location.

    Key uses dot notation (e.g. 'conventions.ids_files_only').
    Target defaults to root. Value is auto-converted (true/false → bool, digits → int).
    """
    import yaml

    jd = _get_root()

    if target:
        kind, obj = _resolve_target(jd, target)
        if kind is None:
            return {"error": f"{target} not found"}
        path = obj.path
    else:
        path = jd.path

    from johnnydecimal.policy import find_meta_dir, POLICY_FILENAME
    meta = find_meta_dir(path)
    if not meta:
        return {"error": f"No meta dir found for {path}"}

    policy_path = meta / POLICY_FILENAME

    # Load existing
    if policy_path.exists():
        with open(policy_path) as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    # Auto-convert value
    if value.lower() in ("true", "false"):
        converted = value.lower() == "true"
    elif value.isdigit():
        converted = int(value)
    else:
        converted = value

    # Set nested key
    parts = key.split(".")
    current = data
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = converted

    with open(policy_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    return {"key": key, "value": converted, "policy_file": str(policy_path)}


@mcp.tool()
def jd_policy_unset(key: str, target: str | None = None) -> dict:
    """Remove a convention key from the policy file for a JD location."""
    import yaml

    jd = _get_root()

    if target:
        kind, obj = _resolve_target(jd, target)
        if kind is None:
            return {"error": f"{target} not found"}
        path = obj.path
    else:
        path = jd.path

    from johnnydecimal.policy import find_meta_dir, POLICY_FILENAME
    meta = find_meta_dir(path)
    if not meta:
        return {"error": f"No meta dir found for {path}"}

    policy_path = meta / POLICY_FILENAME
    if not policy_path.exists():
        return {"error": f"No policy file at {policy_path}"}

    with open(policy_path) as f:
        data = yaml.safe_load(f) or {}

    parts = key.split(".")
    current = data
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            return {"error": f"Key {key} not found"}
        current = current[part]

    if parts[-1] not in current:
        return {"error": f"Key {key} not found"}

    del current[parts[-1]]

    with open(policy_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    return {"key": key, "removed": True, "policy_file": str(policy_path)}


@mcp.tool()
def jd_generate_index() -> dict:
    """Regenerate the 00.00 Index.md file from the current filesystem state."""
    jd = _get_root()

    lines = [f"# Index — {jd.path.name}", ""]
    for area in jd.areas:
        lines.append(f"## {area}")
        for cat in area.categories:
            lines.append(f"  {cat}")
            for jd_id in cat.ids:
                lines.append(f"    {jd_id}")
        lines.append("")

    content = "\n".join(lines) + "\n"

    # Find 00.00 meta dir for index
    from johnnydecimal.policy import find_meta_dir
    meta = find_meta_dir(jd.path)
    if not meta:
        return {"error": "Cannot find 00.00 meta directory"}

    index_path = meta / "Index.md"
    index_path.write_text(content)

    return {"path": str(index_path), "lines": len(lines)}


# ---------------------------------------------------------------------------
# Symlinks / backup audit
# ---------------------------------------------------------------------------

@mcp.tool()
def jd_symlinks() -> dict:
    """List every symlink in the JD tree with target location and git status.

    Shows what lives outside iCloud Drive. For git repos, reports whether
    they have a remote and whether the working tree is clean or dirty.
    """
    import subprocess

    jd = _get_root()
    links = []

    for area in jd.areas:
        if area.path.is_symlink():
            try:
                target = area.path.resolve(strict=True)
                links.append({"id": str(area), "name": area._name, "target": str(target), "broken": False})
            except (OSError, FileNotFoundError):
                links.append({"id": str(area), "name": area._name, "target": str(area.path.readlink()), "broken": True})
            continue

        for category in area.categories:
            if category.path.is_symlink():
                try:
                    target = category.path.resolve(strict=True)
                    links.append({"id": f"{category.number:02d}", "name": category.name, "target": str(target), "broken": False})
                except (OSError, FileNotFoundError):
                    links.append({"id": f"{category.number:02d}", "name": category.name, "target": str(category.path.readlink()), "broken": True})
                continue

            for jd_id in category.ids:
                if jd_id.path.is_symlink():
                    try:
                        target = jd_id.path.resolve(strict=True)
                        links.append({"id": jd_id.id_str, "name": jd_id.name or "(meta)", "target": str(target), "broken": False})
                    except (OSError, FileNotFoundError):
                        links.append({"id": jd_id.id_str, "name": jd_id.name or "(meta)", "target": str(jd_id.path.readlink()), "broken": True})

    # Enrich with git status
    for link in links:
        if link["broken"]:
            continue
        git_dir = Path(link["target"]) / ".git"
        if not git_dir.exists():
            continue
        try:
            remote = subprocess.run(
                ["git", "-C", link["target"], "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=5,
            )
            dirty = subprocess.run(
                ["git", "-C", link["target"], "status", "--porcelain"],
                capture_output=True, text=True, timeout=5,
            )
            link["git"] = {
                "has_remote": remote.returncode == 0,
                "dirty": bool(dirty.stdout.strip()),
            }
        except Exception:
            pass

    # Group by location
    groups = {}
    for link in links:
        target = Path(link["target"])
        parts = target.parts
        if link["broken"]:
            key = link["target"]
        elif len(parts) >= 3 and parts[1] == "Volumes":
            key = f"/Volumes/{parts[2]}"
        elif len(parts) >= 4 and parts[1] == "Users":
            key = f"~/{parts[3]}"
        else:
            key = str(target.parent)
        groups.setdefault(key, []).append(link)

    # Inbound links from policy
    declared = get_links(jd.path)
    inbound_links = []
    for jd_id_str, ext_paths in declared.items():
        target_obj = jd.find_by_id(jd_id_str)
        if not target_obj:
            for ext in ext_paths:
                inbound_links.append({"id": jd_id_str, "source": ext, "status": "id_not_found"})
            continue
        for ext in ext_paths:
            ext_expanded = Path(ext).expanduser()
            if ext_expanded.is_symlink():
                actual = ext_expanded.resolve()
                expected = target_obj.path.resolve()
                if actual == expected:
                    inbound_links.append({"id": jd_id_str, "source": ext, "status": "ok"})
                else:
                    inbound_links.append({"id": jd_id_str, "source": ext, "status": "wrong_target", "actual": str(actual)})
            elif ext_expanded.exists():
                inbound_links.append({"id": jd_id_str, "source": ext, "status": "not_a_symlink"})
            else:
                inbound_links.append({"id": jd_id_str, "source": ext, "status": "missing"})

    return {
        "symlinks": links,
        "inbound_links": inbound_links,
        "by_location": {k: [l["id"] for l in v] for k, v in groups.items()},
        "total": len(links),
        "broken": sum(1 for l in links if l["broken"]),
        "no_remote": [l["id"] for l in links if l.get("git", {}).get("has_remote") is False],
        "dirty": [l["id"] for l in links if l.get("git", {}).get("dirty") is True],
    }


@mcp.tool()
def jd_ln(source: str, jd_id: str, remove: bool = False) -> dict:
    """Create or remove an inbound symlink and declare it in policy.

    Creates a symlink at source pointing into the JD tree at jd_id,
    and records it in policy.yaml so jd_validate tracks it.
    With remove=True, removes the symlink and policy entry.
    """
    import yaml

    jd = _get_root()

    target_obj = jd.find_by_id(jd_id)
    if not target_obj:
        return {"error": f"JD ID {jd_id} not found"}

    source_path = Path(source).expanduser()

    if remove:
        result = {"action": "remove", "source": source, "jd_id": jd_id}

        if source_path.is_symlink():
            source_path.unlink()
            result["symlink_removed"] = True
        elif source_path.exists():
            return {"error": f"{source} exists but is not a symlink — not removing"}
        else:
            result["symlink_removed"] = False  # already gone

        policy_path = find_root_policy(jd.path)
        if policy_path:
            with open(policy_path) as f:
                data = yaml.safe_load(f) or {}
            links = data.get("links", {})
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
                with open(policy_path, "w") as f:
                    yaml.dump(data, f, default_flow_style=False, sort_keys=False)
                result["policy_updated"] = True
            else:
                result["policy_updated"] = False
        return result

    # Create mode
    if source_path.exists() and not source_path.is_symlink():
        return {"error": f"{source} exists and is not a symlink — move it first"}

    result = {"action": "create", "source": source, "jd_id": jd_id, "target": str(target_obj.path)}

    if source_path.is_symlink():
        actual = source_path.resolve()
        expected = target_obj.path.resolve()
        if actual == expected:
            result["symlink_created"] = False  # already correct
        else:
            return {"error": f"{source} is a symlink but points to {actual}, expected {expected}"}
    else:
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.symlink_to(target_obj.path)
        result["symlink_created"] = True

    # Update policy
    policy_path = find_root_policy(jd.path)
    if not policy_path:
        result["policy_updated"] = False
        result["warning"] = "No root policy.yaml found"
        return result

    with open(policy_path) as f:
        data = yaml.safe_load(f) or {}

    links = data.setdefault("links", {})
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
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    result["policy_updated"] = True

    return result


# ---------------------------------------------------------------------------
# Apple Notes tools
# ---------------------------------------------------------------------------

def _notes_id_display(jd_id_obj):
    """Human-readable note name: '26.05 Sourdough'."""
    return str(jd_id_obj)


@mcp.tool()
def jd_notes_scan() -> dict:
    """Scan Apple Notes for JD-matching folders and compare against policy.

    Returns three buckets:
      - declared_found: in policy and exists in Notes
      - declared_missing: in policy but not in Notes
      - undeclared: in Notes with JD naming but not in policy
    """
    from johnnydecimal.notes import build_tree, NotesError
    from johnnydecimal.policy import get_notes_declarations

    jd = _get_root()
    declarations = get_notes_declarations(jd.path)

    if not declarations:
        return {"error": None, "declared_found": [], "declared_missing": [], "undeclared": [],
                "message": "No notes declarations in root policy.yaml"}

    try:
        tree = build_tree()
    except NotesError as exc:
        return {"error": str(exc)}

    declared_found = []
    declared_missing = []
    undeclared = []

    for cat_str, ids in declarations.items():
        cat_num = int(cat_str)
        cat = jd.find_by_category(cat_num)
        if not cat:
            continue

        area = cat.parent
        area_name = str(area)
        cat_name = str(cat)
        area_tree = tree.get(area_name, {})
        cat_tree = area_tree.get("folders", {}).get(cat_name, {})

        if ids == "all":
            for jd_id in cat.ids:
                note_name = _notes_id_display(jd_id)
                notes_list = cat_tree.get("notes", [])
                entry = {"id": jd_id.id_str, "name": jd_id.name}
                if note_name in notes_list:
                    declared_found.append(entry)
                else:
                    declared_missing.append(entry)
        else:
            for id_str in ids:
                jd_id = jd.find_by_id(str(id_str))
                if not jd_id:
                    declared_missing.append({"id": str(id_str), "name": "(not found)"})
                    continue
                note_name = _notes_id_display(jd_id)
                notes_list = cat_tree.get("notes", [])
                entry = {"id": jd_id.id_str, "name": jd_id.name}
                if note_name in notes_list:
                    declared_found.append(entry)
                else:
                    declared_missing.append(entry)

    # Scan for undeclared JD matches
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
                if cat_str in declarations:
                    val = declarations[cat_str]
                    if val == "all" or id_str in val:
                        continue
                undeclared.append({"id": id_str, "name": note_name,
                                   "location": f"{area_name} > {cat_name}"})

    return {
        "error": None,
        "declared_found": declared_found,
        "declared_missing": declared_missing,
        "undeclared": undeclared,
    }


@mcp.tool()
def jd_notes_validate() -> dict:
    """Check consistency between Notes stubs, Apple Notes, and policy.

    Returns lists of issues and warnings for declared Notes-backed IDs.
    """
    from johnnydecimal.notes import note_exists, folder_exists, NotesError
    from johnnydecimal.policy import get_notes_declarations

    jd = _get_root()
    declarations = get_notes_declarations(jd.path)

    if not declarations:
        return {"issues": [], "warnings": [], "message": "No notes declarations"}

    issues = []
    warnings = []

    for cat_str, ids in declarations.items():
        cat_num = int(cat_str)
        cat = jd.find_by_category(cat_num)
        if not cat:
            warnings.append({"id": cat_str, "message": "Category not found in JD tree"})
            continue

        area = cat.parent
        cat_folder = [str(area), str(cat)]

        try:
            if not folder_exists([str(area)]):
                warnings.append({"id": cat_str, "message": f"Area folder '{area}' missing in Notes"})
            if not folder_exists(cat_folder):
                warnings.append({"id": cat_str, "message": f"Category folder '{cat}' missing in Notes"})
        except NotesError as exc:
            issues.append({"id": cat_str, "message": f"Notes error: {exc}"})
            continue

        if ids == "all":
            id_list = [jd_id.id_str for jd_id in cat.ids]
        else:
            id_list = [str(i) for i in ids]

        for id_str in id_list:
            jd_id = jd.find_by_id(str(id_str))
            if not jd_id:
                warnings.append({"id": id_str, "message": "Declared but not found in tree"})
                continue

            note_name = _notes_id_display(jd_id)
            stub_pattern = re.compile(
                rf"{re.escape(jd_id.id_str)} .+ \[Apple Notes\]\.(yaml|yml)$"
            )
            stub_files = [f for f in jd_id.category.path.iterdir() if stub_pattern.match(f.name)]

            try:
                has_note = note_exists(cat_folder, note_name)
            except NotesError:
                has_note = None

            if jd_id.path.is_dir():
                issues.append({"id": jd_id.id_str,
                               "message": "Exists as directory AND declared as Notes-backed"})

            if stub_files and has_note is False:
                issues.append({"id": jd_id.id_str,
                               "message": f"Stub exists but note missing in Notes"})
            elif not stub_files and has_note is True:
                warnings.append({"id": jd_id.id_str,
                                 "message": "Note exists in Notes but no stub file"})

    return {"issues": issues, "warnings": warnings}


@mcp.tool()
def jd_notes_create(id_str: str, folder: bool = False, stub: bool = False) -> dict:
    """Create a note (or folder) in Apple Notes for a JD ID.

    Ensures area and category folders exist first.
    Set folder=True to create a subfolder instead of a note.
    Set stub=True to also create a filesystem stub file.
    """
    import yaml
    from johnnydecimal.notes import (
        create_folder, create_note, folder_exists, note_exists, NotesError,
    )

    jd = _get_root()
    jd_id = jd.find_by_id(id_str)
    if not jd_id:
        return {"error": f"ID {id_str} not found"}

    area = jd_id.category.parent
    area_folder = [str(area)]
    cat_folder = [str(area), str(jd_id.category)]
    note_name = _notes_id_display(jd_id)
    result = {"id": id_str, "created": [], "error": None}

    try:
        if not folder_exists(area_folder):
            create_folder(area_folder)
            result["created"].append(f"folder:{area}")

        if not folder_exists(cat_folder):
            create_folder(cat_folder)
            result["created"].append(f"folder:{jd_id.category}")

        if folder:
            id_folder = cat_folder + [note_name]
            if not folder_exists(id_folder):
                create_folder(id_folder)
                result["created"].append(f"folder:{note_name}")
        else:
            if not note_exists(cat_folder, note_name):
                create_note(cat_folder, note_name)
                result["created"].append(f"note:{note_name}")
    except NotesError as exc:
        result["error"] = str(exc)
        return result

    if stub:
        notes_path = " > ".join(cat_folder + [note_name])
        stub_name = f"{jd_id.id_str} {jd_id.name} [Apple Notes].yaml"
        stub_path = jd_id.category.path / stub_name
        if not stub_path.exists():
            stub_data = {"location": "Apple Notes", "path": notes_path}
            with open(stub_path, "w") as f:
                yaml.dump(stub_data, f, default_flow_style=False, sort_keys=False)
            result["created"].append(f"stub:{stub_name}")

    return result


@mcp.tool()
def jd_notes_open(id_str: str) -> dict:
    """Open a note in Apple Notes.

    Finds the note for the given JD ID and brings it up in Notes.app.
    """
    from johnnydecimal.notes import open_note, NotesError

    jd = _get_root()
    jd_id = jd.find_by_id(id_str)
    if not jd_id:
        return {"error": f"ID {id_str} not found"}

    area = jd_id.category.parent
    cat_folder = [str(area), str(jd_id.category)]
    note_name = _notes_id_display(jd_id)

    try:
        open_note(cat_folder, note_name)
        return {"opened": note_name, "error": None}
    except NotesError as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# OmniFocus tools
# ---------------------------------------------------------------------------

def _parse_jd_tags(tags: list[str]) -> list[str]:
    """Extract JD IDs from tag names. E.g. ['JD:26.05', 'Work'] -> ['26.05']."""
    result = []
    for tag in tags:
        m = re.match(r"^JD:(\d{2}(?:\.\d{2})?)$", tag)
        if m:
            result.append(m.group(1))
    return result


@mcp.tool()
def jd_omnifocus_scan() -> dict:
    """Scan OmniFocus for JD-tagged projects and compare against the JD tree.

    Returns three buckets:
      - tagged_found: OF projects with valid JD tags
      - tagged_dead: OF projects with JD tags pointing to nonexistent IDs
      - untracked: active JD IDs with content but no OF project
    """
    from johnnydecimal.omnifocus import list_projects_with_jd_tags, OmniFocusError
    from johnnydecimal.policy import is_omnifocus_enabled

    jd = _get_root()
    if not is_omnifocus_enabled(jd.path):
        return {"error": "OmniFocus integration disabled (omnifocus: false in root policy.yaml)"}

    try:
        projects = list_projects_with_jd_tags()
    except OmniFocusError as exc:
        return {"error": str(exc)}

    tagged_found = []
    tagged_dead = []
    of_tracked_ids = set()

    for proj in projects:
        jd_ids = _parse_jd_tags(proj["tags"])
        for jd_id_str in jd_ids:
            jd_id = jd.find_by_id(jd_id_str) if "." in jd_id_str else None
            cat = jd.find_by_category(int(jd_id_str)) if "." not in jd_id_str else None
            entry = {"jd_id": jd_id_str, "project": proj["name"],
                     "folder": proj.get("folder"), "status": proj.get("status")}
            if jd_id or cat:
                tagged_found.append(entry)
                of_tracked_ids.add(jd_id_str)
            else:
                tagged_dead.append(entry)

    untracked = []
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
                                untracked.append({"id": jd_id.id_str, "name": jd_id.name})
                        except PermissionError:
                            pass

    return {
        "error": None,
        "tagged_found": tagged_found,
        "tagged_dead": tagged_dead,
        "untracked": untracked,
    }


@mcp.tool()
def jd_omnifocus_validate() -> dict:
    """Check consistency between OmniFocus and the JD tree.

    Returns issues (errors) and warnings (advisory):
      1. OF projects with invalid JD tags (issue)
      2. Active JD IDs without OF projects (warning)
      3. Orphan OF projects without JD tags (warning)
      4. OF folder structure vs JD areas (warning)
    """
    from johnnydecimal.omnifocus import list_projects_with_jd_tags, list_folders, OmniFocusError
    from johnnydecimal.policy import is_omnifocus_enabled

    jd = _get_root()
    if not is_omnifocus_enabled(jd.path):
        return {"error": "OmniFocus integration disabled"}

    try:
        projects = list_projects_with_jd_tags()
        of_folders = list_folders()
    except OmniFocusError as exc:
        return {"error": str(exc)}

    issues = []
    warnings = []
    of_tracked_ids = set()

    for proj in projects:
        jd_ids = _parse_jd_tags(proj["tags"])
        for jd_id_str in jd_ids:
            jd_id = jd.find_by_id(jd_id_str) if "." in jd_id_str else None
            cat = jd.find_by_category(int(jd_id_str)) if "." not in jd_id_str else None
            if jd_id or cat:
                of_tracked_ids.add(jd_id_str)
            else:
                issues.append({"project": proj["name"], "tag": f"JD:{jd_id_str}",
                               "message": "Tag points to nonexistent JD ID"})

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
                                warnings.append({"id": jd_id.id_str, "name": jd_id.name,
                                                 "message": "Active ID with no OF project"})
                        except PermissionError:
                            pass

    top_folders = {f["name"] for f in of_folders if f["parent_name"] is None}
    for area in jd.areas:
        area_name = area._name
        if not any(area_name.lower() in f.lower() for f in top_folders):
            warnings.append({"area": str(area),
                             "message": "No matching OF top-level folder"})

    return {"issues": issues, "warnings": warnings}


@mcp.tool()
def jd_omnifocus_open(id_str: str) -> dict:
    """Open the OmniFocus project tagged with a JD ID.

    Finds OF projects with the JD:xx.xx tag and opens in OmniFocus.
    """
    from johnnydecimal.omnifocus import list_projects_with_jd_tags, open_project, OmniFocusError
    from johnnydecimal.policy import is_omnifocus_enabled

    jd = _get_root()
    if not is_omnifocus_enabled(jd.path):
        return {"error": "OmniFocus integration disabled"}

    tag_name = f"JD:{id_str}"

    try:
        projects = list_projects_with_jd_tags()
    except OmniFocusError as exc:
        return {"error": str(exc)}

    matches = [p for p in projects if tag_name in p["tags"]]
    if not matches:
        return {"error": f"No OmniFocus project tagged with {tag_name}"}

    if len(matches) == 1:
        try:
            open_project(matches[0]["name"])
            return {"opened": matches[0]["name"], "error": None}
        except OmniFocusError as exc:
            return {"error": str(exc)}

    return {
        "error": "Multiple projects found",
        "matches": [{"name": p["name"], "folder": p.get("folder")} for p in matches],
    }


@mcp.tool()
def jd_omnifocus_create(id_str: str, folder: str | None = None) -> dict:
    """Create an OmniFocus project for a JD ID with a JD tag.

    Automatically creates the JD:xx.xx tag and tries to match the JD area
    to an OF folder if no folder is specified.
    """
    from johnnydecimal.omnifocus import (
        create_tag, create_project, list_folders, OmniFocusError,
    )
    from johnnydecimal.policy import is_omnifocus_enabled

    jd = _get_root()
    if not is_omnifocus_enabled(jd.path):
        return {"error": "OmniFocus integration disabled"}

    jd_id = jd.find_by_id(id_str)
    if not jd_id:
        return {"error": f"ID {id_str} not found"}

    project_name = str(jd_id)
    tag_name = f"JD:{id_str}"
    result = {"id": id_str, "project": project_name, "created": [], "error": None}

    try:
        create_tag(tag_name)
        result["created"].append(f"tag:{tag_name}")

        if not folder:
            of_folders = list_folders()
            area_name = jd_id.category.parent._name
            for f in of_folders:
                if area_name.lower() in f["name"].lower():
                    folder = f["name"]
                    break

        create_project(project_name, folder=folder, tags=[tag_name])
        result["created"].append(f"project:{project_name}")
        if folder:
            result["folder"] = folder
    except OmniFocusError as exc:
        result["error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run():
    """Run the MCP server (stdio transport)."""
    mcp.run()
