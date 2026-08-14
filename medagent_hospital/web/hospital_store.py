"""SQLite-backed hospital record store.

Persists assistant sessions, role chat transcripts, exam orders and
medication orders so the assistant workspace integrates with a hospital
record system instead of living only in process memory.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "generated"
    / "hospital_records.db"
)


class HospitalRecordStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                patient TEXT NOT NULL,
                department TEXT DEFAULT '',
                diagnosis_id TEXT DEFAULT '',
                diagnosis_name TEXT DEFAULT '',
                created_at REAL NOT NULL,
                completed_at REAL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                audio_path TEXT DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                exam_name TEXT NOT NULL,
                findings TEXT NOT NULL,
                impression TEXT NOT NULL,
                suggestion TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_orders_session ON orders(session_id);
            CREATE INDEX IF NOT EXISTS idx_reports_session ON reports(session_id);
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def create_session(self, session_id: str, patient: dict) -> None:
        self._conn.execute(
            "INSERT INTO sessions (session_id, patient, created_at) VALUES (?, ?, ?)",
            (session_id, json.dumps(patient, ensure_ascii=False), time.time()),
        )
        self._conn.commit()

    def update_session(
        self,
        session_id: str,
        *,
        department: str = "",
        diagnosis_id: str = "",
        diagnosis_name: str = "",
        completed: bool = False,
    ) -> None:
        self._conn.execute(
            """
            UPDATE sessions
            SET department = ?, diagnosis_id = ?, diagnosis_name = ?, completed_at = ?
            WHERE session_id = ?
            """,
            (
                department,
                diagnosis_id,
                diagnosis_name,
                time.time() if completed else None,
                session_id,
            ),
        )
        self._conn.commit()

    def add_message(
        self,
        session_id: str,
        sender: str,
        role: str,
        content: str,
        audio_path: str = "",
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO messages (session_id, sender, role, content, audio_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, sender, role, content, audio_path, time.time()),
        )
        self._conn.commit()

    def add_order(self, session_id: str, kind: str, name: str) -> None:
        self._conn.execute(
            """
            INSERT INTO orders (session_id, kind, name, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, kind, name, "ordered", time.time()),
        )
        self._conn.commit()

    def add_report(
        self,
        session_id: str,
        exam_name: str,
        findings: str,
        impression: str,
        suggestion: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO reports (session_id, exam_name, findings, impression, suggestion, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, exam_name, findings, impression, suggestion, time.time()),
        )
        self._conn.commit()

    def list_orders(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT kind, name, status FROM orders WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_reports(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT exam_name, findings, impression, suggestion
            FROM reports WHERE session_id = ? ORDER BY id
            """,
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_messages(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT sender, role, content, audio_path
            FROM messages WHERE session_id = ? ORDER BY id
            """,
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_session(self, session_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None
