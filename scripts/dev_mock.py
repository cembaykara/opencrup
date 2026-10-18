#!/usr/bin/env python3
"""Throwaway dev build: serve OpenCrup against a mock opencode DB (fake data).

Creates a throwaway SQLite DB (in a temp dir) populated with a few fake
projects/sessions/messages — no real conversations — then launches the normal
server pointed at it on a separate port, so you can demo the opencode view
without exposing your real data.

Usage:
    python3 scripts/dev_mock.py            # served on http://127.0.0.1:4322
    python3 scripts/dev_mock.py -p 5000    # custom port
"""
import os
import sys
import json
import sqlite3
import tempfile
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # repo root (server.py lives there)
PORT = 4322
for i, a in enumerate(sys.argv):
    if a == "-p" and i + 1 < len(sys.argv):
        PORT = int(sys.argv[i + 1])


def now_ms():
    return int(time.time() * 1000)


MODEL = {"id": "gpt-4o", "providerID": "openai"}


def user_msg(text, t):
    return {"time": {"created": t}, "text": text, "files": [], "agents": []}


def assistant_msg(content, t):
    return {
        "time": {"created": t, "streamed": t + 4000, "completed": t + 9000},
        "agent": "build",
        "model": MODEL,
        "content": content,
    }


def reasoning(text, t):
    return {
        "type": "reasoning", "text": text,
        "state": {"reasoningField": "reasoning_content"},
        "time": {"created": t, "completed": t + 2000},
    }


def tool(name, input_, output, t):
    return {
        "type": "tool", "id": f"call_{t}", "name": name, "executed": True,
        "state": {"status": "completed", "input": input_,
                  "content": [{"type": "text", "text": output}]},
    }


def text(t):
    return {"type": "text", "text": t}


# --- mock content -----------------------------------------------------------
PROJECTS = [
    ("proj_webapp", "/Users/dev/webapp", "webapp"),
    ("proj_api", "/Users/dev/api-server", "api-server"),
]

SESSIONS = [
    {
        "id": "ses_webapp_1", "project": "proj_webapp", "slug": "fix-login-redirect",
        "title": "Fix login redirect loop",
        "tokens": (1840, 620, 310), "cost": 0.021,
        "user": "The login page keeps bouncing straight back to /login after I "
                "submit valid credentials. It works in dev but not in prod. "
                "Can you figure out what's going on?",
        "content": [
            reasoning("A redirect loop after login usually means the session cookie "
                      "isn't being set or read back. In prod the cookie flags (Secure, "
                      "SameSite) or the domain can differ from dev. Let me check the "
                      "auth middleware and how the cookie is written.", 0),
            tool("shell", {"command": "grep -rn 'set_cookie\\|Set-Cookie' src/auth"},
                 "src/auth/session.py:42: resp.set_cookie('sid', token, httponly=True, secure=True, samesite='Lax')\n"
                 "src/auth/session.py:58: resp.set_cookie('sid', '', max_age=0)", 0),
            text("Found it. The cookie is written with `secure=True`, but prod is served "
                 "over plain HTTP behind the load balancer, so the browser drops the "
                 "cookie and the next request is unauthenticated → redirect back to "
                 "`/login`.\n\n**Fix:** set `secure` from the request scheme:\n\n"
                 "```python\nresp.set_cookie('sid', token, httponly=True,\n"
                 "                           secure=request.scheme == 'https', samesite='Lax')\n```\n\n"
                 "Or terminate TLS at the LB and forward `X-Forwarded-Proto`."),
        ],
    },
    {
        "id": "ses_webapp_2", "project": "proj_webapp", "slug": "add-dark-mode",
        "title": "Add a dark mode toggle",
        "tokens": (1210, 480, 190), "cost": 0.014,
        "user": "Add a dark mode toggle in the settings page. It should remember the "
                "choice between visits and respect the system preference on first load.",
        "content": [
            reasoning("Persist the choice in localStorage, default to prefers-color-scheme "
                      "when unset, and drive it with a CSS custom-property theme. I'll add a "
                      "data-theme attribute on <html> and a small toggle in settings.", 0),
            text("Done. Changes:\n\n"
                 "- Added `theme.js` that reads `localStorage.theme`, falls back to "
                 "`prefers-color-scheme`, and sets `document.documentElement.dataset.theme`.\n"
                 "- Moved all colors to CSS variables under `:root` / `[data-theme='dark']`.\n"
                 "- Added a toggle in **Settings → Appearance** that flips the attribute and persists it.\n\n"
                 "The first visit follows the OS setting; once you toggle, your choice wins."),
        ],
    },
    {
        "id": "ses_api_1", "project": "proj_api", "slug": "rate-limit-search",
        "title": "Rate limit the /search endpoint",
        "tokens": (2350, 710, 420), "cost": 0.028,
        "user": "Our /search endpoint is getting hammered by a few heavy clients and it's "
                "slowing everything down. Add per-IP rate limiting.",
        "content": [
            reasoning("A sliding-window counter per IP is the simplest robust approach. "
                      "I'll back it with an in-memory dict with a TTL sweep (good enough for a "
                      "single instance) and return 429 with a Retry-After header when exceeded.", 0),
            tool("read", {"path": "src/middleware.py"},
                 "from fastapi import Request\nfrom starlette.middleware.base import BaseHTTPMiddleware\n\n"
                 "class CORSMiddleware(BaseHTTPMiddleware):\n    ...", 0),
            text("Added a `RateLimitMiddleware`:\n\n"
                 "```python\nLIMIT = 120  # requests / minute per IP\n\n"
                 "class RateLimitMiddleware(BaseHTTPMiddleware):\n"
                 "    async def dispatch(self, request, call_next):\n"
                 "        ip = request.client.host\n"
                 "        if window_full(ip):\n"
                 "            return JSONResponse({'error': 'rate limited'}, status_code=429,\n"
                 "                                headers={'Retry-After': '60'})\n"
                 "        return await call_next(request)\n```\n\n"
                 "Applied only to `/search*`. For multiple instances, swap the in-memory counter "
                 "for Redis — the interface stays the same."),
        ],
    },
    {
        "id": "ses_api_2", "project": "proj_api", "slug": "async-handlers",
        "title": "Migrate routes to async handlers",
        "tokens": (1620, 540, 260), "cost": 0.019,
        "user": "We still have a few sync route handlers blocking the event loop. "
                "Migrate the remaining ones to async.",
        "content": [
            reasoning("The sync handlers call the DB via a blocking driver. I'll wrap those in a "
                      "threadpool (run_in_executor) so the event loop stays free, and mark the "
                      "handlers async.", 0),
            text("Migrated the remaining sync handlers:\n\n"
                 "- `GET /users` and `POST /users` now `async def`.\n"
                 "- Blocking DB calls wrapped with `await run_in_executor(None, db.query, ...)`.\n"
                 "- Verified the event loop no longer blocks under load (p95 latency dropped from 340ms to 45ms).\n\n"
                 "Next up: the file-upload handler, which needs a streaming body."),
        ],
    },
]


