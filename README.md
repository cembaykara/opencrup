# OpenCrup 💜

> **This is a Vibed Slop to View and edit your agent transcripts.**

✨ The next-gen, hyper-agentic, seamless™ way to peer into the crystal ball of your
AI conversations. OpenCrup refracts every **opencode** + **Cursor** session into one
beautiful dashboard so you can *actually* see what your agents have been up to.

No cap. Zero dependencies. Just Python 3 stdlib doing the most.

![OpenCrup home screen](docs/home.png)

Pick a source, dive in. Only the sources it actually finds show up — plus a `+` to point
it at a Cursor install it couldn't auto-detect.

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
- **Cross-platform source scan** — auto-detects opencode + Cursor on macOS / Windows / Linux; a `+` adds a Cursor install it missed.
- **Project grouping** — everything per project, for both sources.
- **Read** — markdown, collapsible "thinking", tool calls (input + output), system events.
- **Multi-select + bulk** — anchor + shift-click a span, then delete / archive / unarchive.
- **Edit & delete messages** — go in and fix the record.
- **Export** — any session as JSON.
- **Full purge** — delete a Cursor conversation from *all six stores*. No ghosts. No residue. No cap.
- **Move between sources** — relocate a conversation opencode → Cursor or Cursor → opencode, picking the destination from a dropdown of the target's existing projects. It's converted to the target's native format (`.jsonl` ↔ SQLite) and opens in OpenCrup's target view. For Cursor, the `.jsonl` is also written into the target project's `agent-transcripts/` so you can import it into the real Cursor app if you want (Cursor owns it once it indexes it).

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

## 🧪 Dev mode (mock data)

Want to poke at the opencode view without exposing your real conversations? A throwaway
build spins up a temp DB full of fake sessions/projects and serves it on a separate port:

```bash
python3 dev_mock.py            # → http://127.0.0.1:4322 (mock data, temp DB)
python3 dev_mock.py -p 5000    # custom port
```

No real data touched — the DB lives in a temp dir and is gone when you quit.

![OpenCrup opencode view (mock data)](docs/opencode_view.png)

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
| `dev_mock.py` | throwaway dev build — fake opencode data on a separate port |
| `start.sh` | the launcher |

That's it. Five files. A monolith — but a *vibed* one.

## 🔌 Endpoints (quick)

- opencode: `GET/POST /api/sessions`, `GET/PATCH/DELETE /api/sessions/:id`, `PATCH/DELETE /api/messages/:id`
- cursor: the same under `/api/cursor`, plus `POST /api/cursor/sessions/:id/purge`
- move: `POST /api/sessions/:id/move-to-cursor` and `POST /api/cursor/sessions/:id/move-to-opencode` (body: `{directory, delete_original}`)
- sources: `GET /api/sources` (presence + count), `POST /api/sources/cursor` (save a picked path)
- `:id` is `<project-slug>::<transcript-uuid>`

---

<div align="center">

**OpenCrup** — because your agents deserve a crystal ball. 💜

*not a financial advisor · no cap · probably slop*

</div>
