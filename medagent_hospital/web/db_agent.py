"""Database management agent.

Owns the complete end-to-end session record and audits every agent memory
write: schema, isolation (visible_to), validity and normalization.
"""

from __future__ import annotations

import json
import math
import re
import time
import uuid
from typing import Any

from medagent_hospital.knowledge import KnowledgeBase
from medagent_hospital.web.hospital_store import HospitalRecordStore

MEMORY_TYPES = {"observation", "case", "rule", "reflection", "summary"}

ROLE_AGENT_IDS = {
    "guide": "guide-001",
    "doctor": "doctor-001",
    "chief": "chief-001",
    "imaging": "imaging-001",
    "patient": "patient-001",
    "db_agent": "db-agent",
}

STAFF_VISIBLE = [
    "guide-001",
    "doctor-001",
    "chief-001",
    "imaging-001",
    "db-agent",
]


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)


class DatabaseAgent:
    """Audit and persist the per-agent memory stream."""

    def __init__(
        self,
        store: HospitalRecordStore,
        kb: KnowledgeBase,
        *,
        decay_rate: float = 1e-4,
        reinforcement_factor: float = 0.1,
    ) -> None:
        self.store = store
        self.kb = kb
        self.decay_rate = decay_rate
        self.reinforcement_factor = reinforcement_factor
        self._ensure_agents()

    def _ensure_agents(self) -> None:
        names = {
            "guide": "导医",
            "doctor": "主诊医师",
            "chief": "主任医师",
            "imaging": "影像分析",
            "patient": "患者",
            "db_agent": "数据库管理",
        }
        for role, agent_id in ROLE_AGENT_IDS.items():
            self.store.upsert_agent(agent_id, role, names[role])

    def agent_id_for(self, role: str) -> str:
        return ROLE_AGENT_IDS.get(role, role)

    def record_event(
        self,
        session_id: str,
        seq: int,
        role: str,
        event_type: str,
        payload: dict,
        visible_to: list[str],
    ) -> int:
        agent_id = self.agent_id_for(role)
        return self.store.add_session_event(
            session_id,
            seq,
            agent_id,
            role,
            event_type,
            payload,
            visible_to,
        )

    def _validate_content(self, content: dict) -> list[str]:
        issues: list[str] = []
        disease_id = content.get("disease_id") or content.get("diagnosis_id") or ""
        if disease_id and self.kb.get(str(disease_id)) is None:
            issues.append(f"无效 disease_id: {disease_id}")
        department = content.get("department", "")
        if department and department not in self.kb.departments:
            issues.append(f"无效 department: {department}")
        return issues

    def save_memory(
        self,
        agent_id: str,
        session_id: str,
        memory_type: str,
        content: dict,
        *,
        source_event_id: int | None = None,
        importance: float = 1.0,
        visible_to: list[str] | None = None,
    ) -> dict:
        issues: list[str] = []
        if memory_type not in MEMORY_TYPES:
            issues.append(f"无效 memory_type: {memory_type}")
        if not isinstance(content, dict) or not content:
            issues.append("记忆内容为空")
        visible_to = visible_to or [agent_id]
        if source_event_id is not None:
            event = self.store.get_session_event(source_event_id)
            if event is None:
                issues.append(f"源事件不存在: {source_event_id}")
            elif agent_id not in event["visible_to"]:
                issues.append(f"Agent 不在源事件可见范围: {agent_id}")
        issues.extend(self._validate_content(content))
        if issues:
            audit_id = self.store.add_audit(
                session_id, agent_id, "", "save", "rejected", issues
            )
            return {"verdict": "rejected", "issues": issues, "audit_id": audit_id}

        memory_id = f"MEM-{uuid.uuid4().hex[:10]}"
        audit_id = self.store.add_audit(
            session_id, agent_id, memory_id, "save", "approved", []
        )
        self.store.add_memory(
            memory_id,
            agent_id,
            session_id,
            source_event_id,
            memory_type,
            content,
            float(importance),
            audit_id,
        )
        return {
            "verdict": "approved",
            "memory_id": memory_id,
            "audit_id": audit_id,
            "agent_id": agent_id,
        }

    def retrieve(
        self,
        agent_id: str,
        query: dict[str, Any],
        top_k: int = 3,
        *,
        now: float | None = None,
    ) -> list[dict]:
        now = now if now is not None else time.time()
        query_terms = self._terms(_flatten_text(query))
        scored: list[tuple[float, dict]] = []
        for row in self.store.list_memories(agent_id):
            content = json.loads(row["content"])
            relevance = self._jaccard(query_terms, self._terms(_flatten_text(content)))
            if relevance <= 0:
                continue
            age = max(0.0, now - row["last_accessed_at"])
            recency = math.exp(-self.decay_rate * age)
            reinforcement = 1.0 + self.reinforcement_factor * row["retrieval_count"]
            score = relevance * recency * row["importance"] * reinforcement
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        hits = scored[:top_k]
        for _, row in hits:
            self.store.touch_memory(row["memory_id"], now)
        return [
            {"score": round(score, 4), "memory": row} for score, row in hits
        ]

    def reflect(
        self,
        agent_id: str,
        session_id: str,
        *,
        since: float | None = None,
    ) -> dict:
        memories = [
            row
            for row in self.store.list_memories(agent_id)
            if row["memory_type"] in {"observation", "case", "rule"}
            and (since is None or row["created_at"] >= since)
        ]
        if not memories:
            return {"verdict": "rejected", "issues": ["没有可反思的记忆"]}
        top = sorted(memories, key=lambda row: row["importance"], reverse=True)[:10]
        labels = []
        for row in top:
            content = json.loads(row["content"])
            label = content.get("diagnosis_name") or content.get("diagnosis") or content.get("rule")
            if label:
                labels.append(str(label))
        summary = {
            "insight": (
                f"回顾 {len(memories)} 条近期记忆，最重要的要点包括："
                f"{'、'.join(list(dict.fromkeys(labels))[:5])}"
            ),
            "count": len(memories),
        }
        return self.save_memory(
            agent_id,
            session_id,
            "reflection",
            summary,
            importance=2.0,
            visible_to=[agent_id],
        )

    @staticmethod
    def _terms(text: str) -> set[str]:
        parts = re.split(r"[\s,，、;；:：/\[\]()（）]+", text)
        return {part.strip() for part in parts if part.strip()}

    @staticmethod
    def _jaccard(left: set[str], right: set[str]) -> float:
        union = left | right
        return len(left & right) / len(union) if union else 0.0
