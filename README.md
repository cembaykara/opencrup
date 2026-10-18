[![Python](https://img.shields.io/badge/python-3.x-478859?labelColor=black)]()
[![Dependencies](https://img.shields.io/badge/deps-none-0097a7?labelColor=black)]()
[![Platform](https://img.shields.io/badge/platform-macOS%20·%20Windows%20·%20Linux-2f74d0?labelColor=black)]()
[![License](https://img.shields.io/badge/license-MIT-d43b4b?labelColor=black)]()

# 📦 OpenCrup

A local dashboard for your **opencode**, **Cursor**, and **Claude Code** agent conversations. Browse and search chat history by project, read and edit messages, and move a conversation between any of the three. It lands in the real app with the full history.

Python 3 stdlib only. No install, no build step.

<p align="center">
  <img src="docs/home.png" alt="OpenCrup home: pick a source" width="45%" style="border-radius:12px;"/>
  <img src="docs/opencode_view.png" alt="OpenCrup opencode view: read, edit, move" width="45%" style="border-radius:12px;"/>
</p>

<p align="center">
  <img src="docs/conversation_view.png" alt="OpenCrup conversation view: thinking, tool calls, and code" width="85%" style="border-radius:12px;"/>
</p>

---

## 🚚 Moving conversations

The main reason to use this. Take a conversation from one app and drop it into another: opencode, Cursor, or Claude Code, in any direction. OpenCrup writes it into the target app's own stores, so it appears in the real sidebar and loads with every reply and tool call.

- **→ Cursor**: writes the transcript, composer record, message bubbles, sidebar entry, and search index.
- **→ opencode**: imports it into opencode's SQLite store.
- **→ Claude Code**: writes the `.jsonl` transcript and marks the project trusted in `~/.claude.json`.
- **Delete**: purges it from every store so it's gone from the real app too.

The destination is a dropdown of the target's existing projects, defaulting to the conversation's own path.

---

## ✨ Everything else

Search and group conversations by project. Read markdown, thinking blocks, and tool calls (input + output). Edit or delete individual messages, or select a range and delete/archive in bulk. Export a session as JSON.

Every view is a shareable deep link: `?source=opencode&session=<id>` opens straight to a conversation, so you can point a teammate (or a screenshot) right at it.

---

## 🔧 Run

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
| `CLAUDE_CONFIG_DIR` | `~/.claude` | Claude Code config root (transcripts in `projects/`) |

Binds to localhost by default. Runs in SQLite WAL mode, so it can run while opencode is open.

---

## 💻 Local by design

OpenCrup runs on your machine and works with the same local files each app already uses to store conversations. It doesn't call their servers or decompile them, so your data stays on your disk.

Quit the target app before a move, and keep a backup before bulk deletes. This is an independent project.

---

## 🤝 Sponsor

<a href='https://ko-fi.com/F1F719XC8H' target='_blank'><img height='36' style='border:0px;height:36px;' src='https://storage.ko-fi.com/cdn/kofi6.png?v=6' border='0' alt='Buy Me a Coffee at ko-fi.com' /></a>

---

## ⚖️ License

MIT.
