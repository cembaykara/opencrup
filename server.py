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
    row = conn.execute("SELECT id FROM project WHERE worktree = ?", (directory,)).fetchone()
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
    return {
        "opencode": {"found": oc_found, "path": str(DB_PATH), "count": oc_count},
        "cursor": {"found": cur_found, "path": str(cursor_projects_dir()), "count": cur_count},
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
    slug = _cursor_slug_from_path(directory)
    uuid = secrets.token_hex(16)
    tdir = cursor_projects_dir() / slug / "agent-transcripts" / uuid
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / f"{uuid}.jsonl").write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    # remember the real path so the project shows a clean label, not the raw slug
    try:
        (cursor_projects_dir() / slug / ".opencrup-path").write_text(directory)
    except OSError:
        pass
    _CURSOR_CACHE.clear()
    if delete_original:
        conn.execute("DELETE FROM session_v2 WHERE id = ?", (sid,))  # messages cascade
        conn.commit()
    return {"id": f"{slug}::{uuid}", "slug": slug, "uuid": uuid, "directory": directory}


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
        ws = Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "workspaceStorage"
        for j in ws.glob("*/workspace.json"):
            try:
                d = json.loads(j.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            f = d.get("folder") or d.get("workspace")
            if not f:
                continue
            f = f.replace("file://", "")
            s = f.lstrip("/").replace("/", "-").replace(".", "-").replace("%20", "-").replace(" ", "-")
            _CURSOR_PATHS.setdefault(s, f)
    if slug in _CURSOR_PATHS:
        return _CURSOR_PATHS[slug]
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
    """Inverse of the slug formula above: a real folder path -> its Cursor slug."""
    p = str(path)
    if p.startswith("file://"):
        p = p[len("file://"):]
    return p.lstrip("/").replace("/", "-").replace(".", "-").replace("%20", "-").replace(" ", "-")


def cursor_projects():
    counts = {}
    for slug, _uuid, _path in _iter_cursor_transcripts():
        counts[slug] = counts.get(slug, 0) + 1
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
        })
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
        "messages": _parse_cursor_transcript(path),
    }


def move_cursor_to_opencode(conn, sid, directory, delete_original=False):
    """Copy a Cursor .jsonl transcript into the opencode DB as a session.

    Parses the transcript into the unified message shape, creates a session_v2
    row (under the given project directory) and one session_message row per
    turn. Cursor transcripts carry no model/agent or timestamps, so the new
    session is stamped with the current version/agent and now().
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
    new_sid = "ses_" + rand_base62(26)
    conn.execute(
        """INSERT INTO session_v2
           (id, project_id, slug, directory, title, version, agent, model, time_created, time_updated)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (new_sid, project_id, random_slug(), directory, _cursor_title(path, uuid),
         OPENCODE_VERSION, "build", None, now, now),
    )
    for i, m in enumerate(msgs):
        d = m["data"]
        if m["type"] == "user":
            data = {"time": {"created": now}, "text": d.get("text", ""), "files": [], "agents": []}
        else:
            data = {"time": {"created": now}, "agent": "build", "model": None,
                    "content": d.get("content") or []}
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
            c = sqlite3.connect(db)
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

    # 4. AgentStores (cloud-sync copy)
    for d in (app_dir / "AgentStores" / "cursor_agent_stores").glob(uuid):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            removed.append("cloud sync")
            break

    # 5. state.vscdb (UI / glass state)
    db = app_dir / "User" / "globalStorage" / "state.vscdb"
    if db.is_file():
        try:
            c = sqlite3.connect(db)
            n = c.execute("delete from ItemTable where key like ?", (f"%{uuid}%",)).rowcount
            c.commit()
            if n:
                removed.append("ui state")
        except sqlite3.Error:
            pass

    # 6. ai-tracking (telemetry)
    db = cursor_dir / "ai-tracking" / "ai-code-tracking.db"
    if db.is_file():
        try:
            c = sqlite3.connect(db)
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
        rel = "/index.html" if path == "/" else path
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
            m = re.match(r"^/api/cursor/sessions/([^/]+)/move-to-opencode$", path)
            if m:
                with closing(connect()) as conn:
                    return self._send_json(200, move_cursor_to_opencode(
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
                    m = re.match(r"^/api/sessions/([^/]+)/move-to-cursor$", path)
                    if m:
                        return self._send_json(200, move_opencode_to_cursor(
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
