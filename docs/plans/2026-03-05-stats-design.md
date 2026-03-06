# jd stats Design

## Summary

`jd stats` — no arguments, no flags. Scans the JD tree and prints a system-wide summary.

## Output Sections

1. **Structure** — area/category/ID counts, archived count
2. **Storage** — total size, top 3 largest IDs
3. **File Types** — top 10 extensions by count
4. **Depth** — average/max nesting depth within IDs
5. **Age** — oldest/newest IDs by filesystem mtime
6. **Health** — broken symlinks, orphan dirs, empty categories

## Implementation

- All logic in `cli.py` — read-only, aggregates existing model data + `os.stat`/`Path.rglob`
- Uses `jd.all_ids()`, `jd.find_orphans()`, `jd.broken_symlinks` from JDSystem
- File type/depth/size: walk each ID dir with `Path.rglob("*")`
- MCP tool: `jd_stats()` returning the same data as a dict
- Smoke test: basic output format, no crashes on empty tree
