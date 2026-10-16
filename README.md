# OpenCrup 💜

> **This is a Vibed Slop to View and edit your agent transcripts.**

✨ The next-gen, hyper-agentic, seamless™ way to peer into the crystal ball of your
AI conversations. OpenCrup refracts every **opencode** + **Cursor** session into one
beautiful dashboard so you can *actually* see what your agents have been up to.

No cap. Zero dependencies. Just Python 3 stdlib doing the most.

---

## 🚀 The Vibe

Your agents talk. A lot. Across opencode, Cursor, six different local stores,
encrypted blobs, FTS indexes, cloud-sync copies, and telemetry — the whole ecosystem.
OpenCrup is the **single pane of glass** (glass, like Cursor's glass, get it) that
surfaces all of it in one place.

Browse. Search. Group by project. Edit. Delete. Purge from *every* store.
It's giving organization. It's giving control. **Vibe check: passed.**

## ✨ Features (the good stuff)

- **Two sources, one UI** — opencode (SQLite) + Cursor (`.jsonl` transcripts), picked from a home screen.
- **Project grouping** — everything per project, for both sources.
- **Read** — markdown, collapsible "thinking", tool calls (input + output), system events.
- **Multi-select + bulk** — anchor + shift-click a span, then delete / archive / unarchive.
- **Edit & delete messages** — go in and fix the record.
- **Export** — any session as JSON.
- **Full purge** — delete a Cursor conversation from *all six stores*. No ghosts. No residue. No cap.

## 🐘 The Six-Store Purge (where the magic happens)

A single Cursor conversation lives in **six** places. OpenCrup wipes all of them:

| # | Store | What it is |
|---|-------|-----------|
| 1 | `~/.cursor/projects/<slug>/agent-transcripts/<uuid>/` | the transcript (source of truth) |
| 2 | `~/.cursor/chats/<hash>/<uuid>/store.db` | encrypted reasoning blobs |
| 3 | `conversation-search.db` | search index + FTS + candidates |
| 4 | `AgentStores/cursor_agent_stores/<uuid>/` | cloud-sync copy |
| 5 | `state.vscdb` | UI / glass state |
| 6 | `ai-tracking/ai-code-tracking.db` | telemetry |

**Delete = full purge.** There is no "just the DB". It's gone.
(Unless Cursor re-syncs it from the cloud — that's a server-side problem, not our problem. 💅)

## 🏃 Run it

```bash
./start.sh            # → http://127.0.0.1:4321
./start.sh -p 8080    # custom port
# or:
python3 server.py
```

| Env var           | Default                              | Meaning |
|-------------------|--------------------------------------|---------|
| `PORT`            | `4321`                               | HTTP port |
| `HOST`            | `127.0.0.1`                          | bind address (we don't leak vibes to the network) |
| `OPENCODE_DB`     | `~/.local/share/opencode/opencode.db`| opencode DB |
| `CURSOR_PROJECTS` | `~/.cursor/projects`                 | Cursor transcripts root |

## 🤖 Tech (for the non-slop folks)

- Python 3 stdlib only — `http.server` + `sqlite3`. No `pip install`, no build step, no node.
- Binds to `127.0.0.1` by default. Not reachable from the network.
- WAL mode + short transactions → safe to run while opencode itself is live.

## 🧠 Architecture (the real part)

| File | What it is |
|------|-----------|
| `server.py` | the whole backend — routing, opencode DB, Cursor transcript parsing, the six-store purge |
| `public/index.html` | the whole frontend — single file, no framework, no bundler |
| `purge_cursor.py` | standalone purge CLI — `python3 purge_cursor.py <uuid\|prefix> [--dry-run]` |
| `start.sh` | the launcher |

That's it. Four files. A monolith — but a *vibed* one.

## 🔌 Endpoints (quick)

- opencode: `GET/POST /api/sessions`, `GET/PATCH/DELETE /api/sessions/:id`, `PATCH/DELETE /api/messages/:id`
- cursor: the same under `/api/cursor`, plus `POST /api/cursor/sessions/:id/purge`
- `:id` is `<project-slug>::<transcript-uuid>`

---

<div align="center">

**OpenCrup** — because your agents deserve a crystal ball. 💜

*not a financial advisor · no cap · probably slop*

</div>
