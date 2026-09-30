"""SQLite persistence: profile, settings, pipeline, and an HTTP response cache."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("ATTESTA_DB", Path(__file__).resolve().parent.parent / "data" / "attesta.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS pipeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('job', 'research')),
    title TEXT NOT NULL,
    org TEXT DEFAULT '',
    contact TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'researching',
    fit_score INTEGER,
    follow_up TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    link TEXT DEFAULT '',
    created REAL NOT NULL,
    updated REAL NOT NULL
);
"""
STATUSES = ["researching", "applied", "replied", "interview", "closed"]


@contextmanager
def conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


# ----------------------------------------------------------------- key/value
def get(key: str, default=None):
    with conn() as c:
        row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def put(key: str, value) -> None:
    with conn() as c:
        c.execute("INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, json.dumps(value)))


# ----------------------------------------------------------------- cache
def cache_get(key: str, max_age: float):
    with conn() as c:
        row = c.execute("SELECT value, ts FROM cache WHERE key=?", (key,)).fetchone()
    if row and time.time() - row["ts"] < max_age:
        return json.loads(row["value"])
    return None


def cache_put(key: str, value) -> None:
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO cache(key, value, ts) VALUES(?, ?, ?)", (key, json.dumps(value), time.time()))


# ----------------------------------------------------------------- pipeline
FIELDS = ["kind", "title", "org", "contact", "status", "fit_score", "follow_up", "notes", "link"]


def pipeline_list() -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM pipeline ORDER BY updated DESC")]


def pipeline_get(item_id: int) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM pipeline WHERE id=?", (item_id,)).fetchone()
    return dict(r) if r else None


def pipeline_create(data: dict) -> dict:
    now = time.time()
    vals = {k: data.get(k) for k in FIELDS}
    vals["status"] = vals["status"] or "researching"
    with conn() as c:
        cur = c.execute(
            f"INSERT INTO pipeline({', '.join(FIELDS)}, created, updated) VALUES({', '.join('?' * len(FIELDS))}, ?, ?)",
            [vals[k] if vals[k] is not None else ("" if k not in ("fit_score",) else None) for k in FIELDS] + [now, now])
        new_id = cur.lastrowid
    return pipeline_get(new_id)


def pipeline_update(item_id: int, data: dict) -> dict | None:
    sets = {k: v for k, v in data.items() if k in FIELDS and k != "kind"}
    if sets:
        with conn() as c:
            c.execute(f"UPDATE pipeline SET {', '.join(f'{k}=?' for k in sets)}, updated=? WHERE id=?",
                      [*sets.values(), time.time(), item_id])
    return pipeline_get(item_id)


def pipeline_delete(item_id: int) -> bool:
    with conn() as c:
        return c.execute("DELETE FROM pipeline WHERE id=?", (item_id,)).rowcount > 0
