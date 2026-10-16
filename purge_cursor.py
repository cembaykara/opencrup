#!/usr/bin/env python3
"""Purge Cursor conversation(s) from every local store.

Usage:
  python3 purge_cursor.py <uuid-or-prefix> [...] [--dry-run]

Accepts full UUIDs or unique prefixes. Resolves them against the search DB
and the filesystem, then removes each from:

  1. ~/.cursor/projects/*/agent-transcripts/<uuid>/      transcript .jsonl
  2. ~/.cursor/chats/*/<uuid>/                           store.db blob store
  3. ~/Library/.../globalStorage/conversation-search.db  search index (+FTS)
  4. ~/Library/.../AgentStores/cursor_agent_stores/<uuid>/  cloud sync
  5. ~/Library/.../globalStorage/state.vscdb             glass/UI state keys
  6. ~/.cursor/ai-tracking/ai-code-tracking.db           telemetry rows

Note: #4 (cloud sync) only clears the local copy; if the session was synced,
a future sync may re-fetch it from the server.
"""
import os, sys, glob, shutil, sqlite3

HOME = os.path.expanduser("~")
CURSOR = os.path.join(HOME, ".cursor")
APP = os.path.join(HOME, "Library", "Application Support", "Cursor")


def resolve(ids):
    """Resolve full or prefix ids to the full UUIDs found in any store."""
    found = set()
    db = os.path.join(APP, "User", "globalStorage", "conversation-search.db")
    try:
        c = sqlite3.connect(db)
        for p in ids:
            for (i,) in c.execute("select id from conversations where id like ?", (p + "%",)):
                found.add(i)
    except Exception:
        pass
    for p in ids:
        for base in (
            os.path.join(CURSOR, "projects", "*", "agent-transcripts", "*"),
            os.path.join(CURSOR, "chats", "*", "*"),
            os.path.join(APP, "AgentStores", "cursor_agent_stores", "*"),
        ):
            for d in glob.glob(base):
                if os.path.basename(d).startswith(p):
                    found.add(os.path.basename(d))
    return sorted(found)


def purge(uuid, dry):
    removed = []

    def rm(d, label):
        rel = os.path.relpath(d, HOME)
        if dry:
            removed.append(f"  {label}: {rel}")
        else:
            shutil.rmtree(d)
            removed.append(f"  {label}: {rel}")

    # 1. agent-transcripts
    for d in glob.glob(os.path.join(CURSOR, "projects", "*", "agent-transcripts", uuid)):
        rm(d, "agent-transcripts")
    # 2. chats store.db
    for d in glob.glob(os.path.join(CURSOR, "chats", "*", uuid)):
        rm(d, "chats/store.db")
    # 3. conversation-search.db (index + FTS + candidates)
    db = os.path.join(APP, "User", "globalStorage", "conversation-search.db")
    try:
        c = sqlite3.connect(db)
        rows = c.execute("select id, fts_rowid from conversations where id = ?", (uuid,)).fetchall()
        cand = c.execute("delete from conversation_search_candidates where id = ?", (uuid,)).rowcount
        if rows:
            c.executemany("delete from conversations where id = ?", [(i,) for i, _ in rows])
            try:
                c.executemany("delete from conversation_fts where rowid = ?", [(fr,) for _, fr in rows])
            except Exception:
                pass
        c.commit()
        if rows or cand:
            removed.append(f"  conversation-search.db: {len(rows)} conversation(s), {cand} candidate(s)")
    except Exception as e:
        removed.append(f"  conversation-search.db: err {e}")
    # 4. AgentStores
    for d in glob.glob(os.path.join(APP, "AgentStores", "cursor_agent_stores", uuid)):
        rm(d, "AgentStores")
    # 5. state.vscdb
    db = os.path.join(APP, "User", "globalStorage", "state.vscdb")
    try:
        c = sqlite3.connect(db)
        n = c.execute("delete from ItemTable where key like ?", (f"%{uuid}%",)).rowcount
        c.commit()
        if n:
            removed.append(f"  state.vscdb: {n} key(s)")
    except Exception as e:
        removed.append(f"  state.vscdb: err {e}")
    # 6. ai-tracking
    db = os.path.join(CURSOR, "ai-tracking", "ai-code-tracking.db")
    try:
        c = sqlite3.connect(db)
        tables = [r[0] for r in c.execute("select name from sqlite_master where type='table'")]
        tot = 0
        for t in tables:
            for col in [r[1] for r in c.execute(f"pragma table_info('{t}')")]:
                try:
                    tot += c.execute(f"delete from '{t}' where '{col}' like ?", (f"%{uuid}%",)).rowcount
                except Exception:
                    pass
        c.commit()
        if tot:
            removed.append(f"  ai-tracking: {tot} row(s)")
    except Exception as e:
        removed.append(f"  ai-tracking: err {e}")

    return removed


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    ids = [a for a in args if a != "--dry-run"]
    if not ids:
        print(__doc__)
        sys.exit(1)
    uuids = resolve(ids)
    if not uuids:
        print("no matching conversations found")
        return
    print(f"purging {len(uuids)} conversation(s) {'[dry-run] ' if dry else ''}:\n")
    for u in uuids:
        print(f"  {u}")
        for line in purge(u, dry):
            print(line)
        print()


if __name__ == "__main__":
    main()
