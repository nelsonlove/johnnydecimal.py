"""Apple Notes backend via JXA (JavaScript for Automation).

Thin wrapper around osascript -l JavaScript. Each function builds a JXA
script, runs it via subprocess, and parses the JSON output.
"""

import json
import subprocess


class NotesError(Exception):
    """Error communicating with Apple Notes."""


def _run_jxa(script: str) -> str:
    """Run a JXA script and return stdout. Raises NotesError on failure."""
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise NotesError(result.stderr.strip() or f"osascript exited {result.returncode}")
    return result.stdout.strip()


def _run_jxa_json(script: str) -> dict | list:
    """Run a JXA script and parse JSON output."""
    raw = _run_jxa(script)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NotesError(f"Bad JSON from osascript: {exc}\n{raw[:200]}")


def _folder_chain_js(path: list[str], account: str = "iCloud") -> str:
    """Build JXA expression to navigate to a nested folder.

    E.g. ["20-29 Projects", "26 Recipes"] →
    app.accounts.byName("iCloud").folders.byName("20-29 Projects").folders.byName("26 Recipes")
    """
    chain = f'app.accounts.byName("{account}")'
    for segment in path:
        escaped = segment.replace('\\', '\\\\').replace('"', '\\"')
        chain += f'.folders.byName("{escaped}")'
    return chain


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def list_folders(account: str = "iCloud") -> list[dict]:
    """List all folders with name, id, parent_name, parent_id. Flat list."""
    script = f"""\
ObjC.import('Foundation');
var app = Application('Notes');
var acct = app.accounts.byName("{account}");
var result = [];

function walkFolders(container, parentName, parentId) {{
    var folders = container.folders();
    for (var i = 0; i < folders.length; i++) {{
        var f = folders[i];
        var info = {{
            name: f.name(),
            id: f.id(),
            parent_name: parentName,
            parent_id: parentId
        }};
        result.push(info);
        walkFolders(f, f.name(), f.id());
    }}
}}

walkFolders(acct, null, null);
JSON.stringify(result);
"""
    return _run_jxa_json(script)


def list_notes(folder_path: list[str], account: str = "iCloud") -> list[dict]:
    """List notes in a folder specified by path segments.

    Returns list of {name, id, creation_date, modification_date}.
    """
    chain = _folder_chain_js(folder_path, account)
    script = f"""\
ObjC.import('Foundation');
var app = Application('Notes');
var folder = {chain};
var notes = folder.notes();
var result = [];
for (var i = 0; i < notes.length; i++) {{
    var n = notes[i];
    result.push({{
        name: n.name(),
        id: n.id(),
        creation_date: n.creationDate().toISOString(),
        modification_date: n.modificationDate().toISOString()
    }});
}}
JSON.stringify(result);
"""
    return _run_jxa_json(script)


def folder_exists(path: list[str], account: str = "iCloud") -> bool:
    """Check if a nested folder path exists."""
    chain = _folder_chain_js(path, account)
    script = f"""\
var app = Application('Notes');
try {{
    var f = {chain};
    f.name();
    'true';
}} catch(e) {{
    'false';
}}
"""
    return _run_jxa(script) == "true"


def note_exists(folder_path: list[str], name: str, account: str = "iCloud") -> bool:
    """Check if a note with the given name exists in a folder."""
    chain = _folder_chain_js(folder_path, account)
    escaped_name = name.replace('\\', '\\\\').replace('"', '\\"')
    script = f"""\
var app = Application('Notes');
try {{
    var folder = {chain};
    var notes = folder.notes();
    var found = false;
    for (var i = 0; i < notes.length; i++) {{
        if (notes[i].name() === "{escaped_name}") {{
            found = true;
            break;
        }}
    }}
    found ? 'true' : 'false';
}} catch(e) {{
    'false';
}}
"""
    return _run_jxa(script) == "true"


def create_folder(path: list[str], account: str = "iCloud"):
    """Create a folder at the given path, including intermediate parents. Idempotent."""
    for i in range(1, len(path) + 1):
        partial = path[:i]
        if not folder_exists(partial, account):
            parent_chain = _folder_chain_js(partial[:-1], account) if len(partial) > 1 else f'app.accounts.byName("{account}")'
            escaped_name = partial[-1].replace('\\', '\\\\').replace('"', '\\"')
            script = f"""\
var app = Application('Notes');
var parent = {parent_chain};
var folder = app.Folder({{name: "{escaped_name}"}});
parent.folders.push(folder);
"""
            _run_jxa(script)


def create_note(folder_path: list[str], name: str, body: str = "", account: str = "iCloud"):
    """Create a note in a folder."""
    chain = _folder_chain_js(folder_path, account)
    escaped_name = name.replace('\\', '\\\\').replace('"', '\\"')
    escaped_body = body.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
    html_body = f"<h1>{escaped_name}</h1>" if not escaped_body else f"<h1>{escaped_name}</h1><br>{escaped_body}"
    script = f"""\
var app = Application('Notes');
var folder = {chain};
var note = app.Note({{name: "{escaped_name}", body: "{html_body}"}});
folder.notes.push(note);
"""
    _run_jxa(script)


def open_note(folder_path: list[str], name: str, account: str = "iCloud"):
    """Open a specific note in Notes.app."""
    chain = _folder_chain_js(folder_path, account)
    escaped_name = name.replace('\\', '\\\\').replace('"', '\\"')
    script = f"""\
var app = Application('Notes');
app.activate();
var folder = {chain};
var notes = folder.notes();
for (var i = 0; i < notes.length; i++) {{
    if (notes[i].name() === "{escaped_name}") {{
        app.show(notes[i]);
        break;
    }}
}}
"""
    _run_jxa(script)


def build_tree(account: str = "iCloud") -> dict:
    """Build the full folder/note hierarchy as a nested dict.

    Returns {folder_name: {"folders": {...}, "notes": [name, ...]}}.
    """
    script = f"""\
ObjC.import('Foundation');
var app = Application('Notes');
var acct = app.accounts.byName("{account}");

function walkFolder(container) {{
    var result = {{}};
    var folders = container.folders();
    for (var i = 0; i < folders.length; i++) {{
        var f = folders[i];
        var notes = f.notes();
        var noteNames = [];
        for (var j = 0; j < notes.length; j++) {{
            noteNames.push(notes[j].name());
        }}
        result[f.name()] = {{
            folders: walkFolder(f),
            notes: noteNames
        }};
    }}
    return result;
}}

JSON.stringify(walkFolder(acct));
"""
    return _run_jxa_json(script)
