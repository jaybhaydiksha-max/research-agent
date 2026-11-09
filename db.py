"""SQLite memory: stores every research run, its notes, its tool-call trace and its final report."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
 
DB_PATH = Path(__file__).with_name("research.db")
 
_SECONDS = "(julianday(finished_at) - julianday(created_at)) * 86400.0 AS seconds"
 
 
@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
 
 
def init_db():
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                depth TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                report TEXT,
                steps INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES runs(id),
                sub_question TEXT,
                finding TEXT,
                source TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES runs(id),
                step INTEGER,
                tool TEXT,
                args TEXT,
                result TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        # Migration for databases created before finished_at existed.
        cols = [r["name"] for r in c.execute("PRAGMA table_info(runs)")]
        if "finished_at" not in cols:
            c.execute("ALTER TABLE runs ADD COLUMN finished_at TEXT")
 
 
def create_run(topic: str, depth: str) -> int:
    with _conn() as c:
        cur = c.execute("INSERT INTO runs (topic, depth) VALUES (?, ?)", (topic, depth))
        return cur.lastrowid
 
 
def finish_run(run_id: int, report: str, status: str, steps: int):
    with _conn() as c:
        c.execute(
            "UPDATE runs SET report = ?, status = ?, steps = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ?",
            (report, status, steps, run_id),
        )
 
 
def add_note(run_id: int, sub_question: str, finding: str, source: str) -> int:
    """Insert a note and return the total number of notes for this run."""
    with _conn() as c:
        c.execute(
            "INSERT INTO notes (run_id, sub_question, finding, source) VALUES (?, ?, ?, ?)",
            (run_id, sub_question, finding, source),
        )
        row = c.execute("SELECT COUNT(*) AS n FROM notes WHERE run_id = ?", (run_id,)).fetchone()
        return row["n"]
 
 
def get_notes(run_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT sub_question, finding, source FROM notes WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
 
 
def add_event(run_id: int, step: int, tool: str, args: str, result: str):
    """Log one tool call (the agent's trace)."""
    with _conn() as c:
        c.execute(
            "INSERT INTO events (run_id, step, tool, args, result) VALUES (?, ?, ?, ?, ?)",
            (run_id, step, tool, args, result),
        )
 
 
def get_events(run_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT step, tool, args, result FROM events WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
 
 
def list_runs(limit: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            f"SELECT id, topic, depth, status, steps, created_at, {_SECONDS} "
            "FROM runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
 
 
def get_run(run_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(
            f"SELECT *, {_SECONDS} FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None
 
 
def delete_run(run_id: int):
    with _conn() as c:
        c.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
        c.execute("DELETE FROM notes WHERE run_id = ?", (run_id,))
        c.execute("DELETE FROM runs WHERE id = ?", (run_id,))
 