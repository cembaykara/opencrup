#!/usr/bin/env python3
"""
OpenCrup — a small local web UI to browse and manage AI conversations (opencode + Cursor).

Zero dependencies — Python 3 standard library only (http.server + sqlite3).

    ./start.sh            # http://127.0.0.1:4321
    PORT=8080 ./start.sh  # custom port

Environment:
    PORT         HTTP port (default 4321)
    HOST         bind address (default 127.0.0.1)
    OPENCODE_DB  database path (default ~/.local/share/opencode/opencode.db)
"""
import datetime
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import sqlite3
import string
import subprocess
import time
import uuid
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
DB_PATH = Path(
    os.environ.get("OPENCODE_DB")
    or (Path.home() / ".local" / "share" / "opencode" / "opencode.db")
)
PORT = int(os.environ.get("PORT", "4321"))
HOST = os.environ.get("HOST", "127.0.0.1")
CURSOR_PROJECTS_DIR = Path(
    os.environ.get("CURSOR_PROJECTS")
    or (Path.home() / ".cursor" / "projects")
)

# --- persistent local config (custom source paths) --------------------------
CONFIG_PATH = Path.home() / ".opencrup" / "config.json"


def _load_config():
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception:
        return {}


def _save_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def _cursor_appdata_dir():
    """VS Code-convention app-data dir (holds User/, AgentStores/), per OS.

    Cursor is a VS Code fork, so its app data follows the same per-OS layout:
    macOS ~/Library/Application Support/Cursor, Windows %APPDATA%/Cursor,
    Linux ~/.config/Cursor.
    """
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        return home / "Library" / "Application Support" / "Cursor"
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Cursor" if appdata else home / "AppData" / "Roaming" / "Cursor"
    return home / ".config" / "Cursor"


def cursor_projects_dir():
    """Effective Cursor projects dir: saved override > env > ~/.cursor/projects."""
    cfg = _load_config()
    if cfg.get("cursor_projects"):
        return Path(cfg["cursor_projects"])
    return CURSOR_PROJECTS_DIR

B62 = string.ascii_lowercase + string.ascii_uppercase + string.digits
ADJ = ["clever", "cosmic", "mighty", "neon", "eager", "brave", "silent", "rapid",
       "lucky", "crimson", "amber", "frosty", "wild", "quiet", "solar", "lunar"]
NOUN = ["mountain", "nebula", "island", "wolf", "squid", "comet", "otter", "falcon",
        "river", "peak", "ember", "willow", "harbor", "canyon", "aurora", "breeze"]

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def now_ms():
    return int(time.time() * 1000)


def rand_base62(n):
    return "".join(secrets.choice(B62) for _ in range(n))


def random_slug():
    return f"{secrets.choice(ADJ)}-{secrets.choice(NOUN)}"


