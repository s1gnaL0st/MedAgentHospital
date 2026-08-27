"""PostgreSQL-backed implementation of the hospital record store.

The public methods intentionally mirror ``HospitalRecordStore`` so the DB
Agent and web workflows do not depend on a specific database engine.
Requires the optional ``psycopg[binary]`` dependency.
"""

from __future__ import annotations

import time
from typing import Any

from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class PostgresRecordStore:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url 不能为空")
        self.database_url = database_url
        self.db_path = None
        self._conn = connect(database_url, autocommit=True, row_factory=dict_row)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                patient JSONB NOT NULL,
                department TEXT DEFAULT '',
                diagnosis_id TEXT DEFAULT '',
                diagnosis_name TEXT DEFAULT '',
                created_at DOUBLE PRECISION NOT NULL,
                completed_at DOUBLE PRECISION,
                complete_json JSONB DEFAULT '{}'::jsonb,
                status TEXT DEFAULT 'open'
            );
            CREATE TABLE IF NOT EXISTS messages (
                id BIGSERIAL PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(session_id),
                sender TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                audio_path TEXT DEFAULT '',
                created_at DOUBLE PRECISION NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id BIGSERIAL PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(session_id),
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at DOUBLE PRECISION NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reports (
                id BIGSERIAL PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(session_id),
                exam_name TEXT NOT NULL,
                findings TEXT NOT NULL,
                impression TEXT NOT NULL,
                suggestion TEXT NOT NULL,
                created_at DOUBLE PRECISION NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                name TEXT NOT NULL,
                department TEXT DEFAULT '',
                created_at DOUBLE PRECISION NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_events (
                id BIGSERIAL PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(session_id),
                seq INTEGER NOT NULL,
                agent_id TEXT NOT NULL,
                role TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload JSONB NOT NULL,
                visible_to JSONB NOT NULL,
                created_at DOUBLE PRECISION NOT NULL,
                UNIQUE(session_id, seq)
            );
            CREATE TABLE IF NOT EXISTS agent_memories (
                memory_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL REFERENCES agents(agent_id),
                session_id TEXT NOT NULL REFERENCES sessions(session_id),
                source_event_id BIGINT,
                memory_type TEXT NOT NULL,
                content JSONB NOT NULL,
                importance DOUBLE PRECISION DEFAULT 1.0,
                created_at DOUBLE PRECISION NOT NULL,
                last_accessed_at DOUBLE PRECISION NOT NULL,
                retrieval_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                audit_id BIGINT DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS audit_logs (
                audit_id BIGSERIAL PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(session_id),
                agent_id TEXT NOT NULL,
                memory_id TEXT DEFAULT '',
                action TEXT NOT NULL,
                verdict TEXT NOT NULL,
                issues JSONB NOT NULL,
                reviewed_by TEXT DEFAULT 'db-agent',
                created_at DOUBLE PRECISION NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pg_messages_session ON messages(session_id, id);
            CREATE INDEX IF NOT EXISTS idx_pg_orders_session ON orders(session_id, id);
            CREATE INDEX IF NOT EXISTS idx_pg_reports_session ON reports(session_id, id);
            CREATE INDEX IF NOT EXISTS idx_pg_events_session ON session_events(session_id, seq);
            CREATE INDEX IF NOT EXISTS idx_pg_memories_agent ON agent_memories(agent_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_pg_audit_agent ON audit_logs(agent_id, audit_id DESC);
            """
        )
        self._conn.execute(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS complete_json JSONB DEFAULT '{}'::jsonb"
        )
        self._conn.execute(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'open'"
        )

    def close(self) -> None:
        self._conn.close()

    def create_session(self, session_id: str, patient: dict) -> None:
        self._conn.execute(
            "INSERT INTO sessions (session_id, patient, created_at) VALUES (%s, %s, %s)",
            (session_id, Jsonb(patient), time.time()),
        )

    def update_session(self, session_id: str, *, department: str = "", diagnosis_id: str = "", diagnosis_name: str = "", completed: bool = False) -> None:
        self._conn.execute(
            """
            UPDATE sessions SET department = %s, diagnosis_id = %s,
                diagnosis_name = %s, completed_at = %s WHERE session_id = %s
            """,
            (department, diagnosis_id, diagnosis_name, time.time() if completed else None, session_id),
        )

    def add_message(self, session_id: str, sender: str, role: str, content: str, audio_path: str = "") -> None:
        self._conn.execute(
            "INSERT INTO messages (session_id, sender, role, content, audio_path, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (session_id, sender, role, content, audio_path, time.time()),
        )

    def add_order(self, session_id: str, kind: str, name: str) -> None:
        self._conn.execute(
            "INSERT INTO orders (session_id, kind, name, status, created_at) VALUES (%s, %s, %s, 'ordered', %s)",
            (session_id, kind, name, time.time()),
        )

    def add_report(self, session_id: str, exam_name: str, findings: str, impression: str, suggestion: str) -> None:
        self._conn.execute(
            "INSERT INTO reports (session_id, exam_name, findings, impression, suggestion, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (session_id, exam_name, findings, impression, suggestion, time.time()),
        )

    def list_orders(self, session_id: str) -> list[dict]:
        return self._conn.execute(
            "SELECT kind, name, status FROM orders WHERE session_id = %s ORDER BY id", (session_id,)
        ).fetchall()

    def list_reports(self, session_id: str) -> list[dict]:
        return self._conn.execute(
            "SELECT exam_name, findings, impression, suggestion FROM reports WHERE session_id = %s ORDER BY id", (session_id,)
        ).fetchall()

    def list_messages(self, session_id: str) -> list[dict]:
        return self._conn.execute(
            "SELECT sender, role, content, audio_path FROM messages WHERE session_id = %s ORDER BY id", (session_id,)
        ).fetchall()

    def get_session(self, session_id: str) -> dict | None:
        return self._conn.execute("SELECT * FROM sessions WHERE session_id = %s", (session_id,)).fetchone()

    def upsert_agent(self, agent_id: str, role: str, name: str, department: str = "") -> None:
        self._conn.execute(
            """
            INSERT INTO agents (agent_id, role, name, department, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT(agent_id) DO UPDATE SET role = EXCLUDED.role,
                name = EXCLUDED.name, department = EXCLUDED.department
            """,
            (agent_id, role, name, department, time.time()),
        )

    def get_agent(self, agent_id: str) -> dict | None:
        return self._conn.execute("SELECT * FROM agents WHERE agent_id = %s", (agent_id,)).fetchone()

    def add_session_event(self, session_id: str, seq: int, agent_id: str, role: str, event_type: str, payload: dict, visible_to: list[str]) -> int:
        row = self._conn.execute(
            """
            INSERT INTO session_events (session_id, seq, agent_id, role, event_type, payload, visible_to, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (session_id, seq, agent_id, role, event_type, Jsonb(payload), Jsonb(visible_to), time.time()),
        ).fetchone()
        return int(row["id"])

    def get_session_event(self, event_id: int) -> dict | None:
        return self._conn.execute("SELECT * FROM session_events WHERE id = %s", (event_id,)).fetchone()

    def list_session_events(self, session_id: str) -> list[dict]:
        return self._conn.execute(
            "SELECT * FROM session_events WHERE session_id = %s ORDER BY seq, id",
            (session_id,),
        ).fetchall()

    def set_session_complete(self, session_id: str, complete: dict) -> None:
        self._conn.execute(
            "UPDATE sessions SET complete_json = %s, status = 'closed', completed_at = %s WHERE session_id = %s",
            (Jsonb(complete), time.time(), session_id),
        )

    def add_memory(self, memory_id: str, agent_id: str, session_id: str, source_event_id: int | None, memory_type: str, content: dict, importance: float, audit_id: int = 0) -> None:
        now = time.time()
        self._conn.execute(
            """
            INSERT INTO agent_memories (memory_id, agent_id, session_id, source_event_id,
                memory_type, content, importance, created_at, last_accessed_at,
                retrieval_count, status, audit_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 'active', %s)
            ON CONFLICT(memory_id) DO NOTHING
            """,
            (memory_id, agent_id, session_id, source_event_id, memory_type, Jsonb(content), importance, now, now, audit_id),
        )

    def update_memory(self, memory_id: str, content: dict, importance: float | None = None) -> None:
        if importance is None:
            self._conn.execute("UPDATE agent_memories SET content = %s WHERE memory_id = %s", (Jsonb(content), memory_id))
        else:
            self._conn.execute("UPDATE agent_memories SET content = %s, importance = %s, status = 'active' WHERE memory_id = %s", (Jsonb(content), importance, memory_id))

    def list_memories(self, agent_id: str) -> list[dict]:
        return self._conn.execute(
            """
            SELECT memory_id, agent_id, session_id, source_event_id, memory_type,
                   content, importance, created_at, last_accessed_at,
                   retrieval_count, status, audit_id
            FROM agent_memories WHERE agent_id = %s AND status = 'active'
            ORDER BY created_at DESC
            """, (agent_id,)
        ).fetchall()

    def touch_memory(self, memory_id: str, now: float) -> None:
        self._conn.execute("UPDATE agent_memories SET retrieval_count = retrieval_count + 1, last_accessed_at = %s WHERE memory_id = %s", (now, memory_id))

    def add_audit(self, session_id: str, agent_id: str, memory_id: str, action: str, verdict: str, issues: list[str]) -> int:
        row = self._conn.execute(
            """
            INSERT INTO audit_logs (session_id, agent_id, memory_id, action, verdict, issues, reviewed_by, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'db-agent', %s) RETURNING audit_id
            """, (session_id, agent_id, memory_id, action, verdict, Jsonb(issues), time.time())
        ).fetchone()
        return int(row["audit_id"])

    def list_audit(self, agent_id: str | None = None) -> list[dict]:
        if agent_id:
            return self._conn.execute("SELECT * FROM audit_logs WHERE agent_id = %s ORDER BY audit_id DESC", (agent_id,)).fetchall()
        return self._conn.execute("SELECT * FROM audit_logs ORDER BY audit_id DESC").fetchall()
