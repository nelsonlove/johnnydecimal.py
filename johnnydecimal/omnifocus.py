"""OmniFocus backend via JXA (JavaScript for Automation).

Thin wrapper around osascript -l JavaScript using OmniFocus's
evaluateJavascript bridge. Each function builds a JXA script,
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
var result = app.evaluateJavascript(`
    JSON.stringify(flattenedTags.filter(t =>
        /^JD:\\\\d/.test(t.name)
    ).map(t => ({
        name: t.name,
        id: t.id.primaryKey,
        remaining_tasks: t.remainingTasks.length
    })))
`);
result;
"""
    return _run_jxa_json(script)


def list_projects_with_jd_tags() -> list[dict]:
    """List OmniFocus projects that have any JD:* tag.

    Returns list of {name, id, status, tags, folder, task_count}.
    """
    script = """\
var app = Application('OmniFocus');
var result = app.evaluateJavascript(`
    JSON.stringify(flattenedProjects.filter(p =>
        p.tags.some(t => /^JD:\\\\d/.test(t.name))
    ).map(p => ({
        name: p.name,
        id: p.id.primaryKey,
        status: p.status.name,
        tags: p.tags.map(t => t.name),
        folder: p.parentFolder ? p.parentFolder.name : null,
        task_count: p.flattenedTasks.length
    })))
`);
result;
"""
    return _run_jxa_json(script)


def list_folders() -> list[dict]:
    """List all OmniFocus folders.

    Returns list of {name, id, parent_name}.
    """
    script = """\
var app = Application('OmniFocus');
var result = app.evaluateJavascript(`
    JSON.stringify(flattenedFolders.map(f => ({
        name: f.name,
        id: f.id.primaryKey,
        parent_name: f.parentFolder ? f.parentFolder.name : null
    })))
`);
result;
"""
    return _run_jxa_json(script)


def find_project(name: str) -> dict | None:
    """Find an OmniFocus project by exact name.

    Returns {name, id, status, tags, folder, task_count} or None.
    """
    escaped = name.replace('\\', '\\\\').replace('"', '\\"')
    script = f"""\
var app = Application('OmniFocus');
var result = app.evaluateJavascript(`
    var matches = flattenedProjects.filter(p => p.name === "{escaped}");
    matches.length ? JSON.stringify({{
        name: matches[0].name,
        id: matches[0].id.primaryKey,
        status: matches[0].status.name,
        tags: matches[0].tags.map(t => t.name),
        folder: matches[0].parentFolder ? matches[0].parentFolder.name : null,
        task_count: matches[0].flattenedTasks.length
    }}) : "null"
`);
result;
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
app.evaluateJavascript(`
    var existing = flattenedTags.find(t => t.name === "{escaped}");
    if (!existing) {{
        var tag = new Tag("{escaped}");
        library.ending.tags.push(tag);
    }}
`);
'ok';
"""
    _run_jxa(script)


def create_project(name: str, folder: str | None = None, tags: list[str] | None = None) -> dict:
    """Create an OmniFocus project, optionally in a folder with tags.

    Returns {name, id}.
    """
    escaped_name = name.replace('\\', '\\\\').replace('"', '\\"')

    folder_js = "null"
    if folder:
        escaped_folder = folder.replace('\\', '\\\\').replace('"', '\\"')
        folder_js = f'flattenedFolders.find(f => f.name === "{escaped_folder}")'

    tags_js = "[]"
    if tags:
        tag_filters = ", ".join(
            f'flattenedTags.find(t => t.name === "{t.replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))}")'
            for t in tags
        )
        tags_js = f"[{tag_filters}].filter(Boolean)"

    script = f"""\
var app = Application('OmniFocus');
var result = app.evaluateJavascript(`
    var folder = {folder_js};
    var proj = new Project("{escaped_name}");
    if (folder) {{
        folder.ending.projects.push(proj);
    }} else {{
        library.ending.projects.push(proj);
    }}
    var tagObjs = {tags_js};
    tagObjs.forEach(function(t) {{ proj.addTag(t); }});
    JSON.stringify({{ name: proj.name, id: proj.id.primaryKey }})
`);
result;
"""
    return _run_jxa_json(script)


def open_project(name: str):
    """Open a project in OmniFocus by selecting it in the front window."""
    escaped = name.replace('\\', '\\\\').replace('"', '\\"')
    script = f"""\
var app = Application('OmniFocus');
app.activate();
app.evaluateJavascript(`
    var proj = flattenedProjects.find(p => p.name === "{escaped}");
    if (proj) {{
        document.windows[0].selectObjects([proj]);
    }}
`);
"""
    _run_jxa(script)


def tag_project(project_name: str, tag_name: str):
    """Add a JD tag to an existing OmniFocus project."""
    escaped_proj = project_name.replace('\\', '\\\\').replace('"', '\\"')
    escaped_tag = tag_name.replace('\\', '\\\\').replace('"', '\\"')
    script = f"""\
var app = Application('OmniFocus');
app.evaluateJavascript(`
    var proj = flattenedProjects.find(p => p.name === "{escaped_proj}");
    if (!proj) throw new Error("Project not found: {escaped_proj}");
    var tag = flattenedTags.find(t => t.name === "{escaped_tag}");
    if (!tag) {{
        tag = new Tag("{escaped_tag}");
        library.ending.tags.push(tag);
    }}
    if (!proj.tags.some(t => t.name === "{escaped_tag}")) {{
        proj.addTag(tag);
    }}
`);
'ok';
"""
    _run_jxa(script)
