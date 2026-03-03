"""OmniFocus backend via JXA (JavaScript for Automation).

Thin wrapper around osascript -l JavaScript using direct JXA API calls
on OmniFocus's defaultDocument. Each function builds a JXA script,
runs it via subprocess, and parses the JSON output.

Links to JD via tags: OF projects get JD:xx.xx or JD:xx tags
pointing to where artifacts live in the JD tree.
"""

import json
import subprocess


class OmniFocusError(Exception):
    """Error communicating with OmniFocus."""


def _run_jxa(script: str) -> str:
    """Run a JXA script and return stdout. Raises OmniFocusError on failure."""
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise OmniFocusError(result.stderr.strip() or f"osascript exited {result.returncode}")
    return result.stdout.strip()


def _run_jxa_json(script: str) -> dict | list:
    """Run a JXA script and parse JSON output."""
    raw = _run_jxa(script)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OmniFocusError(f"Bad JSON from osascript: {exc}\n{raw[:200]}")


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def list_jd_tags() -> list[dict]:
    """List all OmniFocus tags matching JD:* pattern.

    Returns list of {name, id, remaining_tasks}.
    """
    script = """\
var app = Application('OmniFocus');
var doc = app.defaultDocument;
var tags = doc.flattenedTags();
var result = [];
for (var i = 0; i < tags.length; i++) {
    var t = tags[i];
    var name = t.name();
    if (/^JD:\\d/.test(name)) {
        result.push({
            name: name,
            id: t.id(),
            remaining_tasks: t.remainingTasks().length
        });
    }
}
JSON.stringify(result);
"""
    return _run_jxa_json(script)


def list_projects_with_jd_tags() -> list[dict]:
    """List OmniFocus projects that have any JD:* tag.

    Returns list of {name, id, status, tags, folder, task_count}.
    """
    script = """\
var app = Application('OmniFocus');
var doc = app.defaultDocument;
var projects = doc.flattenedProjects();
var result = [];
for (var i = 0; i < projects.length; i++) {
    var p = projects[i];
    var tags = p.tags();
    var hasJD = false;
    var tagNames = [];
    for (var j = 0; j < tags.length; j++) {
        var tname = tags[j].name();
        tagNames.push(tname);
        if (/^JD:\\d/.test(tname)) hasJD = true;
    }
    if (hasJD) {
        var folderName = null;
        try { if (p.parentFolder()) folderName = p.parentFolder().name(); } catch(e) {}
        result.push({
            name: p.name(),
            id: p.id(),
            status: p.status().toString(),
            tags: tagNames,
            folder: folderName,
            task_count: p.flattenedTasks().length
        });
    }
}
JSON.stringify(result);
"""
    return _run_jxa_json(script)


def list_folders() -> list[dict]:
    """List all OmniFocus folders.

    Returns list of {name, id, parent_name}.
    """
    script = """\
var app = Application('OmniFocus');
var doc = app.defaultDocument;
var folders = doc.flattenedFolders();
var result = [];
for (var i = 0; i < folders.length; i++) {
    var f = folders[i];
    var parentName = null;
    try { if (f.parentFolder()) parentName = f.parentFolder().name(); } catch(e) {}
    result.push({
        name: f.name(),
        id: f.id(),
        parent_name: parentName
    });
}
JSON.stringify(result);
"""
    return _run_jxa_json(script)


def find_project(name: str) -> dict | None:
    """Find an OmniFocus project by exact name.

    Returns {name, id, status, tags, folder, task_count} or None.
    """
    escaped = name.replace('\\', '\\\\').replace('"', '\\"')
    script = f"""\
var app = Application('OmniFocus');
var doc = app.defaultDocument;
var projects = doc.flattenedProjects();
var found = null;
for (var i = 0; i < projects.length; i++) {{
    if (projects[i].name() === "{escaped}") {{
        found = projects[i];
        break;
    }}
}}
if (found) {{
    var tagNames = [];
    var tags = found.tags();
    for (var j = 0; j < tags.length; j++) tagNames.push(tags[j].name());
    var folderName = null;
    try {{ if (found.parentFolder()) folderName = found.parentFolder().name(); }} catch(e) {{}}
    JSON.stringify({{
        name: found.name(),
        id: found.id(),
        status: found.status().toString(),
        tags: tagNames,
        folder: folderName,
        task_count: found.flattenedTasks().length
    }});
}} else {{
    'null';
}}
"""
    raw = _run_jxa(script)
    if not raw or raw == "null":
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OmniFocusError(f"Bad JSON from osascript: {exc}\n{raw[:200]}")


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def create_tag(tag_name: str):
    """Create an OmniFocus tag. Idempotent — skips if tag already exists.

    E.g. create_tag("JD:26.05")
    """
    escaped = tag_name.replace('\\', '\\\\').replace('"', '\\"')
    script = f"""\
var app = Application('OmniFocus');
var doc = app.defaultDocument;
var tags = doc.flattenedTags();
var exists = false;
for (var i = 0; i < tags.length; i++) {{
    if (tags[i].name() === "{escaped}") {{
        exists = true;
        break;
    }}
}}
if (!exists) {{
    var tag = app.Tag({{name: "{escaped}"}});
    doc.tags.push(tag);
}}
'ok';
"""
    _run_jxa(script)


