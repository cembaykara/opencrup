# OpenCrup — opencode & Cursor AI chat manager

> A local, zero-dependency **viewer and manager for AI agent chat histories**. Read, search, edit, and **move conversations between [opencode](https://opencode.ai) and Cursor** — from one Python 3 dashboard. No install, no build step.

[![Python](https://img.shields.io/badge/python-3.x-478859?labelColor=black)]()
[![Dependencies](https://img.shields.io/badge/deps-none-0097a7?labelColor=black)]()
[![Platform](https://img.shields.io/badge/platform-macOS%20·%20Windows%20·%20Linux-2f74d0?labelColor=black)]()
[![License](https://img.shields.io/badge/license-MIT-d43b4b?labelColor=black)]()

OpenCrup is a local dashboard for your **opencode** and **Cursor** agent conversations. Browse and **search chat history** by project, read markdown, collapsed thinking blocks, and tool calls, edit or delete individual messages, and — the headline feature — **move a conversation from opencode into Cursor (or back)** so it appears in the real app's sidebar with the full history.

## Screenshots

| Home — pick a source | opencode view — read, edit, move |
|---|---|
| ![OpenCrup home screen: choose an opencode or Cursor source and open a conversation](docs/home.png) | ![OpenCrup opencode view: read, edit, and move an AI agent conversation](docs/opencode_view.png) |

## 🚚 Move conversations between opencode and Cursor

The headline act. Take a conversation that started in opencode and drop it into Cursor — or pull one back the other way. OpenCrup converts it to the target's native format **and** injects it into the target app's own stores, so it shows up in the real sidebar and loads with every reply and tool call intact. No re-typing, no copy-paste, no "where did my history go?".

- **opencode → Cursor** — writes the `.jsonl` transcript *and* the composer record, message bubbles, sidebar entry, and search index. The real Cursor app lists it and renders the whole thing — visible text and tool calls, all of it.
- **Cursor → opencode** — imports it into opencode's SQLite store so it lives in the opencode view.
- **Delete** — purge it from *every* store so it's gone from the real app too. No ghosts, no residue.

Pick the destination from a dropdown of the target's existing projects. It defaults to the conversation's own path, so the common case is one click.

## What else it does

Browse, search, and group **AI agent conversations** by project. Read markdown, collapsed thinking blocks, tool calls (input + output), and system events. Edit or delete individual messages. Select a range and delete, archive, or unarchive in bulk. Export a session as JSON.

## Run

Requires Python 3. No install step.

```bash
./start.sh            # http://127.0.0.1:4321
./start.sh -p 8080    # custom port
./start.sh -H 0.0.0.0 # bind address
./start.sh -d /path/to/opencode.db
```

Or `python3 server.py`.

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `4321` | HTTP port |
| `HOST` | `127.0.0.1` | Bind address |
| `OPENCODE_DB` | `~/.local/share/opencode/opencode.db` | opencode database |
| `CURSOR_PROJECTS` | `~/.cursor/projects` | Cursor transcripts root |

The server binds to localhost by default. It uses SQLite WAL mode and short transactions, so it can run while opencode is open.

## License

MIT. See [LICENSE](LICENSE).

---

<details>
<summary>Keywords</summary>

opencode, Cursor, AI agent, chat history, transcript, viewer, editor, move conversations, migrate chats, local dashboard, SQLite, .jsonl, no dependencies, Python 3, LLM, LLM chat manager, agent transcripts, opencode to Cursor, Cursor to opencode
</details>
