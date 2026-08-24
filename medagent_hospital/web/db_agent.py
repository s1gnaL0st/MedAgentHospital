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
from medagent_hospital.memory.case_base import MedicalCase, MedicalCaseBase
from medagent_hospital.memory.experience_base import ExperienceBase, ExperienceRule
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

    def register_agent(
        self, agent_id: str, role: str, name: str, department: str = ""
    ) -> None:
        """Register a scoped Agent, such as one doctor per department."""
        self.store.upsert_agent(agent_id, role, name, department)

    def ensure_session(self, session_id: str, patient: dict | None = None) -> None:
        """Create a session shell for training memories when needed."""
        if self.store.get_session(session_id) is None:
            self.store.create_session(
                session_id,
                patient or {"type": "training", "session_id": session_id},
            )

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

        existing = self._find_existing_memory(
            agent_id, session_id, memory_type, content
        )
        if existing is not None:
            audit_id = self.store.add_audit(
                session_id, agent_id, existing["memory_id"], "update", "approved", []
            )
            self.store.update_memory(existing["memory_id"], content, float(importance))
            return {
                "verdict": "approved",
                "memory_id": existing["memory_id"],
                "audit_id": audit_id,
                "agent_id": agent_id,
                "updated": True,
            }

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

    def _find_existing_memory(
        self,
        agent_id: str,
        session_id: str,
        memory_type: str,
        content: dict,
    ) -> dict | None:
        for row in self.store.list_memories(agent_id):
            if row["session_id"] != session_id or row["memory_type"] != memory_type:
                continue
            stored = json.loads(row["content"])
            if memory_type == "rule" and content.get("rule_id"):
                if stored.get("rule_id") == content["rule_id"]:
                    return row
            elif stored == content:
                return row
        return None

    def save_case(
        self,
        agent_id: str,
        session_id: str,
        case: MedicalCase,
        *,
        department: str = "",
        source_event_id: int | None = None,
    ) -> dict:
        """Persist a successful case through the audited memory boundary."""
        return self.save_memory(
            agent_id,
            session_id,
            "case",
            {
                "patient": case.patient,
                "diagnosis": case.diagnosis,
                "diagnosis_id": case.diagnosis_id,
                "treatment": case.treatment,
                "outcome": case.outcome,
                "department": department,
            },
            source_event_id=source_event_id,
            importance=case.importance,
        )

    def save_rule(
        self,
        agent_id: str,
        session_id: str,
        rule: ExperienceRule,
        *,
        department: str = "",
        source_event_id: int | None = None,
    ) -> dict:
        """Persist a validated reflection rule through the audited boundary."""
        return self.save_memory(
            agent_id,
            session_id,
            "rule",
            {
                "rule_id": rule.rule_id,
                "trigger": list(rule.trigger),
                "rule": rule.rule,
                "favor": rule.favor,
                "against": rule.against,
                "strength": rule.strength,
                "validations": rule.validations,
                "successes": rule.successes,
                "source": rule.source,
                "department": department,
            },
            source_event_id=source_event_id,
            importance=max(1.0, rule.strength),
        )

    def load_case_base(
        self,
        agent_id: str,
        *,
        department: str = "",
        dedup_threshold: float = 0.0,
    ) -> MedicalCaseBase:
        """Rehydrate one Agent's successful cases from SQLite."""
        base = MedicalCaseBase(dedup_threshold=dedup_threshold)
        for row in self.store.list_memories(agent_id):
            if row["memory_type"] != "case":
                continue
            content = json.loads(row["content"])
            stored_department = content.get("department", "")
            diagnosis = self.kb.get(str(content.get("diagnosis_id", "")))
            if department and stored_department and stored_department != department:
                continue
            if department and not stored_department and diagnosis and diagnosis.department != department:
                continue
            case = MedicalCase(
                patient=content.get("patient") or {
                    "symptoms": content.get("symptoms", []),
                    "exam_names": content.get("exam_names", []),
                },
                diagnosis=str(content.get("diagnosis", content.get("diagnosis_name", ""))),
                diagnosis_id=str(content.get("diagnosis_id", "")),
                treatment=str(content.get("treatment", "")),
                outcome=str(content.get("outcome", "recovered")),
                created_at=float(row["created_at"]),
                last_accessed_at=float(row["last_accessed_at"]),
                importance=float(row["importance"]),
                retrieval_count=int(row["retrieval_count"]),
            )
            base.add(case)
        return base

    def load_experience_base(
        self,
        agent_id: str,
        *,
        department: str = "",
    ) -> ExperienceBase:
        """Rehydrate one Agent's validated reflection rules from SQLite."""
        base = ExperienceBase()
        for row in self.store.list_memories(agent_id):
            if row["memory_type"] != "rule":
                continue
            content = json.loads(row["content"])
            if department and content.get("department", "") not in {"", department}:
                continue
            favor = str(content.get("favor", ""))
            against = str(content.get("against", ""))
            if favor and self.kb.get(favor) is None:
                continue
            if against and self.kb.get(against) is None:
                continue
            rule = ExperienceRule(
                trigger=tuple(str(item) for item in content.get("trigger", [])),
                rule=str(content.get("rule", "")),
                favor=favor,
                against=against,
                strength=float(content.get("strength", 0.6)),
                validations=int(content.get("validations", 0)),
                successes=int(content.get("successes", 0)),
                source=str(content.get("source", "reflection")),
                rule_id=str(content.get("rule_id", "")),
            )
            if not rule.trigger or not rule.rule:
                continue
            base.add(rule)
        return base

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
