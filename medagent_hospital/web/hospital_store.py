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
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                name TEXT NOT NULL,
                department TEXT DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                agent_id TEXT NOT NULL,
                role TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                visible_to TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agent_memories (
                memory_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                source_event_id INTEGER,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                importance REAL DEFAULT 1.0,
                created_at REAL NOT NULL,
                last_accessed_at REAL NOT NULL,
                retrieval_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                audit_id INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS audit_logs (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                memory_id TEXT DEFAULT '',
                action TEXT NOT NULL,
                verdict TEXT NOT NULL,
                issues TEXT NOT NULL,
                reviewed_by TEXT DEFAULT 'db-agent',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_orders_session ON orders(session_id);
            CREATE INDEX IF NOT EXISTS idx_reports_session ON reports(session_id);
            CREATE INDEX IF NOT EXISTS idx_events_session ON session_events(session_id, seq);
            CREATE INDEX IF NOT EXISTS idx_memories_agent ON agent_memories(agent_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_logs(agent_id);
            """
        )
        self._conn.commit()
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        if "complete_json" not in columns:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN complete_json TEXT DEFAULT ''"
            )
        if "status" not in columns:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN status TEXT DEFAULT 'open'"
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

    def upsert_agent(
        self,
        agent_id: str,
        role: str,
        name: str,
        department: str = "",
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO agents (agent_id, role, name, department, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                role = excluded.role,
                name = excluded.name,
                department = excluded.department
            """,
            (agent_id, role, name, department, time.time()),
        )
        self._conn.commit()

    def get_agent(self, agent_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return dict(row) if row else None

    def add_session_event(
        self,
        session_id: str,
        seq: int,
        agent_id: str,
        role: str,
        event_type: str,
        payload: dict,
        visible_to: list[str],
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO session_events
                (session_id, seq, agent_id, role, event_type, payload, visible_to, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                seq,
                agent_id,
                role,
                event_type,
                json.dumps(payload, ensure_ascii=False),
                json.dumps(visible_to, ensure_ascii=False),
                time.time(),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_session_event(self, event_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM session_events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["payload"] = json.loads(data["payload"])
        data["visible_to"] = json.loads(data["visible_to"])
        return data

    def set_session_complete(self, session_id: str, complete: dict) -> None:
        self._conn.execute(
            """
            UPDATE sessions
            SET complete_json = ?, status = 'closed', completed_at = ?
            WHERE session_id = ?
            """,
            (json.dumps(complete, ensure_ascii=False), time.time(), session_id),
        )
        self._conn.commit()

    def add_memory(
        self,
        memory_id: str,
        agent_id: str,
        session_id: str,
        source_event_id: int | None,
        memory_type: str,
        content: dict,
        importance: float,
        audit_id: int = 0,
    ) -> None:
        now = time.time()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO agent_memories
                (memory_id, agent_id, session_id, source_event_id, memory_type,
                 content, importance, created_at, last_accessed_at,
                 retrieval_count, status, audit_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'active', ?)
            """,
            (
                memory_id,
                agent_id,
                session_id,
                source_event_id,
                memory_type,
                json.dumps(content, ensure_ascii=False),
                importance,
                now,
                now,
                audit_id,
            ),
        )
        self._conn.commit()

    def update_memory(
        self, memory_id: str, content: dict, importance: float | None = None
    ) -> None:
        if importance is None:
            self._conn.execute(
                "UPDATE agent_memories SET content = ? WHERE memory_id = ?",
                (json.dumps(content, ensure_ascii=False), memory_id),
            )
        else:
            self._conn.execute(
                """
                UPDATE agent_memories
                SET content = ?, importance = ?, status = 'active'
                WHERE memory_id = ?
                """,
                (json.dumps(content, ensure_ascii=False), importance, memory_id),
            )
        self._conn.commit()

    def list_memories(self, agent_id: str) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT memory_id, agent_id, session_id, source_event_id, memory_type,
                   content, importance, created_at, last_accessed_at,
                   retrieval_count, status, audit_id
            FROM agent_memories
            WHERE agent_id = ? AND status = 'active'
            ORDER BY created_at DESC
            """,
            (agent_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def touch_memory(self, memory_id: str, now: float) -> None:
        self._conn.execute(
            """
            UPDATE agent_memories
            SET retrieval_count = retrieval_count + 1, last_accessed_at = ?
            WHERE memory_id = ?
            """,
            (now, memory_id),
        )
        self._conn.commit()

    def add_audit(
        self,
        session_id: str,
        agent_id: str,
        memory_id: str,
        action: str,
        verdict: str,
        issues: list[str],
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO audit_logs
                (session_id, agent_id, memory_id, action, verdict, issues, reviewed_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'db-agent', ?)
            """,
            (
                session_id,
                agent_id,
                memory_id,
                action,
                verdict,
                json.dumps(issues, ensure_ascii=False),
                time.time(),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def list_audit(self, agent_id: str | None = None) -> list[dict]:
        if agent_id:
            rows = self._conn.execute(
                "SELECT * FROM audit_logs WHERE agent_id = ? ORDER BY audit_id DESC",
                (agent_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM audit_logs ORDER BY audit_id DESC"
            ).fetchall()
        return [dict(row) for row in rows]