def build_mock_db(path):
    path.unlink(missing_ok=True)
    c = sqlite3.connect(str(path))
    c.executescript(
        """
        CREATE TABLE project (
          id text PRIMARY KEY, worktree text NOT NULL, vcs text, name text,
          icon_url text, icon_url_override text, icon_color text,
          time_created integer NOT NULL, time_updated integer NOT NULL,
          time_initialized integer, time_active integer DEFAULT 0 NOT NULL,
          sandboxes text NOT NULL, commands text, time_archived integer);
        CREATE TABLE session_v2 (
          id text PRIMARY KEY, project_id text NOT NULL, workspace_id text,
          parent_id text, fork_session_id text, fork_boundary text,
          slug text NOT NULL, directory text NOT NULL, path text, title text,
          version text NOT NULL, share_url text, summary_additions integer,
          summary_deletions integer, summary_files integer, summary_diffs text,
          metadata text, cost real DEFAULT 0 NOT NULL,
          tokens_input integer DEFAULT 0 NOT NULL, tokens_output integer DEFAULT 0 NOT NULL,
          tokens_reasoning integer DEFAULT 0 NOT NULL, tokens_cache_read integer DEFAULT 0 NOT NULL,
          tokens_cache_write integer DEFAULT 0 NOT NULL, revert text, permission text,
          agent text, model text, time_created integer NOT NULL, time_updated integer NOT NULL,
          time_idle integer, time_viewed integer, idle_outcome text, time_compacting integer,
          time_archived integer, time_suspended integer, resume_attempts integer DEFAULT 0 NOT NULL);
        CREATE TABLE session_message (
          id text PRIMARY KEY, session_id text NOT NULL, type text NOT NULL,
          seq integer NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL,
          data text NOT NULL);
        """
    )
    base = now_ms()
    for i, (pid, worktree, name) in enumerate(PROJECTS):
        c.execute(
            "INSERT INTO project (id, worktree, vcs, name, time_created, time_updated, "
            "time_initialized, time_active, sandboxes, commands) "
            "VALUES (?,?,?,?,?,?,?,0,'[]',NULL)",
            (pid, worktree, "git", name, base, base, base),
        )
    for j, s in enumerate(SESSIONS):
        worktree = next(w for p, w, n in PROJECTS if p == s["project"])
        t = base - (len(SESSIONS) - j) * 3600_000  # spread over the last few hours
        tin, tout, treason = s["tokens"]
        c.execute(
            "INSERT INTO session_v2 (id, project_id, slug, directory, title, version, "
            "cost, tokens_input, tokens_output, tokens_reasoning, agent, model, "
            "time_created, time_updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (s["id"], s["project"], s["slug"], worktree, s["title"], "0.1.0",
             s["cost"], tin, tout, treason, "build", MODEL["id"], t, t + 9000),
        )
        # user message
        c.execute(
            "INSERT INTO session_message (id, session_id, type, seq, time_created, time_updated, data) "
            "VALUES (?,?,?,?,?,?,?)",
            (f"{s['id']}_m1", s["id"], "user", 1, t, t, json.dumps(user_msg(s["user"], t))),
        )
        # assistant message
        at = t + 1000
        c.execute(
            "INSERT INTO session_message (id, session_id, type, seq, time_created, time_updated, data) "
            "VALUES (?,?,?,?,?,?,?)",
            (f"{s['id']}_m2", s["id"], "assistant", 2, at, at + 9000,
             json.dumps(assistant_msg(s["content"], at))),
        )
    c.commit()
    c.close()


def main():
    tmp = Path(tempfile.mkdtemp(prefix="opencrup-mock-"))
    db = tmp / "opencode.db"
    build_mock_db(db)
    os.environ["OPENCODE_DB"] = str(db)
    os.environ["PORT"] = str(PORT)
    os.environ["HOST"] = "127.0.0.1"
    print(f"mock opencode DB: {db}")
    sys.path.insert(0, str(BASE))
    import server
    server.main()


if __name__ == "__main__":
    main()
