# OpenCrup — opencode & Cursor chat manager

A local dashboard for your **opencode** and **Cursor** agent conversations. Browse and search chat history by project, read and edit messages, and move a conversation from one app into the other — it lands in the real sidebar with the full history.

Python 3 stdlib only. No install, no build step.

| | |
|---|---|
| ![Home: pick an opencode or Cursor source](docs/home.png) | ![opencode view: read, edit, move](docs/opencode_view.png) |

## Moving conversations

The main reason to use this. Take a conversation from opencode and drop it into Cursor, or pull one back. OpenCrup writes it into the target app's own stores, so it appears in the real sidebar and loads with every reply and tool call.

- **opencode → Cursor** — writes the transcript, composer record, message bubbles, sidebar entry, and search index.
- **Cursor → opencode** — imports it into opencode's SQLite store.
- **Delete** — purges it from every store so it's gone from the real app too.

The destination is a dropdown of the target's existing projects, defaulting to the conversation's own path.

## Everything else

Search and group conversations by project. Read markdown, thinking blocks, and tool calls (input + output). Edit or delete individual messages, or select a range and delete/archive in bulk. Export a session as JSON.

## Run

```bash
./start.sh            # http://127.0.0.1:4321
./start.sh -p 8080    # custom port
```

Or `python3 server.py`.

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `4321` | HTTP port |
| `HOST` | `127.0.0.1` | Bind address |
| `OPENCODE_DB` | `~/.local/share/opencode/opencode.db` | opencode database |
| `CURSOR_PROJECTS` | `~/.cursor/projects` | Cursor transcripts root |

Binds to localhost by default. Runs in SQLite WAL mode, so it can run while opencode is open.

## License

MIT.
