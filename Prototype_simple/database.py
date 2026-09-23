import sqlite3
import json
import uuid
from datetime import datetime
from contextlib import contextmanager  # To close the connection automatically
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    content TEXT NOT NULL,
    source_type TEXT NOT NULL,
    is_query INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS entry_tags (
    entry_id INTEGER REFERENCES entries(id),
    tag_id INTEGER REFERENCES tags(id),
    PRIMARY KEY (entry_id, tag_id)
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL REFERENCES entries(id),
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    processed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS process_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    process_id TEXT NOT NULL,
    entry_id INTEGER REFERENCES entries(id),
    chunk_id INTEGER REFERENCES chunks(id),
    agent_name TEXT NOT NULL,
    step_name TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT,
    created_at TEXT NOT NULL
);
"""

@contextmanager   
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  
    try:
        yield conn    # why not return conn? Because we want to ensure that the connection is properly closed after use, even if an error occurs. Using a context manager with 'yield' allows us to automatically close the connection when we're done with it.
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)

def log_step(process_id, entry_id, chunk_id, agent_name, step_name, status, payload=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO process_log (process_id, entry_id, chunk_id, agent_name, step_name, status, payload, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (process_id, entry_id, chunk_id, agent_name, step_name, status,
             json.dumps(payload, default=str) if payload is not None else None,
             datetime.utcnow().isoformat())
        )

def insert_entry(content, source_type, tags, is_query):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO entries (created_at, content, source_type, is_query) VALUES (?,?,?,?)",
            (datetime.utcnow().isoformat(), content, source_type, int(is_query))
        )
        entry_id = cur.lastrowid
        for tag in tags:
            tag = tag.strip()
            if not tag:
                continue
            conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
            tag_row = conn.execute("SELECT id FROM tags WHERE name = ?", (tag,)).fetchone()
            conn.execute("INSERT OR IGNORE INTO entry_tags (entry_id, tag_id) VALUES (?,?)", (entry_id, tag_row["id"]))
        return entry_id

def insert_chunks(entry_id, chunk_texts):
    ids = []
    with get_conn() as conn:
        for idx, text in enumerate(chunk_texts):
            cur = conn.execute(
                "INSERT INTO chunks (entry_id, chunk_index, chunk_text) VALUES (?,?,?)",
                (entry_id, idx, text)
            )
            ids.append(cur.lastrowid)
    return ids

def mark_chunk_processed(chunk_id):
    with get_conn() as conn:
        conn.execute("UPDATE chunks SET processed = 1 WHERE id = ?", (chunk_id,))

def get_unprocessed_chunks():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM chunks WHERE processed = 0").fetchall()
        return [dict(r) for r in rows]

def get_chunks_by_ids(chunk_ids):
    if not chunk_ids:
        return []
    placeholders = ",".join("?" for _ in chunk_ids)
    with get_conn() as conn:
        rows = conn.execute(f"SELECT * FROM chunks WHERE id IN ({placeholders})", chunk_ids).fetchall()
        return [dict(r) for r in rows]

def get_entry_tags(entry_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT t.name FROM tags t JOIN entry_tags et ON t.id = et.tag_id WHERE et.entry_id = ?",
            (entry_id,)
        ).fetchall()
        return [r["name"] for r in rows]

def get_recent_entries(limit=5):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM entries ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

def get_all_entries():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM entries ORDER BY id DESC").fetchall()
        entries = [dict(r) for r in rows]
    for e in entries:
        e["tags"] = get_entry_tags(e["id"])
    return entries

def reset_db():   
    with get_conn() as conn:
        conn.executescript("""
        DROP TABLE IF EXISTS process_log;
        DROP TABLE IF EXISTS entry_tags;
        DROP TABLE IF EXISTS tags;
        DROP TABLE IF EXISTS chunks;
        DROP TABLE IF EXISTS entries;
        """)
    init_db()

def new_process_id():
    return str(uuid.uuid4())

def get_process_logs():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM process_log ORDER BY id ASC").fetchall() 
        return [dict(r) for r in rows]

def get_chunks():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM chunks ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]

if __name__ == "__main__":
    init_db()
    print(get_chunks())