def create_project(name: str, folder: str | None = None, tags: list[str] | None = None) -> dict:
    """Create an OmniFocus project, optionally in a folder with tags.

    Returns {name, id}.
    """
    escaped_name = name.replace('\\', '\\\\').replace('"', '\\"')

    # Build folder lookup JS
    folder_js = ""
    if folder:
        escaped_folder = folder.replace('\\', '\\\\').replace('"', '\\"')
        folder_js = f"""
var targetFolder = null;
var folders = doc.flattenedFolders();
for (var i = 0; i < folders.length; i++) {{
    if (folders[i].name() === "{escaped_folder}") {{
        targetFolder = folders[i];
        break;
    }}
}}
"""
    else:
        folder_js = "var targetFolder = null;\n"

    # Build tag application JS
    tag_js = ""
    if tags:
        for t in tags:
            escaped_t = t.replace('\\', '\\\\').replace('"', '\\"')
            tag_js += f"""
var tagObj = null;
var allTags = doc.flattenedTags();
for (var ti = 0; ti < allTags.length; ti++) {{
    if (allTags[ti].name() === "{escaped_t}") {{
        tagObj = allTags[ti];
        break;
    }}
}}
if (tagObj) {{
    app.add(tagObj, {{to: proj.tags}});
}}
"""

    script = f"""\
var app = Application('OmniFocus');
var doc = app.defaultDocument;
{folder_js}
var proj = app.Project({{name: "{escaped_name}"}});
if (targetFolder) {{
    targetFolder.projects.push(proj);
}} else {{
    doc.projects.push(proj);
}}
{tag_js}
JSON.stringify({{name: proj.name(), id: proj.id()}});
"""
    return _run_jxa_json(script)


def open_project(name: str):
    """Open a project in OmniFocus by selecting it in the front window."""
    escaped = name.replace('\\', '\\\\').replace('"', '\\"')
    script = f"""\
var app = Application('OmniFocus');
app.activate();
var doc = app.defaultDocument;
var projects = doc.flattenedProjects();
for (var i = 0; i < projects.length; i++) {{
    if (projects[i].name() === "{escaped}") {{
        var win = doc.documentWindows[0];
        win.selectedViewModeProjectsSidebar = projects[i];
        break;
    }}
}}
"""
    _run_jxa(script)


def tag_project(project_name: str, tag_name: str):
    """Add a JD tag to an existing OmniFocus project."""
    escaped_proj = project_name.replace('\\', '\\\\').replace('"', '\\"')
    escaped_tag = tag_name.replace('\\', '\\\\').replace('"', '\\"')
    script = f"""\
var app = Application('OmniFocus');
var doc = app.defaultDocument;

// Find project
var proj = null;
var projects = doc.flattenedProjects();
for (var i = 0; i < projects.length; i++) {{
    if (projects[i].name() === "{escaped_proj}") {{
        proj = projects[i];
        break;
    }}
}}
if (!proj) throw new Error("Project not found: {escaped_proj}");

// Find or create tag
var tag = null;
var tags = doc.flattenedTags();
for (var i = 0; i < tags.length; i++) {{
    if (tags[i].name() === "{escaped_tag}") {{
        tag = tags[i];
        break;
    }}
}}
if (!tag) {{
    tag = app.Tag({{name: "{escaped_tag}"}});
    doc.tags.push(tag);
}}

// Add tag if not already present
var projTags = proj.tags();
var hasTag = false;
for (var i = 0; i < projTags.length; i++) {{
    if (projTags[i].name() === "{escaped_tag}") {{
        hasTag = true;
        break;
    }}
}}
if (!hasTag) {{
    app.add(tag, {{to: proj.tags}});
}}
'ok';
"""
    _run_jxa(script)
