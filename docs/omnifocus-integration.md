# OmniFocus ↔ Johnny Decimal Integration

## Core Principle

JD and OF serve different purposes. Don't make them mirror each other.

- **JD** = where things *are* (filing, artifacts, reference)
- **OF** = what you need to *do* (actions, projects, deadlines)

They link via tags, not structure.

## Hierarchy Mapping

```
OF Folder  = JD Area     (20-29 Family)
  OF Folder  = JD Category  ← when ongoing/multi-project (26 Recipes, 22 Mom)
    OF Project = whatever makes sense
  OF Project = JD Category  ← when single finite thing (25 Animals)
```

- **Areas** are always OF folders
- **Categories** are the decision point: folder if complex, project if simple
- **IDs** may or may not correspond to OF projects — depends on whether there's active work

## Tagging Convention

OF projects get a `JD:xx.xx` or `JD:xx` tag linking to where artifacts live.

```
OF: "Motion for Temporary Orders" [JD:26.17]
  - Review draft from Meghan
  - Gather financial docs (see 40-49)
  - Court date 3/15
```

Projects are cross-cutting. A single OF project may reference multiple JD locations. That's fine — the tag points to the *primary* artifact location, notes can reference others.

## Validation Rules (`jd validate --omnifocus`)

1. **OF projects with JD tags** → does the tagged ID/category actually exist?
2. **Active JD IDs with content** → is there an OF project tracking it? (advisory, not error)
3. **Orphan OF projects** → no JD tag (flag for review, not necessarily wrong)
4. **OF folder structure** → do top-level folders roughly match JD areas? (advisory)

## Email → OF → JD Workflow

The closed loop for processing email:

1. **Extract artifacts** → `jd file` attachments to appropriate JD ID
2. **Extract actions** → create OF task/project with `JD:xx.xx` tag and context
3. **Archive email** → it's been processed, search if you need it again

Agents (Kin, Rex) can do steps 1-3 for routine emails. Human triage for anything ambiguous.

## What NOT to Do

- Don't create OF projects for every JD ID
- Don't create JD IDs for every OF project
- Don't try to sync folder hierarchies between them
- Don't force emails into JD — emails stay in email, artifacts get filed
