"""LLM proposal layer for Skill evolution.

The distiller proposes a candidate only. It never writes to a skill base and
never certifies its own proposal; admission remains the experiment verifier's
responsibility.
"""

from __future__ import annotations

import json
from typing import Any

from medagent_hospital.knowledge import KnowledgeBase
from medagent_hospital.llm.base import LLMBackend
from medagent_hospital.memory.skill_base import DiagnosticSkill
from medagent_hospital.simulacrum.models import ConsultationContext, PatientRecord


class SkillDistiller:
    """Constrained LLM skill proposer with strict local validation."""

    ALLOWED_ACTIONS = {"rerank", "add_exam"}

    def __init__(self, llm: LLMBackend, kb: KnowledgeBase) -> None:
        self.llm = llm
        self.kb = kb

    def distill(
        self,
        patient: PatientRecord,
        context: ConsultationContext,
        *,
        skill_id: str,
    ) -> DiagnosticSkill | None:
        observed = set(patient.symptoms) | set(patient.medical_history)
        observed |= {
            exam.name for exam in context.exam_results if exam.is_abnormal()
        }
        candidates = self.kb.by_department(context.department or "")
        prompt = {
            "symptoms": patient.symptoms,
            "medical_history": patient.medical_history,
            "exams": [
                {"name": exam.name, "findings": exam.findings}
                for exam in context.exam_results
            ],
            "wrong_diagnosis_id": context.diagnosis_id,
            "candidate_diseases": [{"id": d.id, "name": d.name} for d in candidates],
            "allowed_observed_evidence": sorted(observed),
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "你是医学Agent技能提炼器。只输出JSON，不要输出解释。"
                    "从失败轨迹提炼一个可验证的诊断策略。trigger只能使用已观察证据；"
                    "action只能是rerank或add_exam。字段为："
                    "skill_name, trigger, action, target_exam, favor, against。"
                    "不要输出真实标签之外的疾病或检查。"
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        try:
            raw = self.llm.chat(messages, temperature=0.0, max_tokens=350)
        except Exception:
            return None
        data = self._parse_json(raw)
        if data is None:
            return None
        return self._validate(data, patient, context, observed, skill_id)

    def _validate(
        self,
        data: dict[str, Any],
        patient: PatientRecord,
        context: ConsultationContext,
        observed: set[str],
        skill_id: str,
    ) -> DiagnosticSkill | None:
        action = str(data.get("action", "")).strip()
        trigger = tuple(dict.fromkeys(str(item).strip() for item in data.get("trigger", [])))
        favor = str(data.get("favor", "")).strip()
        against = str(data.get("against", "")).strip()
        if action not in self.ALLOWED_ACTIONS or not trigger:
            return None
        if any(not item or item not in observed for item in trigger):
            return None
        department = context.department or ""
        allowed = {d.id for d in self.kb.by_department(department)}
        if favor not in allowed or against not in allowed or favor == against:
            return None
        target_exam = str(data.get("target_exam", "")).strip()
        if action == "add_exam":
            exams = {
                exam.name
                for disease in self.kb.by_department(department)
                for exam in disease.examinations
            }
            if target_exam not in exams:
                return None
        else:
            target_exam = ""
        return DiagnosticSkill(
            skill_id=skill_id,
            name=str(data.get("skill_name") or f"鉴别 {favor} 与 {against}"),
            trigger=trigger,
            favor=favor,
            against=against,
            action=action,
            target_exam=target_exam,
            source="llm_distillation",
        )

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any] | None:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:]
        try:
            value = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None
