# Staging Design

## Summary

Surface JD items on the Desktop for active work, then return them when done. Two layers: low-level tagging and high-level stage/unstage with symlinks.

## Commands

### `jd tag add <id> <path>`

Tag a file or directory with `JD:xx.xx` Finder tag. Does not move anything.

### `jd tag remove <path>`

Strip the `JD:*` Finder tag from a file or directory.

### `jd stage <id>`

1. Resolve the JD ID to its directory.
2. For each top-level item (file/dir) in the ID dir:
   - Add Finder tag `JD:xx.xx`.
   - Move to `~/Desktop/xx.xx <original-name>` (ID prefix avoids collisions).
   - Leave a symlink at the original location pointing to the Desktop path.
3. Print what was staged. Skip `.DS_Store` and dotfiles.

### `jd unstage [id]`

1. Scan `~/Desktop` for items with `JD:*` Finder tags. If `id` is given, filter to that ID only.
2. For each matched item:
   - Parse the `JD:xx.xx` tag to determine the target ID dir.
   - If a symlink exists in the ID dir pointing to this item, remove it.
   - If the filename is ID-prefixed (`xx.xx name`), strip the prefix.
   - Move the item back to the ID dir.
   - Remove the `JD:xx.xx` Finder tag.
3. Print what was unstaged.

Handles both staged items (symlinks + prefix) and manually tagged items (no symlink, no prefix) uniformly.

## Finder Tags

- Format: `JD:26.05` — consistent with OmniFocus `JD:` tag convention.
- Stored in `com.apple.metadata:_kMDItemUserTags` extended attribute (binary plist of string array).
- Read/write via `subprocess` calling `/usr/bin/xattr` + `plistlib` for parsing. No external dependencies.

## Flags

- `--dry-run` / `-n` on `stage` and `unstage` (consistent with `mv` and `restore`).

## Edge Cases

- **Desktop collision**: ID prefix (`26.05 report.pdf`) prevents name clashes.
- **Already staged**: If symlinks already exist in the ID dir pointing to Desktop, skip or warn.
- **Empty ID dir**: After staging all items, the dir contains only symlinks — fine.
- **Manually tagged items on Desktop**: `unstage` handles these — no symlink to clean up, no prefix to strip, just move to ID dir.
- **Multiple JD tags on one item**: Use the first `JD:*` tag found (shouldn't normally happen).