def detect_version():
    """The installed opencode version, read live from `opencode --version`.

    Returns e.g. "2.0.29", or "unknown" when opencode isn't on PATH. We don't
    pin to a specific version — whatever is installed (and anything newer) works.
    """
    try:
        out = subprocess.run(["opencode", "--version"], capture_output=True,
                             text=True, timeout=5)
        m = re.search(r"v?(\d+\.\d+\.\d+)", out.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "unknown"


OPENCODE_VERSION = detect_version()


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# API: projects
# ---------------------------------------------------------------------------
def list_projects(conn):
    # Only projects that still own at least one session (empty ones are hidden)
    cur = conn.execute(
        """SELECT p.id, p.worktree, p.name, p.time_active,
                  (SELECT COUNT(*) FROM session_v2 s WHERE s.project_id = p.id) AS session_count
           FROM project p
           WHERE (SELECT COUNT(*) FROM session_v2 s WHERE s.project_id = p.id) > 0
           ORDER BY p.time_active DESC, p.worktree"""
    )
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# API: sessions
# ---------------------------------------------------------------------------
def list_sessions(conn, project_id=None, q=None, include_archived=False, limit="200"):
    where = ["1=1"]
    params = []
    if project_id:
        where.append("s.project_id = ?")
        params.append(project_id)
    if not include_archived:
        where.append("s.time_archived IS NULL")
    if q:
        where.append("(s.title LIKE ? OR s.id LIKE ? OR s.directory LIKE ? OR s.slug LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like, like])
    try:
        params.append(int(limit))
    except (TypeError, ValueError):
        params.append(200)
    cur = conn.execute(
        f"""SELECT s.id, s.project_id, s.parent_id, s.slug, s.directory, s.title, s.agent,
                   s.model, s.cost, s.tokens_input, s.tokens_output, s.tokens_reasoning,
                   s.time_created, s.time_updated, s.time_archived, s.version,
                   p.worktree AS project_worktree,
                   (SELECT COUNT(*) FROM session_message m WHERE m.session_id = s.id) AS message_count
            FROM session_v2 s
            LEFT JOIN project p ON p.id = s.project_id
            WHERE {' AND '.join(where)}
            ORDER BY s.time_updated DESC
            LIMIT ?""",
        params,
    )
    return [dict(r) for r in cur.fetchall()]


def get_session(conn, sid):
    session = conn.execute(
        """SELECT s.*, p.worktree AS project_worktree
           FROM session_v2 s
           LEFT JOIN project p ON p.id = s.project_id
           WHERE s.id = ?""",
        (sid,),
    ).fetchone()
    if not session:
        raise HttpError(404, "session not found")
    session = dict(session)
    messages = conn.execute(
        """SELECT id, type, seq, time_created, time_updated, data
           FROM session_message
           WHERE session_id = ?
           ORDER BY seq""",
        (sid,),
    ).fetchall()
    for m in messages:
        m = dict(m)
        try:
            m["data"] = json.loads(m["data"])
        except (json.JSONDecodeError, TypeError):
            m["data"] = {"text": m["data"]}
        session.setdefault("messages", []).append(m)
    return session


def resolve_project(conn, directory):
    # A directory can have duplicate project rows (opencode recreates them);
    # the real app uses the most recent, so match on that, not the first row.
    row = conn.execute(
        "SELECT id FROM project WHERE worktree = ? ORDER BY time_created DESC",
        (directory,)).fetchone()
    if row:
        return row["id"]
    pid = secrets.token_hex(16)
    now = now_ms()
    conn.execute(
        """INSERT INTO project
           (id, worktree, vcs, name, icon_url, icon_url_override, icon_color,
            time_created, time_updated, time_initialized, time_active, sandboxes, commands)
           VALUES (?, ?, NULL, NULL, NULL, NULL, NULL, ?, ?, ?, 0, '[]', NULL)""",
        (pid, directory, now, now, now),
    )
    conn.commit()
    return pid


# Directories to skip while scanning for a path match (heavy / noisy), per platform.
def _scan_prune():
    prune = {
        "node_modules", ".git", ".hg", ".svn", ".cache", "__pycache__",
        ".venv", "venv", ".npm", ".cargo", ".rustup", ".tox",
        ".mypy_cache", ".pytest_cache",
    }
    system = platform.system()
    if system == "Darwin":
        prune |= {"Library", ".Trash", "Applications"}
    elif system == "Windows":
        prune |= {
            "AppData", "Windows", "Program Files", "Program Files (x86)",
            "ProgramData", "$Recycle.Bin", "System Volume Information",
            "PerfLogs", "Recovery",
        }
    return prune


def _scan_roots():
    """Root directories to scan for a path match, per platform.

    macOS/Linux: the user's home. Windows: the root of every fixed drive, so
    projects on D:\\, E:\\, ... are found too (not just C:\\Users\\<you>).
    """
    if platform.system() != "Windows":
        return [str(Path.home())]
    roots = []
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if mask & (1 << i):
                drive = f"{letter}:\\"
                try:
                    if ctypes.windll.kernel32.GetDriveTypeW(drive) == 2:  # DRIVE_FIXED
                        roots.append(drive)
                except Exception:
                    pass
    except Exception:
        pass
    return roots or [str(Path.home())]


def _immediate_children(path, limit=200):
    try:
        with os.scandir(path) as it:
            return [e.name for e in it][:limit]
    except OSError:
        return []


def resolve_dir(name, children=None):
    """Resolve a full directory path from a basename + child-name fingerprint.

    The browser's native directory picker only exposes the folder name, so we
    scan the home tree (or every fixed drive on Windows) for a directory whose
    name matches and whose immediate children best match the fingerprint.
    Returns the best path or None.
    """
    want = set(children or [])
    prune = _scan_prune()
    matches = []  # (score, depth, path)
    seen = 0
    for root in _scan_roots():
        for dirpath, dirnames, _ in os.walk(root, topdown=True):
            dirnames[:] = [d for d in dirnames if d not in prune]
            if os.path.basename(dirpath) == name:
                kids = set(_immediate_children(dirpath))
                if want:
                    union = len(want | kids) or 1
                    score = len(want & kids) / union
                else:
                    score = 0.5
                matches.append((score, dirpath.count(os.sep), dirpath))
            seen += 1
            if seen > 200000:
                break
        if seen > 200000:
            break
    if not matches:
        return None
    matches.sort(key=lambda m: (-m[0], m[1]))
    return matches[0][2]


def detect_sources():
    """Presence + location + count for each source, for the home screen."""
    # opencode
    oc_found = DB_PATH.is_file()
    oc_count = 0
    if oc_found:
        try:
            with closing(connect()) as conn:
                oc_count = conn.execute("SELECT count(*) FROM session_v2").fetchone()[0]
        except Exception:
            oc_count = 0
    # cursor (agent dir ~/.cursor, or the VS Code-convention app-data dir)
    agent = Path.home() / ".cursor"
    cur_found = agent.is_dir() or _cursor_appdata_dir().is_dir()
    cur_count = sum(1 for _ in _iter_cursor_transcripts()) if cur_found else 0
    # claude code (~/.claude/projects, or $CLAUDE_CONFIG_DIR/projects)
    claude_dir = _claude_projects_dir()
    claude_found = claude_dir.is_dir()
    claude_count = sum(1 for _ in _iter_claude_transcripts()) if claude_found else 0
    return {
        "opencode": {"found": oc_found, "path": str(DB_PATH), "count": oc_count},
        "cursor": {"found": cur_found, "path": str(cursor_projects_dir()), "count": cur_count},
        "claude": {"found": claude_found, "path": str(claude_dir), "count": claude_count},
    }


def add_cursor_source(path):
    """Save a manually-picked Cursor location (from the home "+" button)."""
    p = Path(path).expanduser()
    if (p / "projects").is_dir():
        projects = p / "projects"  # picked the agent dir (~/.cursor)
    elif p.is_dir() and any(c.is_dir() and (c / "agent-transcripts").is_dir() for c in p.iterdir()):
        projects = p  # picked the projects dir directly
    else:
        projects = p / "projects"  # best guess
    cfg = _load_config()
    cfg["cursor_projects"] = str(projects)
    _save_config(cfg)
    _CURSOR_CACHE.clear()
    return detect_sources()["cursor"]


def create_session(conn, body):
    directory = body.get("directory")
    if not isinstance(directory, str) or not directory:
        raise HttpError(400, "directory is required")
    now = now_ms()
    project_id = resolve_project(conn, directory)
    sid = "ses_" + rand_base62(26)
    model = body.get("model")
    model_str = model if isinstance(model, str) else (json.dumps(model) if model else None)
    conn.execute(
        """INSERT INTO session_v2
           (id, project_id, slug, directory, title, version, agent, model, time_created, time_updated)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sid, project_id, random_slug(), directory, body.get("title") or "Untitled session",
         OPENCODE_VERSION, body.get("agent") or "build", model_str, now, now),
    )
    conn.commit()
    return get_session(conn, sid)


def update_session(conn, sid, patch):
    existing = conn.execute("SELECT * FROM session_v2 WHERE id = ?", (sid,)).fetchone()
    if not existing:
        raise HttpError(404, "session not found")
    old_project_id = existing["project_id"]
    sets = []
    params = []
    if "title" in patch:
        sets.append("title = ?")
        params.append(str(patch["title"]))
    if "directory" in patch:
        sets.append("directory = ?")
        params.append(str(patch["directory"]))
        # re-home the session into the project that owns the new directory
        # (creates the project row if the directory is new)
        sets.append("project_id = ?")
        params.append(resolve_project(conn, str(patch["directory"])))
    if "agent" in patch:
        sets.append("agent = ?")
        params.append(str(patch["agent"]) if patch["agent"] else None)
    if "model" in patch:
        model = patch["model"]
        sets.append("model = ?")
        params.append(model if isinstance(model, str) else (json.dumps(model) if model else None))
    if "archived" in patch:
        sets.append("time_archived = ?")
        params.append(now_ms() if patch["archived"] else None)
    if not sets:
        raise HttpError(400, "no fields to update")
    sets.append("time_updated = ?")
    params.append(now_ms())
    params.append(sid)
    conn.execute(f"UPDATE session_v2 SET {', '.join(sets)} WHERE id = ?", params)
    # If the move left the source project with no sessions, purge its row
    if "directory" in patch and old_project_id:
        n = conn.execute(
            "SELECT COUNT(*) FROM session_v2 WHERE project_id = ?", (old_project_id,)
        ).fetchone()[0]
        if n == 0:
            conn.execute("DELETE FROM project WHERE id = ?", (old_project_id,))
    conn.commit()
    return get_session(conn, sid)


def delete_session(conn, sid):
    existing = conn.execute("SELECT id FROM session_v2 WHERE id = ?", (sid,)).fetchone()
    if not existing:
        raise HttpError(404, "session not found")
    conn.execute("DELETE FROM session_v2 WHERE id = ?", (sid,))  # messages cascade
    conn.commit()
    return {"deleted": sid}


def bulk_sessions(conn, body):
    action = body.get("action")
    ids = body.get("ids")
    if not isinstance(ids, list) or not ids:
        raise HttpError(400, "ids must be a non-empty array")
    if action not in ("delete", "archive", "unarchive"):
        raise HttpError(400, "action must be one of: delete, archive, unarchive")
    now = now_ms()
    done = []
    for sid in ids:
        existing = conn.execute("SELECT id FROM session_v2 WHERE id = ?", (sid,)).fetchone()
        if not existing:
            continue
        if action == "delete":
            conn.execute("DELETE FROM session_v2 WHERE id = ?", (sid,))  # messages cascade
        else:
            conn.execute(
                "UPDATE session_v2 SET time_archived = ?, time_updated = ? WHERE id = ?",
                (now if action == "archive" else None, now, sid),
            )
        done.append(sid)
    conn.commit()
    return {"action": action, "affected": len(done), "ids": done}


def _cursor_root_fingerprint(cuuid, title, recency, is_archived, message_ids, branches):
    """Replicate Cursor's root_fingerprint (conversationSearchMain.js `$7`).

    SHA-256 over the JSON of [conversationId, title, recency, isArchived,
    messageIds, branches, ...]. This is the gate Cursor's reconciliation uses
    to decide whether a locally-injected row survives; matching it means the
    real app keeps the conversation instead of cleaning it up.
    """
    arr = [cuuid, title, recency, is_archived, message_ids, branches]
    return hashlib.sha256(
        json.dumps(arr, separators=(",", ":")).encode("utf-8", "replace")
    ).hexdigest()


def _decode_folder_uri(folder):
    """Decode a workspace.json `folder` URI to a Path.

    Handles the Windows form `file:///c%3A/Users/x/proj` (percent-encoded drive
    letter): after unquoting it is `/c:/Users/x/proj`, and Windows' Path would
    misread the leading `/c:` as a UNC path (`\\c:\\...`). Strip the leading
    slash before a drive letter so it resolves to `c:\\Users\\x\\proj`."""
    if not folder:
        return None
    path = unquote(urlparse(folder).path) if folder.startswith("file://") else folder
    if not path:
        return None
    if platform.system() == "Windows" and len(path) >= 3 \
            and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return Path(path)


def _cursor_workspaces():
    """Every Cursor workspace: hash-dir name -> (state.vscdb Path, folder Path).

    The hash dir under workspaceStorage is the workspace id the app keys
    chats by (see the composerHeaders table).
    """
    out = {}
    ws_root = _cursor_appdata_dir() / "User" / "workspaceStorage"
    if not ws_root.is_dir():
        return out
    for wj in ws_root.glob("*/workspace.json"):
        try:
            d = json.loads(wj.read_text())
        except (OSError, ValueError):
            continue
        folder = d.get("folder") or d.get("workspace") or ""
        cand = _decode_folder_uri(folder)
        if cand is None:
            continue
        out[wj.parent.name] = (wj.parent / "state.vscdb", cand)
    return out


def _cursor_workspace_db(directory):
    """Find the workspace state.vscdb for a project directory.

    Cursor keys each workspace by a hash; workspace.json holds the folder URI.
    Returns the state.vscdb Path, or None if the project has no workspace yet
    (in which case the chat registers under the app's 'empty-window' bucket).
    """
    target = Path(directory).expanduser()
    try:
        target = target.resolve()
    except OSError:
        pass
    # Windows paths are case-insensitive, so compare decoded, resolved forms
    # case-insensitively there; elsewhere a plain resolved comparison works.
    win = platform.system() == "Windows"
    norm = (lambda p: str(p).lower()) if win else (lambda p: str(p))
    target_n = norm(target)
    for _ws_id, (db, folder) in _cursor_workspaces().items():
        if norm(folder) == target_n:
            return db
        try:
            if norm(folder.resolve()) == target_n:
                return db
        except OSError:
            continue
    return None


def _cursor_workspace_id(directory):
    """The workspace id (storage hash) a chat registers under for `directory`,
    or the app's 'empty-window' bucket when the folder was never opened in Cursor."""
    target = Path(directory).expanduser()
    try:
        target = target.resolve()
    except OSError:
        pass
    win = platform.system() == "Windows"
    norm = (lambda p: str(p).lower()) if win else (lambda p: str(p))
    target_n = norm(target)
    for ws_id, (_db, folder) in _cursor_workspaces().items():
        if norm(folder) == target_n:
            return ws_id
        try:
            if norm(folder.resolve()) == target_n:
                return ws_id
        except OSError:
            continue
    return "empty-window"


def _cursor_uri_obj(directory):
    """The VS Code-style URI object ($mid:1 shape) the app uses to name a folder.

    On Windows the drive letter is lowercased in every form, matching what the
    app itself stores (path '/c:/Users/...', fsPath 'c:\\Users\\...',
    external 'file:///c%3A/Users/...').
    """
    p = str(Path(directory).expanduser())
    try:
        p = str(Path(p).resolve())
    except OSError:
        pass
    win = platform.system() == "Windows"
    if win and len(p) >= 2 and p[1] == ":":
        drive = p[0].lower()
        slash = drive + ":" + p[2:].replace("\\", "/").replace(" ", "%20")
        fs = p[0].lower() + p[1:]
        path = "/" + drive + ":" + p[2:].replace("\\", "/")
        ext = "file:///" + drive + "%3A" + p[2:].replace("\\", "/").replace(" ", "%20")
    else:
        slash = p.replace("\\", "/")
        fs = slash
        path = slash
        ext = "file://" + slash
    return {"$mid": 1, "fsPath": fs, "_sep": 1 if win else 2,
            "external": ext, "path": path, "scheme": "file"}


def _iso_ms(ms):
    """epoch millis -> the ISO string ('2026-10-17T23:45:11.308Z') the app stores."""
    dt = datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def _cursor_composer_defaults(cuuid, title, headers, now_ms, ws_id, uri):
    """A full composer record in the shape the installed app expects (_v: 18 on
    Cursor 3.x; the field set mirrors a real agent-mode composer exactly).

    Older records are rejected by the deserializer and the chat opens blank,
    so every field a real record carries is present here. Chat-specific
    ciphertext (conversationState, blob keys) is omitted — the app treats a
    missing conversation state as 'nothing to decrypt'.
    """
    mentions = {}
    for k in ("composers", "selectedCommits", "selectedPullRequests",
              "selectedImages", "folderSelections", "fileSelections",
              "terminalFiles", "selections", "terminalSelections",
              "selectedDocs", "externalLinks", "cursorRules", "cursorCommands",
              "subagentSelections", "browserSelections"):
        mentions[k] = {}
    for k in ("gitDiff", "gitDiffFromBranchToMain", "diffHistory",
              "uiElementSelections", "consoleLogs", "ideEditorsState"):
        mentions[k] = []
    lists = ["composers", "selectedCommits", "selectedPullRequests",
             "selectedImages", "selectedDocuments", "selectedVideos",
             "folderSelections", "fileSelections", "selections",
             "terminalSelections", "selectedDocs", "externalLinks",
             "cursorRules", "cursorCommands", "gitPRDiffSelections",
             "subagentSelections", "browserSelections", "extraContext"]
    context = {k: [] for k in lists}
    context["mentions"] = mentions
    return {
        "_v": 18,
        "composerId": cuuid,
        "richText": "",
        "hasLoaded": True,
        "text": "",
        "fullConversationHeadersOnly": headers,
        "conversationMap": {},
        "status": "completed",
        "context": context,
        "generatingBubbleIds": [],
        "codeBlockData": {},
        "originalFileStates": {},
        "newlyCreatedFiles": [],
        "newlyCreatedFolders": [],
        "lastUpdatedAt": now_ms,
        "conversationCheckpointLastUpdatedAt": now_ms,
        "createdAt": now_ms,
        "hasChangedContext": False,
        "capabilities": [
            {"type": 15, "data": {"bubbleDataMap": "{}"}},
            {"type": 19, "data": {}},
            {"type": 33, "data": {}},
            {"type": 32, "data": {}},
            {"type": 23, "data": {}},
            {"type": 16, "data": {}},
            {"type": 24, "data": {}},
        ],
        "name": title,
        "isFileListExpanded": False,
        "canvasPillCollapsed": False,
        "browserChipManuallyDisabled": False,
        "browserChipManuallyEnabled": False,
        "unifiedMode": "agent",
        "activeCustomMode": None,
        "committedCustomMode": None,
        "pendingExitedCustomMode": None,
        "forceMode": "agent",
        "usageData": {},
        "contextUsagePercent": 0,
        "contextTokensUsed": 0,
        "contextTokenLimit": 256000,
        "allAttachedFileCodeChunksUris": [],
        "subComposerIds": [],
        "subagentComposerIds": [],
        "capabilityContexts": [],
        "todos": [],
        "isQueueExpanded": True,
        "hasUnreadMessages": False,
        "lastReadAtMs": now_ms,
        "gitHubPromptDismissed": False,
        "totalLinesAdded": 0,
        "totalLinesRemoved": 0,
        "addedFiles": 0,
        "removedFiles": 0,
        "isDraft": False,
        "isCreatingWorktree": False,
        "isApplyingWorktree": False,
        "isUndoingWorktree": False,
        "applied": False,
        "pendingCreateWorktree": False,
        "worktreeStartedReadOnly": False,
        "isBestOfNSubcomposer": False,
        "isBestOfNParent": False,
        "isSpec": False,
        "isProject": False,
        "isSpecSubagentDone": False,
        "isContinuationInProgress": False,
        "stopHookLoopCount": 0,
        "trackedGitRepos": [],
        "isNAL": True,
        "planModeSuggestionUsed": False,
        "debugModeSuggestionUsed": False,
        "latestChatGenerationUUID": None,
        "isAgentic": True,
        "subtitle": title,
        "workspaceIdentifier": {"id": ws_id, "uri": uri},
        "queueItems": [],
    }


def _cursor_head_record(cuuid, title, now_ms, ws_id, uri):
    """The 'head' summary the composerHeaders store holds per chat (3.x).

    Mirrors a real head exactly: the app's list view renders name/subtitle/
    times from this row, and `agentLocation` tells it where the chat's local
    data lives. The row is the gate: without it the app never lists the chat.
    """
    env = {"id": ws_id, "uri": uri}
    return {
        "type": "head",
        "composerId": cuuid,
        "name": title,
        "lastUpdatedAt": now_ms,
        "conversationCheckpointLastUpdatedAt": now_ms,
        "createdAt": now_ms,
        "unifiedMode": "agent",
        "forceMode": "agent",
        "hasUnreadMessages": False,
        "contextUsagePercent": 0,
        "totalLinesAdded": 0,
        "totalLinesRemoved": 0,
        "subtitle": title,
        "hasBlockingPendingActions": False,
        "hasPendingPlan": False,
        "isDraft": False,
        "isWorktree": False,
        "worktreeStartedReadOnly": False,
        "isSpec": False,
        "isProject": False,
        "isBestOfNSubcomposer": False,
        "numSubComposers": 0,
        "referencedPlans": [],
        "trackedGitRepos": [],
        "workspaceIdentifier": {"id": ws_id, "uri": uri},
        "agentLocation": {"type": "local", "environment": env, "status": "active"},
        "agentLocationHistory": [{
            "id": str(uuid.uuid4()),
            "timestamp": now_ms,
            "destination": {"type": "local"},
            "location": {"type": "local", "environment": env, "status": "active"},
            "reason": "created",
        }],
    }


def _cursor_write_composer_headers(cuuid, title, now_ms, ws_id, uri):
    """Register the chat in Cursor's composerHeaders store.

    On Cursor 3.x the sidebar and chat history list from the `composerHeaders`
    table in the global state.vscdb (canonical once the app has migrated; the
    legacy cursorDiskKV blob is cleared then). On older 2.x installs the heads
    live in the `composer.composerHeaders` KV blob instead, so fall back to
    appending there when the table does not exist. Best-effort: returns False
    when nothing was written (e.g. the app data dir is absent or locked).
    """
    gs = _cursor_appdata_dir() / "User" / "globalStorage"
    state_db = gs / "state.vscdb"
    if not state_db.is_file():
        return False
    head = _cursor_head_record(cuuid, title, now_ms, ws_id, uri)
    try:
        c = sqlite3.connect(str(state_db), timeout=15)
        has_table = c.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE type='table' AND name='composerHeaders'").fetchone()[0]
        if has_table:
            c.execute(
                "INSERT INTO composerHeaders "
                "(composerId, workspaceId, createdAt, lastUpdatedAt, isArchived,"
                " isSubagent, recency, checkpointAt, subagentTypeName, value)"
                " VALUES (?,?,?,?,0,0,?,?,?,?)"
                " ON CONFLICT(composerId) DO UPDATE SET"
                " workspaceId=excluded.workspaceId, lastUpdatedAt=excluded.lastUpdatedAt,"
                " recency=excluded.recency, value=excluded.value",
                (cuuid, ws_id, now_ms, now_ms, now_ms, now_ms, "",
                 json.dumps(head)))
        else:
            row = c.execute(
                "SELECT value FROM cursorDiskKV"
                " WHERE key='composer.composerHeaders'").fetchone()
            heads = []
            if row:
                try:
                    parsed = json.loads(row[0])
                    if isinstance(parsed, list):
                        heads = parsed
                except (ValueError, TypeError):
                    heads = []
            heads = [h for h in heads
                     if not (isinstance(h, dict)
                             and h.get("composerId") == cuuid)]
            heads.append(head)
            c.execute("INSERT OR REPLACE INTO cursorDiskKV (key, value) VALUES (?,?)",
                      ("composer.composerHeaders", json.dumps(heads)))
        c.commit()
        c.close()
        return True
    except sqlite3.Error:
        return False


def _cursor_tool_case(name):
    """Map a tool name to Cursor's (toolCallCase, toolFormerTool) pair."""
    n = (name or "").lower()
    if "read" in n:
        return "readToolCall", 40
    if "write" in n or "edit" in n:
        return "writeToolCall", 41
    if "bash" in n or "shell" in n or "command" in n:
        return "bashToolCall", 42
    if "search" in n or "grep" in n or "glob" in n:
        return "searchToolCall", 43
    return "genericToolCall", 40


def _register_cursor_conversation(cuuid, title, body, lines, directory, now_ms):
    """Make a moved-in transcript show in the *real* Cursor app.

    Stores, all best-effort, all required on at least one Cursor version:
      1. composerHeaders (global state.vscdb) — on Cursor 3.x the sidebar and
         chat history list from this table; without a row the app never shows
         the chat. On 2.x the heads live in the cursorDiskKV blob instead.
      2. Composer store (global state.vscdb, cursorDiskKV,
         `composerData:<uuid>`) — full composer record (_v matches the
         installed app; wrong version opens a blank chat).
      3. Message bubbles (same table, `bubbleId:<uuid>:<bubbleId>`) — used by
         older versions; 3.x renders from the transcript instead.
      4. Workspace allComposers (workspaceStorage/<hash>/state.vscdb,
         ItemTable `composer.composerData`) — the 2.x sidebar source; 3.x
         workspaces keep this empty, so this is legacy compatibility only.
      5. Search index (conversation-search.db) — written with the matching
         fingerprint for immediate visibility before the next reconcile.

    `lines` is the transcript (each line has `role` and `message.content`).
    The real app renders assistant content from the bubble's `text` (visible
    text) and `toolFormerData` (tool use), and gates rendering on the header's
    `grouping.isRenderable`.
    """
    gs = _cursor_appdata_dir() / "User" / "globalStorage"
    ws_id = _cursor_workspace_id(directory)
    uri = _cursor_uri_obj(directory)

    # Build headers + bubbles from the transcript. The real app renders
    # assistant content from the bubble's `text` (visible text) and
    # `toolFormerData` (tool use), and gates rendering on the header's
    # `grouping.isRenderable` — a tool-use reply with no `grouping` renders
    # blank, so both must be populated. Timestamps mirror a real header
    # (ISO createdAt + startedAtMs/completedAtMs).
    headers = []
    bubbles = []  # (bubbleId, bubble_dict)
    for l in lines:
        role = l.get("role")
        content = (l.get("message") or {}).get("content") or []
        bubble_id = str(uuid.uuid4())
        btype = 1 if role == "user" else 2
        texts = [c.get("text", "") for c in content
                 if isinstance(c, dict) and c.get("type") == "text"]
        tools = [c for c in content
                 if isinstance(c, dict) and c.get("type") == "tool_use"]
        text = "\n".join(t for t in texts if t).strip()
        bubble = {"_v": 1, "type": btype, "text": text, "bubbleId": bubble_id,
                  "isAgentic": True, "unifiedMode": "agent"}
        grouping = {"isRenderable": True, "toolDisplayComputed": True}
        if text:
            grouping["hasText"] = True
        if btype == 2 and tools:
            t0 = tools[0]
            tool_call_id = f"call-{uuid.uuid4()}"
            name = t0.get("name", "tool")
            case, tool = _cursor_tool_case(name)
            raw_args = t0.get("input")
            raw_args_s = (raw_args if isinstance(raw_args, str)
                          else json.dumps(raw_args))
            path = ""
            if isinstance(raw_args, dict):
                path = (raw_args.get("path") or raw_args.get("targetFile")
                        or raw_args.get("file_path") or "")
            bubble["toolFormerData"] = {
                "toolCallId": tool_call_id,
                "toolIndex": 0,
                "modelCallId": tool_call_id,
                "status": "completed",
                "name": name,
                "rawArgs": raw_args_s,
                "tool": tool,
                "params": raw_args_s,
                "result": "{}",
            }
            bubble["unifiedMode"] = 2
            bubble["capabilityType"] = 15
            grouping.update({
                "capabilityType": 15,
                "toolFormerTool": tool,
                "toolFormerStatus": "completed",
                "toolCallId": tool_call_id,
                "isToolGroupable": True,
                "toolCallCase": case,
                "toolDisplayComputed": True,
            })
            if path:
                grouping["toolDisplayPath"] = path
        headers.append({"bubbleId": bubble_id, "type": btype,
                        "createdAt": _iso_ms(now_ms),
                        "startedAtMs": now_ms, "completedAtMs": now_ms,
                        "grouping": grouping})
        bubbles.append((bubble_id, bubble))

    message_ids = [h["bubbleId"] for h in headers]
    fingerprint = _cursor_root_fingerprint(cuuid, title, now_ms, False, message_ids, "")

    # 1) + 2) composer store + message bubbles (global cursorDiskKV)
    src = gs / "state.vscdb"
    if src.is_file():
        try:
            conn = sqlite3.connect(str(src), timeout=15)
            conn.execute(
                "INSERT OR REPLACE INTO cursorDiskKV (key, value) VALUES (?,?)",
                (f"composerData:{cuuid}",
                 json.dumps(_cursor_composer_defaults(
                     cuuid, title, headers, now_ms, ws_id, uri))))
            for bubble_id, bubble in bubbles:
                conn.execute(
                    "INSERT OR REPLACE INTO cursorDiskKV (key, value) VALUES (?,?)",
                    (f"bubbleId:{cuuid}:{bubble_id}", json.dumps(bubble)))
            conn.commit()
            conn.close()
        except sqlite3.Error:
            pass

    # 3) workspace allComposers — the 2.x sidebar source; 3.x workspaces keep
    #    this list empty, so this write is legacy compatibility only
    ws_db = _cursor_workspace_db(directory)
    if ws_db is not None and ws_db.is_file():
        try:
            conn = sqlite3.connect(str(ws_db), timeout=15)
            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key='composer.composerData'"
            ).fetchone()
            data = json.loads(row[0]) if row else {
                "allComposers": [], "selectedComposerIds": [],
                "lastFocusedComposerIds": [], "hasMigratedComposerData": True,
                "hasMigratedMultipleComposers": True}
            entry = {"type": "head", "composerId": cuuid, "name": title,
                     "lastUpdatedAt": now_ms, "createdAt": now_ms,
                     "unifiedMode": "agent", "forceMode": "agent",
                     "hasUnreadMessages": False, "contextUsagePercent": 0,
                     "totalLinesAdded": 0, "totalLinesRemoved": 0,
                     "filesChangedCount": 0, "subtitle": "",
                     "hasBlockingPendingActions": False, "isArchived": False,
                     "isDraft": False, "isWorktree": False, "isSpec": False,
                     "isBestOfNSubcomposer": False, "numSubComposers": 0,
                     "referencedPlans": []}
            if not any(c.get("composerId") == cuuid
                       for c in data.get("allComposers", [])):
                data.setdefault("allComposers", []).insert(0, entry)
            conn.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?,?)",
                ("composer.composerData", json.dumps(data)))
            conn.commit()
            conn.close()
        except sqlite3.Error:
            pass

    # 5) composerHeaders — on Cursor 3.x this table is the sidebar/history
    #    listing source; without a row the app never shows the chat at all.
    _cursor_write_composer_headers(cuuid, title, now_ms, ws_id, uri)

    # (legacy) search index — immediate visibility with the matching fingerprint
    db = gs / "conversation-search.db"
    if not db.is_file():
        return
    try:
        conn = sqlite3.connect(str(db), timeout=15)
        cur = conn.execute(
            "INSERT INTO conversation_fts (title, body, branches) VALUES (?,?,?)",
            (title, body, ""))
        fts_rowid = cur.lastrowid
        conn.execute(
            "INSERT INTO conversations (fts_rowid, source, scope, id, title, branches,"
            " updated_at, is_archived, root_fingerprint, cache_fingerprint)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (fts_rowid, "local", "", cuuid, title, "", now_ms, 0, fingerprint, None))
        conn.execute(
            "INSERT INTO conversation_search_candidates (id, updated_at) VALUES (?,?)",
            (cuuid, now_ms))
        conn.commit()
        conn.close()
    except sqlite3.Error:
        pass


def move_opencode_to_cursor(conn, sid, directory, delete_original=False):
    """Copy an opencode session into a Cursor project as a .jsonl transcript.

    Reads the session's messages, converts each turn to Cursor's line format
    (user -> text; assistant -> text/reasoning/tool_use) and writes
    <projects>/<slug>/agent-transcripts/<uuid>/<uuid>.jsonl. Tool output and
    model/agent metadata are not part of the Cursor format, so they are dropped.
    """
    if not isinstance(directory, str) or not directory:
        raise HttpError(400, "directory is required")
    if conn.execute("SELECT id FROM session_v2 WHERE id = ?", (sid,)).fetchone() is None:
        raise HttpError(404, "session not found")
    msgs = conn.execute(
        "SELECT type, data FROM session_message WHERE session_id = ? ORDER BY seq", (sid,)
    ).fetchall()
    lines = []
    for m in msgs:
        d = json.loads(m["data"]) if isinstance(m["data"], str) else m["data"]
        if m["type"] == "user":
            lines.append({"role": "user", "message": {"content": [
                {"type": "text", "text": d.get("text", "")}]}})
        else:
            content = []
            for c in (d.get("content") or []):
                if not isinstance(c, dict):
                    continue
                t = c.get("type")
                if t == "text":
                    content.append({"type": "text", "text": c.get("text", "")})
                elif t == "reasoning":
                    content.append({"type": "reasoning", "text": c.get("text", "")})
                elif t == "tool":
                    state = c.get("state") or {}
                    content.append({"type": "tool_use", "name": c.get("name", "tool"),
                                    "input": state.get("input")})
            lines.append({"role": "assistant", "message": {"content": content}})
    slug = _resolve_cursor_slug(directory)
    cuuid = str(uuid.uuid4())  # dashed UUID, matching Cursor's own transcript ids
    tdir = cursor_projects_dir() / slug / "agent-transcripts" / cuuid
    tdir.mkdir(parents=True, exist_ok=True)
    raw = "\n".join(json.dumps(l) for l in lines) + "\n"
    (tdir / f"{cuuid}.jsonl").write_text(raw)
    # remember the real path so the project shows a clean label, not the raw slug
    try:
        (cursor_projects_dir() / slug / ".opencrup-path").write_text(directory)
    except OSError:
        pass
    # register in Cursor's search index so the real app lists it in its history
    title = ""
    for l in lines:
        if l["role"] != "user":
            continue
        for c in l["message"]["content"]:
            if isinstance(c, dict) and c.get("type") == "text" and c.get("text"):
                title = c["text"].strip()
                break
        if title:
            break
    body = " ".join(c.get("text", "") for l in lines for c in l["message"]["content"]
                    if isinstance(c, dict) and c.get("type") == "text")
    # the transcript lines drive the composer headers + bubbles; the real app
    # renders assistant content from each bubble's `text`/`toolFormerData` and
    # gates it on the header's `grouping.isRenderable` (see
    # _register_cursor_conversation)
    _register_cursor_conversation(cuuid, title[:80], body, lines,
                                  directory, int(time.time() * 1000))
    _CURSOR_CACHE.clear()
    if delete_original:
        conn.execute("DELETE FROM session_v2 WHERE id = ?", (sid,))  # messages cascade
        conn.commit()
    return {"id": f"{slug}::{cuuid}", "slug": slug, "uuid": cuuid, "directory": directory}


# ---------------------------------------------------------------------------
# API: messages
# ---------------------------------------------------------------------------
def update_message(conn, mid, body):
    text = body.get("text")
    if not isinstance(text, str):
        raise HttpError(400, "text is required")
    row = conn.execute("SELECT * FROM session_message WHERE id = ?", (mid,)).fetchone()
    if not row:
        raise HttpError(404, "message not found")
    try:
        data = json.loads(row["data"])
    except (json.JSONDecodeError, TypeError):
        raise HttpError(400, "message data is not valid JSON")
    if row["type"] == "assistant":
        content = data.get("content") or []
        item = next((c for c in content if c.get("type") == "text"), None)
        if item is not None:
            item["text"] = text
        else:
            data["content"] = content + [{"type": "text", "text": text}]
    else:
        data["text"] = text
    now = now_ms()
    conn.execute(
        "UPDATE session_message SET data = ?, time_updated = ? WHERE id = ?",
        (json.dumps(data), now, mid),
    )
    conn.execute("UPDATE session_v2 SET time_updated = ? WHERE id = ?", (now, row["session_id"]))
    conn.commit()
    return {"updated": mid}


def delete_message(conn, mid):
    row = conn.execute("SELECT id, session_id FROM session_message WHERE id = ?", (mid,)).fetchone()
    if not row:
        raise HttpError(404, "message not found")
    now = now_ms()
    conn.execute("DELETE FROM session_message WHERE id = ?", (mid,))
    conn.execute("UPDATE session_v2 SET time_updated = ? WHERE id = ?", (now, row["session_id"]))
    conn.commit()
    return {"deleted": mid}


# ---------------------------------------------------------------------------
# API: model catalog (distinct models seen in sessions)
# ---------------------------------------------------------------------------
def list_models(conn):
    rows = conn.execute("SELECT model FROM session_v2 WHERE model IS NOT NULL").fetchall()
    seen = {}
    for r in rows:
        try:
            m = json.loads(r["model"])
        except (json.JSONDecodeError, TypeError):
            continue
        key = f"{m.get('providerID')}/{m.get('id')}" + (f"#{m['variant']}" if m.get("variant") else "")
        seen.setdefault(key, m)
    return list(seen.values())


# ---------------------------------------------------------------------------
# API: cursor (conversations stored as .jsonl transcripts on disk)
# ---------------------------------------------------------------------------
_CURSOR_CACHE = {}  # (path, mtime) -> parsed messages
_CURSOR_PATHS = None  # slug -> real folder (best effort, from workspace.json)


def _cursor_transcript_path(slug, uuid):
    return cursor_projects_dir() / slug / "agent-transcripts" / uuid / f"{uuid}.jsonl"


def _iter_cursor_transcripts():
    d = cursor_projects_dir()
    if not d.is_dir():
        return
    for proj in sorted(d.iterdir()):
        if not proj.is_dir():
            continue
        at = proj / "agent-transcripts"
        if not at.is_dir():
            continue
        for sess in at.iterdir():
            if sess.is_dir() and (sess / f"{sess.name}.jsonl").is_file():
                yield proj.name, sess.name, sess / f"{sess.name}.jsonl"


def _clean_user_text(text):
    t = re.sub(r"<timestamp>.*?</timestamp>\s*", "", text, flags=re.S)
    m = re.search(r"<user_query>(.*?)</user_query>", t, flags=re.S)
    if m:
        return m.group(1).strip()
    return t.strip()


def _parse_cursor_transcript(path):
    """Parse a .jsonl transcript into the unified message shape the UI expects."""
    key = (str(path), path.stat().st_mtime)
    cached = _CURSOR_CACHE.get(key)
    if cached is not None:
        return cached
    messages = []
    try:
        raw = path.read_text(errors="replace")
    except OSError:
        return []
    for i, line in enumerate(raw.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        role = obj.get("role")
        if role not in ("user", "assistant"):
            continue
        content = (obj.get("message") or {}).get("content") or []
        if role == "user":
            text = "".join(
                c.get("text", "") for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            )
            messages.append({"id": str(i), "type": "user", "time_created": 0,
                             "data": {"text": _clean_user_text(text)}})
        else:
            out = []
            for c in content:
                if not isinstance(c, dict):
                    continue
                t = c.get("type")
                if t == "text":
                    out.append({"type": "text", "text": c.get("text", "")})
                elif t == "tool_use":
                    out.append({"type": "tool", "name": c.get("name", "tool"),
                                "state": {"status": "completed", "input": c.get("input"), "content": []}})
                elif t == "reasoning":
                    out.append({"type": "reasoning", "text": c.get("text", "")})
            messages.append({"id": str(i), "type": "assistant", "time_created": 0,
                             "data": {"content": out}})
    _CURSOR_CACHE[key] = messages
    return messages


def _cursor_title(path, uuid):
    override = path.parent / f"{uuid}.title"
    if override.is_file():
        t = override.read_text(errors="replace").strip()
        if t:
            return t
    for m in _parse_cursor_transcript(path):
        if m["type"] == "user" and m["data"].get("text"):
            return m["data"]["text"].split("\n")[0][:80]
    return "Untitled conversation"


def _cursor_is_archived(path, uuid):
    return (path.parent / f"{uuid}.archived").is_file()


def _cursor_real_path(slug):
    """Best-effort mapping of a project slug back to a real folder path."""
    global _CURSOR_PATHS
    if _CURSOR_PATHS is None:
        _CURSOR_PATHS = {}
        for _ws_id, (_db, folder) in _cursor_workspaces().items():
            s = _cursor_slug_from_path(str(folder))
            _CURSOR_PATHS.setdefault(s, str(folder))
            _CURSOR_PATHS.setdefault(s.lower(), str(folder))
            _CURSOR_PATHS.setdefault(str(folder), str(folder))
    if slug in _CURSOR_PATHS:
        return _CURSOR_PATHS[slug]
    if slug.lower() in _CURSOR_PATHS:
        return _CURSOR_PATHS[slug.lower()]
    # explicit path OpenCrup saved when it moved a transcript into this project
    # (Cursor's own workspace.json only knows projects it has natively opened)
    try:
        p = (cursor_projects_dir() / slug / ".opencrup-path").read_text().strip()
        if p:
            return p
    except OSError:
        pass
    return slug


def _cursor_slug_from_path(path):
    """A real folder path -> its Cursor project-dir slug.

    Matches the app's own formula (Cursor 3.x): every non-alphanumeric char
    becomes '-', runs of '-' collapse, and leading/trailing '-' are trimmed.
    So 'C:\\Users\\x\\proj' slugs to 'C-Users-x-proj' on Windows and
    '/Users/x/proj' to 'Users-x-proj' elsewhere.
    """
    p = str(path)
    if p.startswith("file://"):
        dec = _decode_folder_uri(p)
        if dec is not None:
            p = str(dec)
    s = re.sub(r"[^A-Za-z0-9]", "-", p)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def _resolve_cursor_slug(directory):
    """Slug for `directory`, preferring a project dir Cursor (or a prior move)
    already created — on Windows a case difference ('c-' vs 'C-') would
    otherwise fork into a second, app-invisible folder."""
    p = Path(directory).expanduser()
    try:
        p = p.resolve()
    except OSError:
        pass
    slug = _cursor_slug_from_path(str(p))
    base = cursor_projects_dir()
    if base.is_dir():
        want = slug.lower()
        try:
            for d in base.iterdir():
                if d.is_dir() and d.name.lower() == want:
                    return d.name
        except OSError:
            pass
    return slug


def cursor_diag():
    """Report the resolved Cursor paths + store availability, for debugging
    cross-platform moves/purges (e.g. a Windows user seeing chats but writes
    not landing). Returns plain data, best-effort."""
    app_dir = _cursor_appdata_dir()
    gs = app_dir / "User" / "globalStorage"
    state_db = gs / "state.vscdb"
    search_db = gs / "conversation-search.db"
    ws_root = app_dir / "User" / "workspaceStorage"
    info = {
        "platform": platform.system(),
        "home": str(Path.home()),
        "appdata_dir": str(app_dir),
        "appdata_dir_exists": app_dir.is_dir(),
        "projects_dir": str(cursor_projects_dir()),
        "projects_dir_exists": cursor_projects_dir().is_dir(),
        "state_vscdb": str(state_db),
        "state_vscdb_exists": state_db.is_file(),
        "search_db_exists": search_db.is_file(),
        "workspace_root": str(ws_root),
        "workspace_count": len(list(ws_root.glob("*/state.vscdb"))) if ws_root.is_dir() else 0,
    }
    # does the global state.vscdb have the tables the move/purge need, and can
    # we actually WRITE to it (Windows locks it while Cursor runs)?
    if state_db.is_file():
        try:
            c = sqlite3.connect(str(state_db), timeout=15)
            tables = {r[0] for r in c.execute(
                "select name from sqlite_master where type='table'").fetchall()}
            info["state_tables"] = sorted(t for t in tables
                                          if t in ("cursorDiskKV", "ItemTable",
                                                   "composerHeaders"))
            if "composerHeaders" in tables:
                info["composer_headers"] = {
                    "rows": c.execute(
                        "select count(*) from composerHeaders").fetchone()[0],
                    "canonical": (c.execute(
                        "select value from cursorDiskKV"
                        " where key='composer.composerHeaders.migratedToTable'"
                    ).fetchone() or [None])[0] == "1",
                }
            # test write: insert + delete a throwaway row, with a busy timeout
            probe = f"opencrup_diag_{secrets.token_hex(4)}"
            c.execute("INSERT OR REPLACE INTO cursorDiskKV (key, value) VALUES (?,?)",
                      (probe, "diag"))
            c.execute("DELETE FROM cursorDiskKV WHERE key = ?", (probe,))
            c.commit()
            info["write_ok"] = True
            c.close()
        except sqlite3.Error as e:
            info["write_ok"] = False
            info["state_error"] = str(e)
    return info


def cursor_workspace_diag(directory):
    """For a given project directory, show how the workspace match resolves.

    The chat registers under the matched workspace id (3.x composerHeaders
    workspaceId, 2.x allComposers store), so if
    _cursor_workspace_db(directory) returns None it lands in the app's
    'empty-window' bucket instead of the project's sidebar. Reports every
    workspace's folder URI and which (if any) matches the directory."""
    ws_root = _cursor_appdata_dir() / "User" / "workspaceStorage"
    target = Path(directory).expanduser().resolve() if directory else None
    win = platform.system() == "Windows"
    norm = (lambda p: str(p).lower()) if win else (lambda p: str(p))
    target_n = norm(target) if target is not None else None
    entries = []
    if ws_root.is_dir():
        for wj in ws_root.glob("*/workspace.json"):
            try:
                folder = json.loads(wj.read_text()).get("folder", "")
            except (OSError, ValueError):
                folder = ""
            cand = _decode_folder_uri(folder)
            entries.append({
                "workspace": wj.parent.name,
                "folder": folder,
                "decoded": str(cand) if cand is not None else None,
                "match": bool(target_n and cand is not None
                              and (norm(cand) == target_n
                                   or norm(cand.resolve()) == target_n)),
            })
    return {
        "directory": str(target) if target is not None else None,
        "normalized_target": target_n,
        "resolved_workspace_db": str(_cursor_workspace_db(directory)) if directory else None,
        "workspaces": entries,
    }


def cursor_composer_diag(uuid):
    """Dump exactly where a moved conversation landed, for a given UUID.

    Reports the global store (composerHeaders row, composer record + bubble
    count) and, for every workspace, whether the UUID is in its allComposers
    or local composerHeaders table. Lets a Windows user confirm whether the
    move wrote to the right places."""
    app_dir = _cursor_appdata_dir()
    state_db = app_dir / "User" / "globalStorage" / "state.vscdb"
    info = {"uuid": uuid, "global": {}, "workspaces": []}
    if state_db.is_file():
        try:
            c = sqlite3.connect(str(state_db), timeout=15)
            comp = c.execute(
                "select value from cursorDiskKV where key=?",
                (f"composerData:{uuid}",)).fetchone()
            nbub = c.execute(
                "select count(*) from cursorDiskKV where key like ?",
                (f"bubbleId:{uuid}:%",)).fetchone()[0]
            header = None
            try:
                header = c.execute(
                    "select workspaceId, value from composerHeaders"
                    " where composerId = ?", (uuid,)).fetchone()
            except sqlite3.Error:
                header = None
            c.close()
            info["global"] = {
                "composer": bool(comp),
                "bubbles": nbub,
                "composer_headers": (None if not header else {
                    "workspaceId": header[0],
                    "head": json.loads(header[1])
                    if isinstance(header[1], str) else None,
                }),
            }
        except sqlite3.Error as e:
            info["global"]["error"] = str(e)
    ws_root = app_dir / "User" / "workspaceStorage"
    if ws_root.is_dir():
        for wdb in ws_root.glob("*/state.vscdb"):
            try:
                c = sqlite3.connect(str(wdb), timeout=15)
                row = c.execute(
                    "select value from ItemTable where key='composer.composerData'"
                ).fetchone()
                wh = None
                try:
                    wh = c.execute(
                        "select workspaceId, value from composerHeaders"
                        " where composerId = ?", (uuid,)).fetchone()
                except sqlite3.Error:
                    wh = None
                c.close()
                allc = []
                if row:
                    data = json.loads(row[0].decode() if isinstance(row[0], bytes) else row[0])
                    allc = data.get("allComposers", [])
                entry = next((ac for ac in allc if ac.get("composerId") == uuid), None)
                if not (entry or wh):
                    continue
                info["workspaces"].append({
                    "workspace": wdb.parent.name,
                    "in_all_composers": bool(entry),
                    "entry": entry,
                    "in_composer_headers": bool(wh),
                })
            except (sqlite3.Error, ValueError):
                continue
    return info


def _cursor_header_chats(include_archived=False):
    """Chats the real app lists from its composerHeaders store (3.x) but that
    have no local transcript — native 3.x chats whose content lives in the
    agent store / cloud. Moved-in chats have a transcript and are already
    covered by the transcript scan, so they are skipped here."""
    gs = _cursor_appdata_dir() / "User" / "globalStorage" / "state.vscdb"
    if not gs.is_file():
        return []
    workspaces = _cursor_workspaces()
    try:
        c = sqlite3.connect(str(gs), timeout=10)
        rows = c.execute(
            "SELECT composerId, workspaceId, createdAt, lastUpdatedAt,"
            " isArchived, value FROM composerHeaders").fetchall()
        c.close()
    except sqlite3.Error:
        return []
    have = {u for _slug, u, _p in _iter_cursor_transcripts()}
    out = []
    for cuuid, ws_id, created, updated, archived, value in rows:
        if cuuid in have:
            continue
        try:
            head = json.loads(value)
        except (ValueError, TypeError):
            continue
        if not isinstance(head, dict):
            continue
        if head.get("isDraft") or cuuid == "empty-state-draft":
            continue
        if archived and not include_archived:
            continue
        folder = workspaces.get(ws_id, (None, None))[1]
        out.append({
            "id": f"{ws_id}::{cuuid}",
            "title": head.get("name") or head.get("subtitle") or "Untitled conversation",
            "directory": str(folder) if folder is not None else "",
            "project": ws_id,
            "time_created": created or 0,
            "time_updated": updated or 0,
            "time_archived": (updated or 0) if archived else None,
            "agent": None,
            "model": None,
            "message_count": 0,
            "local": False,
        })
    return out


def cursor_projects():
    counts = {}
    for slug, _uuid, _path in _iter_cursor_transcripts():
        counts[slug] = counts.get(slug, 0) + 1
    # 3.x-native projects have no transcripts but do have listed chats
    for chat in _cursor_header_chats(include_archived=True):
        if not chat["project"] or chat["project"] == "empty-window":
            continue
        counts.setdefault(chat["project"], 0)
    out = [{"id": slug, "worktree": _cursor_real_path(slug), "session_count": n}
           for slug, n in counts.items()]
    out.sort(key=lambda p: p["worktree"])
    return out


def cursor_sessions(project=None, q=None, include_archived=False, limit="200"):
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 200
    rows = []
    for slug, uuid, path in _iter_cursor_transcripts():
        if project and slug != project:
            continue
        archived = _cursor_is_archived(path, uuid)
        if not include_archived and archived:
            continue
        mtime = int(path.stat().st_mtime * 1000)
        title = _cursor_title(path, uuid)
        msgs = _parse_cursor_transcript(path)
        rows.append({
            "id": f"{slug}::{uuid}",
            "title": title,
            "directory": _cursor_real_path(slug),
            "project": slug,
            "time_created": mtime,
            "time_updated": mtime,
            "time_archived": mtime if archived else None,
            "agent": None,
            "model": None,
            "message_count": len(msgs),
            "local": True,
        })
    # chats the app lists from composerHeaders without a local transcript
    for chat in _cursor_header_chats(include_archived=include_archived):
        if project and chat["project"] != project:
            continue
        rows.append(chat)
    if q:
        like = f"%{q}%"
        rows = [r for r in rows
                if like.replace("%", "").lower() in r["title"].lower()
                or like.replace("%", "").lower() in r["directory"].lower()
                or like.replace("%", "").lower() in r["id"].lower()]
    rows.sort(key=lambda r: r["time_updated"], reverse=True)
    return rows[:limit]


def cursor_get_session(sid):
    slug, uuid = sid.split("::", 1)
    path = _cursor_transcript_path(slug, uuid)
    if not path.is_file():
        # 3.x-native chat: listed from composerHeaders, content not local
        for chat in _cursor_header_chats(include_archived=True):
            if chat["id"] == f"{slug}::{uuid}":
                return {
                    "id": sid,
                    "title": chat["title"],
                    "directory": chat["directory"],
                    "project": slug,
                    "time_created": chat["time_created"],
                    "time_updated": chat["time_updated"],
                    "time_archived": chat["time_archived"],
                    "agent": None,
                    "model": None,
                    "local": False,
                    "messages": [],
                }
        raise HttpError(404, "conversation not found")
    mtime = int(path.stat().st_mtime * 1000)
    return {
        "id": sid,
        "title": _cursor_title(path, uuid),
        "directory": _cursor_real_path(slug),
        "project": slug,
        "time_created": mtime,
        "time_updated": mtime,
        "time_archived": mtime if _cursor_is_archived(path, uuid) else None,
        "agent": None,
        "model": None,
        "local": True,
        "messages": _parse_cursor_transcript(path),
    }


# ---------------------------------------------------------------------------
# Claude Code source (~/.claude/projects/<slug>/<sessionId>.jsonl)
# ---------------------------------------------------------------------------
_CLAUDE_CACHE = {}   # (path, mtime) -> parsed messages
_CLAUDE_CWD = {}     # slug -> real project path (cwd)


def _claude_projects_dir():
    """Claude Code projects dir: $CLAUDE_CONFIG_DIR/projects or ~/.claude/projects."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(env).expanduser() if env else Path.home() / ".claude"
    return base / "projects"


def _claude_transcript_path(slug, uuid):
    return _claude_projects_dir() / slug / f"{uuid}.jsonl"


def _iter_claude_transcripts():
    d = _claude_projects_dir()
    if not d.is_dir():
        return
    for proj in sorted(d.iterdir()):
        if not proj.is_dir():
            continue
        for f in proj.iterdir():
            if f.is_file() and f.suffix == ".jsonl":
                yield proj.name, f.stem, f


def _claude_real_path(slug, path=None):
    """Real project path (cwd) for a Claude Code slug, read from the transcript."""
    if slug in _CLAUDE_CWD:
        return _CLAUDE_CWD[slug]
    cwd = None
    if path is not None:
        try:
            with open(path, errors="replace") as fh:
                first = fh.readline().strip()
            if first:
                cwd = json.loads(first).get("cwd")
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    if not cwd:
        cwd = "/" + slug.lstrip("-").replace("-", "/")  # lossy fallback
    _CLAUDE_CWD[slug] = cwd
    return cwd


def _claude_ts(iso):
    if not iso:
        return 0
    try:
        return int(datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, AttributeError, OSError):
        return 0


def _parse_claude_transcript(path):
    """Parse a Claude Code .jsonl transcript into the unified message shape."""
    key = (str(path), path.stat().st_mtime)
    cached = _CLAUDE_CACHE.get(key)
    if cached is not None:
        return cached
    messages = []
    try:
        raw = path.read_text(errors="replace")
    except OSError:
        return []
    for i, line in enumerate(raw.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        role = obj.get("type") or (obj.get("message") or {}).get("role")
        if role not in ("user", "assistant"):
            continue
        content = (obj.get("message") or {}).get("content") or []
        ts = _claude_ts(obj.get("timestamp"))
        if role == "user":
            if isinstance(content, str):
                text = content
            else:
                blocks = [c for c in content if isinstance(c, dict)]
                if blocks and all(c.get("type") == "tool_result" for c in blocks):
                    continue  # tool-output line, not a user prompt
                text = "".join(c.get("text", "") for c in blocks if c.get("type") == "text")
            if not text.strip():
                continue
            messages.append({"id": str(i), "type": "user", "time_created": ts,
                             "data": {"text": text}})
        else:
            out = []
            if isinstance(content, str):
                out.append({"type": "text", "text": content})
            else:
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    t = c.get("type")
                    if t == "text":
                        out.append({"type": "text", "text": c.get("text", "")})
                    elif t == "tool_use":
                        out.append({"type": "tool", "name": c.get("name", "tool"),
                                    "state": {"status": "completed", "input": c.get("input"), "content": []}})
                    elif t in ("thinking", "reasoning"):
                        out.append({"type": "reasoning", "text": c.get("thinking") or c.get("text", "")})
            if out:
                messages.append({"id": str(i), "type": "assistant", "time_created": ts,
                                 "data": {"content": out}})
    _CLAUDE_CACHE[key] = messages
    return messages


def _claude_title(path):
    for m in _parse_claude_transcript(path):
        if m["type"] == "user" and m["data"].get("text"):
            return m["data"]["text"].split("\n")[0][:80]
    return "Untitled conversation"


def claude_projects():
    counts, paths = {}, {}
    for slug, _uuid, path in _iter_claude_transcripts():
        counts[slug] = counts.get(slug, 0) + 1
        paths.setdefault(slug, path)
    out = [{"id": slug, "worktree": _claude_real_path(slug, paths[slug]), "session_count": n}
           for slug, n in counts.items()]
    out.sort(key=lambda p: p["worktree"])
    return out


def claude_sessions(project=None, q=None, include_archived=False, limit="200"):
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 200
    rows = []
    for slug, uuid, path in _iter_claude_transcripts():
        if project and slug != project:
            continue
        mtime = int(path.stat().st_mtime * 1000)
        msgs = _parse_claude_transcript(path)
        rows.append({
            "id": f"{slug}::{uuid}",
            "title": _claude_title(path),
            "directory": _claude_real_path(slug, path),
            "project": slug,
            "time_created": mtime,
            "time_updated": mtime,
            "time_archived": None,
            "agent": None,
            "model": None,
            "message_count": len(msgs),
            "local": True,
        })
    if q:
        like = q.lower()
        rows = [r for r in rows
                if like in r["title"].lower()
                or like in r["directory"].lower()
                or like in r["id"].lower()]
    rows.sort(key=lambda r: r["time_updated"], reverse=True)
    return rows[:limit]


def claude_get_session(sid):
    slug, uuid = sid.split("::", 1)
    path = _claude_transcript_path(slug, uuid)
    if not path.is_file():
        raise HttpError(404, "conversation not found")
    mtime = int(path.stat().st_mtime * 1000)
    return {
        "id": sid,
        "title": _claude_title(path),
        "directory": _claude_real_path(slug, path),
        "project": slug,
        "time_created": mtime,
        "time_updated": mtime,
        "time_archived": None,
        "agent": None,
        "model": None,
        "local": True,
        "messages": _parse_claude_transcript(path),
    }


def move_claude_to_opencode(conn, sid, directory, delete_original=False):
    """Copy a Claude Code .jsonl transcript into the opencode DB as a session.

    Mirrors move_cursor_to_opencode: parses the transcript into the unified
    message shape, creates a session_v2 row (under the given project directory)
    and one session_message row per turn, normalized to the exact shape the
    real opencode app decodes (non-null model, time.completed, well-formed tool
    content) so the conversation loads in the app, not just in OpenCrup.
    """
    if not isinstance(directory, str) or not directory:
        raise HttpError(400, "directory is required")
    slug, uuid = sid.split("::", 1)
    path = _claude_transcript_path(slug, uuid)
    if not path.is_file():
        raise HttpError(404, "conversation not found")
    msgs = _parse_claude_transcript(path)
    now = now_ms()
    project_id = resolve_project(conn, directory)
    model = _opencode_default_model(conn)
    new_sid = "ses_" + rand_base62(26)
    conn.execute(
        """INSERT INTO session_v2
           (id, project_id, slug, directory, title, version, agent, model, time_created, time_updated)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (new_sid, project_id, random_slug(), directory, _claude_title(path),
         OPENCODE_VERSION, "build",
         json.dumps(model) if model else None, now, now),
    )
    for i, m in enumerate(msgs):
        d = m["data"]
        if m["type"] == "user":
            data = {"time": {"created": now}, "text": d.get("text", ""), "files": [], "agents": []}
        else:
            content = []
            for idx, c in enumerate(d.get("content") or []):
                if c.get("type") == "tool":
                    content.append(_opencode_tool_content(c, idx, now))
                else:
                    content.append(c)
            data = {"time": {"created": now, "completed": now + 1}, "agent": "build",
                    "model": model, "content": content}
        conn.execute(
            """INSERT INTO session_message
               (id, session_id, type, seq, time_created, time_updated, data)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("msg_" + rand_base62(26), new_sid, m["type"], i + 1, now, now, json.dumps(data)),
        )
    conn.commit()
    if delete_original:
        path.unlink(missing_ok=True)
    return {"id": new_sid, "directory": directory}


def move_claude_to_cursor(conn, sid, directory, delete_original=False):
    """Copy a Claude Code .jsonl transcript into a Cursor project.

    Mirrors move_opencode_to_cursor: parses the transcript into the unified
    message shape, converts each turn to Cursor's line format (user -> text;
    assistant -> text/reasoning/tool_use) and writes
    <projects>/<slug>/agent-transcripts/<uuid>/<uuid>.jsonl, then registers it
    in Cursor's search index so the real app lists + renders it.
    """
    if not isinstance(directory, str) or not directory:
        raise HttpError(400, "directory is required")
    claude_slug, claude_uuid = sid.split("::", 1)  # `uuid` is also a module; don't shadow it
    path = _claude_transcript_path(claude_slug, claude_uuid)
    if not path.is_file():
        raise HttpError(404, "conversation not found")
    msgs = _parse_claude_transcript(path)
    lines = []
    for m in msgs:
        d = m["data"]
        if m["type"] == "user":
            lines.append({"role": "user", "message": {"content": [
                {"type": "text", "text": d.get("text", "")}]}})
        else:
            content = []
            for c in (d.get("content") or []):
                if not isinstance(c, dict):
                    continue
                t = c.get("type")
                if t == "text":
                    content.append({"type": "text", "text": c.get("text", "")})
                elif t == "reasoning":
                    content.append({"type": "reasoning", "text": c.get("text", "")})
                elif t == "tool":
                    state = c.get("state") or {}
                    content.append({"type": "tool_use", "name": c.get("name", "tool"),
                                    "input": state.get("input")})
            lines.append({"role": "assistant", "message": {"content": content}})
    cslug = _resolve_cursor_slug(directory)
    cuuid = str(uuid.uuid4())  # dashed UUID, matching Cursor's own transcript ids
    tdir = cursor_projects_dir() / cslug / "agent-transcripts" / cuuid
    tdir.mkdir(parents=True, exist_ok=True)
    raw = "\n".join(json.dumps(l) for l in lines) + "\n"
    (tdir / f"{cuuid}.jsonl").write_text(raw)
    # remember the real path so the project shows a clean label, not the raw slug
    try:
        (cursor_projects_dir() / cslug / ".opencrup-path").write_text(directory)
    except OSError:
        pass
    title = ""
    for l in lines:
        if l["role"] != "user":
            continue
        for c in l["message"]["content"]:
            if isinstance(c, dict) and c.get("type") == "text" and c.get("text"):
                title = c["text"].strip()
                break
        if title:
            break
    body = " ".join(c.get("text", "") for l in lines for c in l["message"]["content"]
                    if isinstance(c, dict) and c.get("type") == "text")
    _register_cursor_conversation(cuuid, title[:80], body, lines,
                                  directory, int(time.time() * 1000))
    _CURSOR_CACHE.clear()
    if delete_original:
        path.unlink(missing_ok=True)
    return {"id": f"{cslug}::{cuuid}", "slug": cslug, "uuid": cuuid, "directory": directory}


# --- move -> claude: write a Claude Code .jsonl transcript -------------------
_CLAUDE_VERSION = "2.1.292"  # cosmetic: the version stamped into moved transcripts


def _claude_slug_from_path(path):
    """Claude Code project slug: every non-alphanumeric char -> '-'
    (e.g. /private/tmp -> -private-tmp)."""
    return re.sub(r"[^a-zA-Z0-9]", "-", path)


def _claude_iso(ms):
    """Epoch ms -> ISO 8601 (the timestamp format Claude Code transcripts use)."""
    dt = (datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc) if ms
          else datetime.datetime.now(datetime.timezone.utc))
    return dt.isoformat().replace("+00:00", "Z")


def _claude_config_path():
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def _write_claude_transcript(directory, messages, session_id):
    """Write a unified-message conversation as a Claude Code .jsonl transcript.

    user content is a plain string; assistant content is an array of
    text/tool_use/thinking blocks; lines are chained via parentUuid (linear)
    and stamped with cwd/sessionId/version/gitBranch. Returns the path.
    """
    tdir = _claude_projects_dir() / _claude_slug_from_path(directory)
    tdir.mkdir(parents=True, exist_ok=True)
    path = tdir / f"{session_id}.jsonl"
    now = now_ms()
    lines = []
    parent = None
    for m in messages:
        d = m["data"]
        ts = _claude_iso(m.get("time_created") or now)
        uid = str(uuid.uuid4())
        if m["type"] == "user":
            line = {
                "parentUuid": parent, "isSidechain": False, "type": "user",
                "message": {"role": "user", "content": d.get("text", "")},
                "uuid": uid, "timestamp": ts, "cwd": directory,
                "sessionId": session_id, "version": _CLAUDE_VERSION, "gitBranch": "HEAD",
            }
        else:
            content = []
            for c in (d.get("content") or []):
                if not isinstance(c, dict):
                    continue
                t = c.get("type")
                if t == "text":
                    content.append({"type": "text", "text": c.get("text", "")})
                elif t == "reasoning":
                    content.append({"type": "thinking", "thinking": c.get("text", "")})
                elif t == "tool":
                    state = c.get("state") or {}
                    content.append({"type": "tool_use", "id": "toolu_" + rand_base62(24),
                                    "name": c.get("name", "tool"), "input": state.get("input")})
            line = {
                "parentUuid": parent, "isSidechain": False, "type": "assistant",
                "message": {"id": str(uuid.uuid4()), "model": "claude-sonnet-4-5",
                            "role": "assistant", "stop_reason": "end_turn", "type": "message",
                            "usage": {"input_tokens": 0, "output_tokens": 0},
                            "content": content},
                "uuid": uid, "timestamp": ts, "cwd": directory,
                "sessionId": session_id, "version": _CLAUDE_VERSION, "gitBranch": "HEAD",
            }
        lines.append(line)
        parent = uid
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    return path


def _claude_index_entry(directory):
    """Best-effort: mark the project trusted in ~/.claude.json so claude --resume
    lists it. The session list itself comes from scanning the transcript dirs.
    Config path: $CLAUDE_CONFIG_DIR/.claude.json, else ~/.claude.json (home)."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    cfg = (Path(env).expanduser() / ".claude.json") if env else Path.home() / ".claude.json"
    try:
        data = json.loads(cfg.read_text()) if cfg.is_file() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    entry = data.setdefault("projects", {}).setdefault(directory, {})
    if not entry.get("hasTrustDialogAccepted"):
        entry["hasTrustDialogAccepted"] = True
    try:
        cfg.write_text(json.dumps(data, indent=2))
    except OSError:
        pass


def move_opencode_to_claude(conn, sid, directory, delete_original=False):
    """Copy an opencode session into a Claude Code project as a .jsonl transcript."""
    if not isinstance(directory, str) or not directory:
        raise HttpError(400, "directory is required")
    if conn.execute("SELECT id FROM session_v2 WHERE id = ?", (sid,)).fetchone() is None:
        raise HttpError(404, "session not found")
    msgs = []
    for m in conn.execute(
        "SELECT type, data, time_created FROM session_message WHERE session_id = ? ORDER BY seq",
        (sid,)).fetchall():
        d = json.loads(m["data"]) if isinstance(m["data"], str) else m["data"]
        if m["type"] == "user":
            msgs.append({"type": "user", "time_created": m["time_created"],
                         "data": {"text": d.get("text", "")}})
        else:
            msgs.append({"type": "assistant", "time_created": m["time_created"],
                         "data": {"content": d.get("content") or []}})
    session_id = str(uuid.uuid4())
    _write_claude_transcript(directory, msgs, session_id)
    _claude_index_entry(directory)
    _CLAUDE_CACHE.clear(); _CLAUDE_CWD.clear()
    if delete_original:
        conn.execute("DELETE FROM session_v2 WHERE id = ?", (sid,))  # messages cascade
        conn.commit()
    return {"id": f"{_claude_slug_from_path(directory)}::{session_id}", "directory": directory}


def move_cursor_to_claude(conn, sid, directory, delete_original=False):
    """Copy a Cursor .jsonl transcript into a Claude Code project."""
    if not isinstance(directory, str) or not directory:
        raise HttpError(400, "directory is required")
    cslug, cuid = sid.split("::", 1)  # `uuid` is also a module; don't shadow it
    path = _cursor_transcript_path(cslug, cuid)
    if not path.is_file():
        raise HttpError(404, "conversation not found")
    msgs = _parse_cursor_transcript(path)
    session_id = str(uuid.uuid4())
    _write_claude_transcript(directory, msgs, session_id)
    _claude_index_entry(directory)
    _CLAUDE_CACHE.clear(); _CLAUDE_CWD.clear()
    if delete_original:
        path.unlink(missing_ok=True)
        for ext in (".title", ".archived"):
            (path.parent / f"{cuid}{ext}").unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass
    return {"id": f"{_claude_slug_from_path(directory)}::{session_id}", "directory": directory}


def _opencode_default_model(conn):
    """Return the model object (dict) the real opencode app last used, as a
    fallback for moved-in sessions. Cursor transcripts carry no model, but the
    opencode assistant-message schema requires a non-null model object, so we
    reuse the most recent real one. Returns None if the DB has none."""
    try:
        row = conn.execute(
            "SELECT model FROM session_v2 WHERE model IS NOT NULL "
            "ORDER BY time_created DESC LIMIT 1").fetchone()
        if row and row["model"]:
            return json.loads(row["model"])
    except (sqlite3.Error, json.JSONDecodeError, TypeError, KeyError):
        pass
    return None


def _opencode_tool_content(item, idx, now):
    """Normalize a parsed tool content item into the shape opencode's
    assistant-message schema accepts. The real app rejects a completed tool
    whose `state.content` is an empty array, and requires `id`/`executed` and
    a `time` object, so we fill those in."""
    state = dict(item.get("state") or {})
    content = state.get("content")
    if not content:
        content = [{"type": "text", "text": ""}]
    state["content"] = content
    return {
        "type": "tool",
        "name": item.get("name", "tool"),
        "id": item.get("id") or f"call_0_{idx}",
        "executed": True,
        "time": {"created": now},
        "state": state,
    }


def move_cursor_to_opencode(conn, sid, directory, delete_original=False):
    """Copy a Cursor .jsonl transcript into the opencode DB as a session.

    Parses the transcript into the unified message shape, creates a session_v2
    row (under the given project directory) and one session_message row per
    turn. Cursor transcripts carry no model/agent or timestamps, so the new
    session is stamped with the current version/agent and now(). The assistant
    messages are normalized to the exact shape the real opencode app decodes
    (non-null model, time.completed, and well-formed tool content) so the
    conversation loads in the app, not just in OpenCrup.
    """
    if not isinstance(directory, str) or not directory:
        raise HttpError(400, "directory is required")
    slug, uuid = sid.split("::", 1)
    path = _cursor_transcript_path(slug, uuid)
    if not path.is_file():
        raise HttpError(404, "conversation not found")
    msgs = _parse_cursor_transcript(path)
    now = now_ms()
    project_id = resolve_project(conn, directory)
    model = _opencode_default_model(conn)
    new_sid = "ses_" + rand_base62(26)
    conn.execute(
        """INSERT INTO session_v2
           (id, project_id, slug, directory, title, version, agent, model, time_created, time_updated)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (new_sid, project_id, random_slug(), directory, _cursor_title(path, uuid),
         OPENCODE_VERSION, "build",
         json.dumps(model) if model else None, now, now),
    )
    for i, m in enumerate(msgs):
        d = m["data"]
        if m["type"] == "user":
            data = {"time": {"created": now}, "text": d.get("text", ""), "files": [], "agents": []}
        else:
            content = []
            for idx, c in enumerate(d.get("content") or []):
                if c.get("type") == "tool":
                    content.append(_opencode_tool_content(c, idx, now))
                else:
                    content.append(c)
            data = {"time": {"created": now, "completed": now + 1}, "agent": "build",
                    "model": model, "content": content}
        conn.execute(
            """INSERT INTO session_message
               (id, session_id, type, seq, time_created, time_updated, data)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("msg_" + rand_base62(26), new_sid, m["type"], i + 1, now, now, json.dumps(data)),
        )
    conn.commit()
    if delete_original:
        path.unlink(missing_ok=True)
        for ext in (".title", ".archived"):
            (path.parent / f"{uuid}{ext}").unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass
    return {"id": new_sid, "directory": directory}


def cursor_update_session(sid, patch):
    slug, uuid = sid.split("::", 1)
    path = _cursor_transcript_path(slug, uuid)
    if not path.is_file():
        raise HttpError(404, "conversation not found")
    if "title" in patch:
        (path.parent / f"{uuid}.title").write_text(str(patch["title"]))
    if "archived" in patch:
        marker = path.parent / f"{uuid}.archived"
        if patch["archived"]:
            marker.write_text("")
        elif marker.is_file():
            marker.unlink()
    return cursor_get_session(sid)


def _cursor_purge_stores(slug, uuid):
    """Remove a Cursor conversation from every local store: the transcript,
    the store.db blob store, the search index, the cloud-sync copy, UI state,
    and telemetry. Returns the list of stores actually touched."""
    home = Path.home()
    cursor_dir = home / ".cursor"
    app_dir = _cursor_appdata_dir()
    removed = []

    # 1. transcript (.jsonl)
    tdir = cursor_projects_dir() / slug / "agent-transcripts" / uuid
    if tdir.is_dir():
        shutil.rmtree(tdir, ignore_errors=True)
        removed.append("transcript")

    # 2. store.db blob store (encrypted reasoning)
    for d in (cursor_dir / "chats").glob(f"*/{uuid}"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            removed.append("store.db")
            break

    # 3. conversation-search.db (index + FTS + candidates)
    db = app_dir / "User" / "globalStorage" / "conversation-search.db"
    if db.is_file():
        try:
            c = sqlite3.connect(db, timeout=15)
            rows = c.execute("select id, fts_rowid from conversations where id = ?", (uuid,)).fetchall()
            cand = c.execute("delete from conversation_search_candidates where id = ?", (uuid,)).rowcount
            if rows:
                c.executemany("delete from conversations where id = ?", [(i,) for i, _ in rows])
                try:
                    c.executemany("delete from conversation_fts where rowid = ?", [(fr,) for _, fr in rows])
                except sqlite3.Error:
                    pass
            c.commit()
            if rows or cand:
                removed.append("search index")
        except sqlite3.Error:
            pass

    # 4. AgentStores (cloud-sync copy) — 3.x keeps it under %LOCALAPPDATA%
    #    Cursor, older versions under %APPDATA%; check both. Includes the
    #    .control metadata dir.
    local_appdata = os.environ.get("LOCALAPPDATA")
    store_roots = [app_dir / "AgentStores" / "cursor_agent_stores"]
    if local_appdata:
        store_roots.append(Path(local_appdata) / "Cursor" / "AgentStores"
                           / "cursor_agent_stores")
    for root in store_roots:
        if not root.is_dir():
            continue
        for d in root.glob(uuid):
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
                removed.append("cloud sync")
                break
        ctrl = root / ".control" / uuid
        if ctrl.is_dir():
            shutil.rmtree(ctrl, ignore_errors=True)
            removed.append("agent store control")

    # 5. state.vscdb (UI / glass state + composer store)
    #    The app lists from composerHeaders (3.x) and loads from the global
    #    cursorDiskKV (composer record + bubbles), so a purge must clear those
    #    too or the conversation keeps showing in the real Cursor app.
    db = app_dir / "User" / "globalStorage" / "state.vscdb"
    if db.is_file():
        try:
            c = sqlite3.connect(db, timeout=15)
            n = c.execute("delete from ItemTable where key like ?", (f"%{uuid}%",)).rowcount
            try:
                n += c.execute("delete from cursorDiskKV where key = ?",
                               (f"composerData:{uuid}",)).rowcount
                n += c.execute("delete from cursorDiskKV where key like ?",
                               (f"bubbleId:{uuid}:%",)).rowcount
                # the 3.x listing table — the row that keeps it visible
                has_headers = c.execute(
                    "select count(*) from sqlite_master"
                    " where type='table' and name='composerHeaders'").fetchone()[0]
                if has_headers:
                    n += c.execute("delete from composerHeaders where composerId = ?",
                                   (uuid,)).rowcount
            except sqlite3.Error:
                pass
            c.commit()
            if n:
                removed.append("ui state")
        except sqlite3.Error:
            pass

    # 5b. workspace stores — 2.x workspaces keep the sidebar list in
    #     ItemTable composer.composerData; 3.x workspaces carry a local
    #     composerHeaders table too. Clean both, wherever present.
    ws_root = app_dir / "User" / "workspaceStorage"
    if ws_root.is_dir():
        for wdb in ws_root.glob("*/state.vscdb"):
            try:
                c = sqlite3.connect(str(wdb), timeout=15)
                row = c.execute(
                    "SELECT value FROM ItemTable WHERE key='composer.composerData'"
                ).fetchone()
                if row:
                    data = json.loads(row[0])
                    composers = data.get("allComposers") or []
                    if any(c0.get("composerId") == uuid for c0 in composers):
                        data["allComposers"] = [c0 for c0 in composers
                                                if c0.get("composerId") != uuid]
                        for key in ("selectedComposerIds", "lastFocusedComposerIds"):
                            if uuid in (data.get(key) or []):
                                data[key] = [x for x in data[key] if x != uuid]
                        c.execute("UPDATE ItemTable SET value=? WHERE key='composer.composerData'",
                                  (json.dumps(data),))
                n = 0
                try:
                    n = c.execute("delete from composerHeaders where composerId = ?",
                                  (uuid,)).rowcount
                except sqlite3.Error:
                    n = 0
                c.commit()
                c.close()
                if row or n:
                    removed.append("workspace list")
                    continue
            except (sqlite3.Error, json.JSONDecodeError, OSError):
                pass

    # 6. ai-tracking (telemetry)
    db = cursor_dir / "ai-tracking" / "ai-code-tracking.db"
    if db.is_file():
        try:
            c = sqlite3.connect(db, timeout=15)
            tables = [r[0] for r in c.execute("select name from sqlite_master where type='table'")]
            tot = 0
            for t in tables:
                for col in [r[1] for r in c.execute(f"pragma table_info('{t}')")]:
                    try:
                        tot += c.execute(f"delete from '{t}' where '{col}' like ?", (f"%{uuid}%",)).rowcount
                    except sqlite3.Error:
                        pass
            c.commit()
            if tot:
                removed.append("telemetry")
        except sqlite3.Error:
            pass

    _CURSOR_CACHE.clear()
    return removed


def cursor_delete_session(sid):
    slug, uuid = sid.split("::", 1)
    path = _cursor_transcript_path(slug, uuid)
    if not path.is_file():
        raise HttpError(404, "conversation not found")
    removed = _cursor_purge_stores(slug, uuid)
    return {"deleted": sid, "stores": removed}


def cursor_purge_session(sid):
    slug, uuid = sid.split("::", 1)
    removed = _cursor_purge_stores(slug, uuid)
    return {"purged": sid, "stores": removed}


def cursor_bulk_sessions(body):
    action = body.get("action")
    ids = body.get("ids")
    if not isinstance(ids, list) or not ids:
        raise HttpError(400, "ids must be a non-empty array")
    if action not in ("delete", "archive", "unarchive"):
        raise HttpError(400, "action must be one of: delete, archive, unarchive")
    done = []
    for sid in ids:
        slug, uuid = sid.split("::", 1)
        path = _cursor_transcript_path(slug, uuid)
        if not path.is_file():
            continue
        if action == "delete":
            _cursor_purge_stores(slug, uuid)
        else:
            marker = path.parent / f"{uuid}.archived"
            if action == "archive":
                marker.write_text("")
            elif marker.is_file():
                marker.unlink()
        done.append(sid)
    _CURSOR_CACHE.clear()
    return {"action": action, "affected": len(done), "ids": done}


def cursor_update_message(sid, mid, body):
    text = body.get("text")
    if not isinstance(text, str):
        raise HttpError(400, "text is required")
    slug, uuid = sid.split("::", 1)
    path = _cursor_transcript_path(slug, uuid)
    if not path.is_file():
        raise HttpError(404, "conversation not found")
    lines = path.read_text(errors="replace").splitlines()
    try:
        idx = int(mid)
        obj = json.loads(lines[idx])
    except (ValueError, IndexError, json.JSONDecodeError):
        raise HttpError(404, "message not found")
    content = (obj.get("message") or {}).get("content") or []
    for c in content:
        if isinstance(c, dict) and c.get("type") == "text":
            c["text"] = text
            break
    else:
        content.append({"type": "text", "text": text})
        obj.setdefault("message", {})["content"] = content
    lines[idx] = json.dumps(obj, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n")
    _CURSOR_CACHE.clear()
    return {"updated": mid}


def cursor_delete_message(sid, mid):
    slug, uuid = sid.split("::", 1)
    path = _cursor_transcript_path(slug, uuid)
    if not path.is_file():
        raise HttpError(404, "conversation not found")
    lines = path.read_text(errors="replace").splitlines()
    try:
        idx = int(mid)
        lines.pop(idx)
    except (ValueError, IndexError):
        raise HttpError(404, "message not found")
    path.write_text("\n".join(lines) + "\n")
    _CURSOR_CACHE.clear()
    return {"deleted": mid}


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "OpenCrup"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep stdout clean
        pass

    # -- helpers ------------------------------------------------------------
    def _send_json(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get("content-length") or 0)
        if length > 5 * 1024 * 1024:
            raise HttpError(413, "body too large")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise HttpError(400, "invalid JSON body")

    def _serve_static(self, path):
        rel = "index.html" if path == "/" else path.lstrip("/")
        public_root = str(PUBLIC_DIR.resolve())
        file = (PUBLIC_DIR / rel).resolve()
        if not str(file).startswith(public_root) or not file.is_file():
            if path.startswith("/api/"):
                return self._send_json(404, {"error": "not found"})
            file = PUBLIC_DIR / "index.html"  # SPA fallback
            if not file.is_file():
                return self._send_json(404, {"error": "not found"})
        data = file.read_bytes()
        self.send_response(200)
        self.send_header("content-type", MIME.get(file.suffix, "application/octet-stream"))
        self.send_header("content-length", str(len(data)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # -- routing ------------------------------------------------------------
    def _handle_cursor(self, method, path, qs):
        if not path.startswith("/api/cursor"):
            return False
        if method == "GET":
            if path == "/api/cursor/env":
                return self._send_json(200, {
                    "home": str(Path.home()),
                    "dir": str(cursor_projects_dir()),
                    "count": sum(1 for _ in _iter_cursor_transcripts()),
                })
            if path == "/api/cursor/projects":
                return self._send_json(200, cursor_projects())
            if path == "/api/cursor/sessions":
                return self._send_json(200, cursor_sessions(
                    project=qs.get("project", [None])[0],
                    q=qs.get("q", [None])[0],
                    include_archived=qs.get("archived", ["0"])[0] == "1",
                    limit=qs.get("limit", ["200"])[0],
                ))
            m = re.match(r"^/api/cursor/sessions/([^/]+)$", path)
            if m:
                return self._send_json(200, cursor_get_session(unquote(m.group(1))))
            return self._send_json(404, {"error": "not found"})
        if method == "POST":
            body = self._read_body()
            if path == "/api/cursor/sessions/bulk":
                return self._send_json(200, cursor_bulk_sessions(body))
            m = re.match(r"^/api/cursor/sessions/([^/]+)/purge$", path)
            if m:
                return self._send_json(200, cursor_purge_session(unquote(m.group(1))))
            m = re.match(r"^/api/cursor/sessions/([^/]+)/move-to-(opencode|claude)$", path)
            if m:
                with closing(connect()) as conn:
                    if m.group(2) == "opencode":
                        return self._send_json(200, move_cursor_to_opencode(
                            conn, unquote(m.group(1)), body.get("directory"),
                            bool(body.get("delete_original"))))
                    return self._send_json(200, move_cursor_to_claude(
                        conn, unquote(m.group(1)), body.get("directory"),
                        bool(body.get("delete_original"))))
            return self._send_json(404, {"error": "not found"})
        if method == "PATCH":
            body = self._read_body()
            m = re.match(r"^/api/cursor/sessions/([^/]+)/messages/([^/]+)$", path)
            if m:
                return self._send_json(200, cursor_update_message(unquote(m.group(1)), unquote(m.group(2)), body))
            m = re.match(r"^/api/cursor/sessions/([^/]+)$", path)
            if m:
                return self._send_json(200, cursor_update_session(unquote(m.group(1)), body))
            return self._send_json(404, {"error": "not found"})
        if method == "DELETE":
            m = re.match(r"^/api/cursor/sessions/([^/]+)/messages/([^/]+)$", path)
            if m:
                return self._send_json(200, cursor_delete_message(unquote(m.group(1)), unquote(m.group(2))))
            m = re.match(r"^/api/cursor/sessions/([^/]+)$", path)
            if m:
                return self._send_json(200, cursor_delete_session(unquote(m.group(1))))
            return self._send_json(404, {"error": "not found"})
        return self._send_json(405, {"error": "method not allowed"})

    def _handle_claude(self, method, path, qs):
        if method == "GET":
            if path == "/api/claude/env":
                return self._send_json(200, {
                    "home": str(Path.home()),
                    "dir": str(_claude_projects_dir()),
                    "count": sum(1 for _ in _iter_claude_transcripts()),
                })
            if path == "/api/claude/projects":
                return self._send_json(200, claude_projects())
            if path == "/api/claude/sessions":
                return self._send_json(200, claude_sessions(
                    project=qs.get("project", [None])[0],
                    q=qs.get("q", [None])[0],
                    include_archived=qs.get("archived", ["0"])[0] == "1",
                    limit=qs.get("limit", ["200"])[0],
                ))
            m = re.match(r"^/api/claude/sessions/([^/]+)$", path)
            if m:
                return self._send_json(200, claude_get_session(unquote(m.group(1))))
            return self._send_json(404, {"error": "not found"})
        if method == "POST":
            body = self._read_body()
            m = re.match(r"^/api/claude/sessions/([^/]+)/move-to-(opencode|cursor)$", path)
            if m:
                sid = unquote(m.group(1))
                with closing(connect()) as conn:
                    if m.group(2) == "opencode":
                        return self._send_json(200, move_claude_to_opencode(
                            conn, sid, body.get("directory"),
                            bool(body.get("delete_original"))))
                    return self._send_json(200, move_claude_to_cursor(
                        conn, sid, body.get("directory"),
                        bool(body.get("delete_original"))))
            return self._send_json(404, {"error": "not found"})
        return self._send_json(405, {"error": "method not allowed"})

    def _handle(self, method):
        url = urlparse(self.path)
        path = url.path
        qs = parse_qs(url.query)
        try:
            # Cursor routes send their own response; gate on the path prefix
            # (not the return value) so we never fall through to opencode routing.
            if path.startswith("/api/cursor"):
                self._handle_cursor(method, path, qs)
                return
            if path.startswith("/api/claude"):
                self._handle_claude(method, path, qs)
                return
            with closing(connect()) as conn:
                if method == "GET":
                    if path == "/api/sources":
                        return self._send_json(200, detect_sources())
                    if path == "/api/env":
                        return self._send_json(200, {
                            "home": str(Path.home()),
                            "db": str(DB_PATH),
                            "version": detect_version(),
                        })
                    if path == "/api/diag":
                        return self._send_json(200, cursor_diag())
                    if path == "/api/diag/workspace":
                        return self._send_json(
                            200, cursor_workspace_diag(
                                qs.get("dir", [None])[0]))
                    if path == "/api/diag/composer":
                        return self._send_json(
                            200, cursor_composer_diag(
                                qs.get("uuid", [None])[0]))
                    if path == "/api/projects":
                        return self._send_json(200, list_projects(conn))
                    if path == "/api/models":
                        return self._send_json(200, list_models(conn))
                    if path == "/api/sessions":
                        return self._send_json(200, list_sessions(conn,
                            project_id=qs.get("project_id", [None])[0],
                            q=qs.get("q", [None])[0],
                            include_archived=qs.get("archived", ["0"])[0] == "1",
                            limit=qs.get("limit", ["200"])[0],
                        ))
                    m = re.match(r"^/api/sessions/([^/]+)$", path)
                    if m:
                        return self._send_json(200, get_session(conn, unquote(m.group(1))))
                    if path.startswith("/api/"):
                        return self._send_json(404, {"error": "not found"})
                    return self._serve_static(path)

                if method == "POST":
                    body = self._read_body()
                    if path == "/api/sessions":
                        return self._send_json(201, create_session(conn, body))
                    if path == "/api/sessions/bulk":
                        return self._send_json(200, bulk_sessions(conn, body))
                    if path == "/api/resolve-dir":
                        return self._send_json(200, {"path": resolve_dir(
                            body.get("name"), body.get("children"))})
                    if path == "/api/sources/cursor":
                        return self._send_json(200, add_cursor_source(body.get("path", "")))
                    m = re.match(r"^/api/sessions/([^/]+)/move-to-(cursor|claude)$", path)
                    if m:
                        if m.group(2) == "cursor":
                            return self._send_json(200, move_opencode_to_cursor(
                                conn, unquote(m.group(1)), body.get("directory"),
                                bool(body.get("delete_original"))))
                        return self._send_json(200, move_opencode_to_claude(
                            conn, unquote(m.group(1)), body.get("directory"),
                            bool(body.get("delete_original"))))
                    return self._send_json(404, {"error": "not found"})

                if method == "PATCH":
                    body = self._read_body()
                    m = re.match(r"^/api/sessions/([^/]+)$", path)
                    if m:
                        return self._send_json(200, update_session(conn, unquote(m.group(1)), body))
                    m = re.match(r"^/api/messages/([^/]+)$", path)
                    if m:
                        return self._send_json(200, update_message(conn, unquote(m.group(1)), body))
                    return self._send_json(404, {"error": "not found"})

                if method == "DELETE":
                    m = re.match(r"^/api/sessions/([^/]+)$", path)
                    if m:
                        return self._send_json(200, delete_session(conn, unquote(m.group(1))))
                    m = re.match(r"^/api/messages/([^/]+)$", path)
                    if m:
                        return self._send_json(200, delete_message(conn, unquote(m.group(1))))
                    return self._send_json(404, {"error": "not found"})

                return self._send_json(405, {"error": "method not allowed"})
        except HttpError as e:
            return self._send_json(e.status, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            print(f"error handling {method} {path}: {e}")
            return self._send_json(500, {"error": str(e) or "internal error"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_DELETE(self):
        self._handle("DELETE")


def main():
    if not DB_PATH.exists():
        print(f"opencode database not found at {DB_PATH}")
        print("Set OPENCODE_DB to point at the right file.")
        raise SystemExit(1)
    with closing(connect()) as conn:
        pass  # ensure WAL mode is set (persistent)
    print(f"OpenCrup running:  http://{HOST}:{PORT}")
    print(f"database: {DB_PATH}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
