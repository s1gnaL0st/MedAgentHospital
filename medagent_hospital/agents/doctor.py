"""Doctor agent: examination selection, diagnosis and treatment.

``reasoner="rule"`` uses the knowledge-base scorer; ``reasoner="llm"`` asks the
configured LLM (DeepSeek / HuatuoGPT / OpenAI-compatible) with RAG memory
injected into the prompt, and falls back to the rule scorer on failure.
"""

from __future__ import annotations

import json

from medagent_hospital.agents.base import Agent
from medagent_hospital.knowledge import Disease, KnowledgeBase, load_knowledge_base
from medagent_hospital.llm.base import LLMBackend, RuleBackend, build_llm_backend
from medagent_hospital.memory.case_base import MedicalCaseBase
from medagent_hospital.memory.experience_base import ExperienceBase
from medagent_hospital.simulacrum.models import Action, ConsultationContext, HospitalState, PatientRecord

FOCUS_DESCRIPTIONS = {
    "balanced": "综合判断",
    "exam": "重点依据检查结果与影像学证据",
    "history": "重点依据病史、危险因素与流行病学线索",
}


class DoctorAgent(Agent):
    role = "doctor"

    def __init__(
        self,
        name: str = "主治医生",
        llm: LLMBackend | None = None,
        kb: KnowledgeBase | None = None,
        reasoner: str = "rule",
        max_exams: int = 3,
        case_base: MedicalCaseBase | None = None,
        experience_base: ExperienceBase | None = None,
        top_k_cases: int = 3,
        top_k_rules: int = 4,
        case_weight: float = 1.0,
        focus: str = "balanced",
        deliberation_weight: float = 0.15,
        symptom_weight: float = 1.0,
        exam_weight: float = 1.0,
        history_weight: float = 1.0,
    ) -> None:
        if llm is None and reasoner == "llm":
            llm = build_llm_backend()
        super().__init__(name, llm or RuleBackend())
        self.kb = kb or load_knowledge_base()
        self.reasoner = reasoner
        self.max_exams = max_exams
        self.case_base = case_base
        self.experience_base = experience_base
        self.top_k_cases = top_k_cases
        self.top_k_rules = top_k_rules
        self.case_weight = case_weight
        self.focus = focus
        self.deliberation_weight = deliberation_weight
        self.symptom_weight = symptom_weight
        self.exam_weight = exam_weight
        self.history_weight = history_weight

    def run(self, context: ConsultationContext) -> Action:
        if context.current_state == HospitalState.SYMPTOM_QUESTION:
            return self._ask_symptom(context)
        if context.current_state == HospitalState.CONSULTATION:
            return self._select_exams(context)
        if context.current_state == HospitalState.DIAGNOSIS:
            return self._diagnose(context)
        if context.current_state == HospitalState.CONSULTATION_ROUND:
            return self._consult_opinion(context)
        if context.current_state == HospitalState.CONSULTATION_SUMMARY:
            return self._arbitrate(context)
        if context.current_state == HospitalState.TREATMENT:
            return self._prescribe(context)
        return Action("idle", {})

    def _ask_symptom(self, context: ConsultationContext) -> Action:
        department = context.department
        diseases = (
            self.kb.by_department(department)
            if department
            else self.kb.diseases
        )
        observed = set(context.patient.symptoms)
        asked = set(context.asked_symptoms)
        candidates: list[tuple[float, str]] = []
        for disease in diseases:
            if not disease.patient_profile:
                continue
            for symptom, weight in disease.patient_profile.symptom_weights.items():
                if symptom not in observed and symptom not in asked:
                    candidates.append((weight, symptom))
        if not candidates:
            return Action("no_more_questions", {})
        candidates.sort(key=lambda item: item[0], reverse=True)
        symptom = candidates[0][1]
        return Action(
            "ask_symptom",
            {"symptom": symptom, "question": f"请问您是否有{symptom}？"},
        )

    def _consult_opinion(self, context: ConsultationContext) -> Action:
        diagnosis = (
            self._diagnose(context)
            if self.reasoner == "llm"
            else self._diagnose_with_deliberation(context)
        )
        payload = diagnosis.payload
        scores = payload.get("scores") or {}
        weight = max(float(value) for value in scores.values()) if scores else 1.0
        agrees_with = [
            item.get("doctor", "")
            for item in context.opinions
            if item.get("disease_id") == payload.get("disease_id")
        ]
        return Action(
            "opinion",
            {
                "disease_id": payload.get("disease_id", ""),
                "disease_name": payload.get("disease_name", ""),
                "reasoning": payload.get("reasoning", ""),
                "weight": weight,
                "considers": len(context.opinions),
                "agrees_with": agrees_with,
            },
        )

    def _arbitrate(self, context: ConsultationContext) -> Action:
        if self.reasoner == "llm":
            action = self._llm_arbitrate(context)
            if action is not None:
                return action
        return self._weighted_arbitrate(context)

    def _llm_arbitrate(self, context: ConsultationContext) -> Action | None:
        opinion_lines = "；".join(
            f"{item.get('doctor', '')}: {item.get('disease_name', '')}（权重{item.get('weight', 1.0)}）"
            for item in context.opinions
        )
        messages = [
            {
                "role": "system",
                "content": "你是一名主任医生，负责主持会诊并做最终裁定。综合各方意见给出最终诊断，只输出 JSON：{\"disease_id\": \"...\", \"disease_name\": \"...\", \"reasoning\": \"...\"}。",
            },
            {
                "role": "user",
                "content": f"病人：{'男' if context.patient.gender == 'male' else '女'}，{context.patient.age}岁\n症状：{'、'.join(context.patient.symptoms)}\n会诊意见：{opinion_lines}",
            },
        ]
        try:
            text = self.llm.chat(messages, temperature=0.1, max_tokens=400)
        except Exception:
            return None
        parsed = self._parse_json(text)
        disease = None
        if parsed:
            disease = self.kb.get(str(parsed.get("disease_id", "")).strip())
            if disease is None:
                disease = self.kb.by_name(str(parsed.get("disease_name", "")).strip())
        if disease is None:
            return None
        return Action(
            "final_diagnosis",
            {
                "disease_id": disease.id,
                "disease_name": disease.name,
                "reasoning": f"主任仲裁：{str(parsed.get('reasoning') or text.strip())[:500]}",
                "scores": {},
            },
        )

    def _weighted_arbitrate(self, context: ConsultationContext) -> Action:
        totals: dict[str, float] = {}
        names: dict[str, str] = {}
        for opinion in context.opinions:
            disease_id = opinion.get("disease_id", "")
            if not disease_id:
                continue
            totals[disease_id] = totals.get(disease_id, 0.0) + float(opinion.get("weight", 1.0))
            names.setdefault(disease_id, opinion.get("disease_name", ""))
        if not totals:
            disease_id = context.lead_diagnosis_id
            disease_name = context.lead_diagnosis_name
        else:
            disease_id = max(
                totals,
                key=lambda key: (totals[key], key == context.lead_diagnosis_id),
            )
            disease_name = names.get(disease_id, context.lead_diagnosis_name)
        reasoning = (
            "主任仲裁（加权）："
            + "；".join(
                f"{item.get('disease_name', '')}({item.get('weight', 1.0):.1f})"
                for item in context.opinions
            )
        )
        return Action(
            "final_diagnosis",
            {
                "disease_id": disease_id,
                "disease_name": disease_name,
                "reasoning": reasoning,
                "scores": {key: round(value, 3) for key, value in totals.items()},
            },
        )

    def _select_exams(self, context: ConsultationContext) -> Action:
        candidates = self._candidate_pool(context)
        scored = self._score_candidates(context.patient, candidates, exam_results=None)
        top_diseases = [disease for _, disease in scored[:2]]
        exams: list[str] = []
        for disease in top_diseases:
            for exam in disease.examinations:
                if exam.name not in exams:
                    exams.append(exam.name)
            if len(exams) >= self.max_exams:
                break
        return Action(
            "order_exams",
            {
                "exams": exams[: self.max_exams],
                "candidates": [disease.id for _, disease in scored[:3]],
            },
        )

    def _diagnose(self, context: ConsultationContext) -> Action:
        if self.reasoner == "llm":
            return self._llm_diagnose(context)
        return self._diagnose_rule(context)

    def _diagnose_rule(self, context: ConsultationContext) -> Action:
        scored = self._rank_candidates(context)
        if not scored:
            return Action(
                "diagnose",
                {"disease_id": "", "disease_name": "未知", "reasoning": "无法识别", "scores": {}},
            )
        _, best = scored[0]
        return Action(
            "diagnose",
            {
                "disease_id": best.id,
                "disease_name": best.name,
                "reasoning": self._build_reasoning(context, scored),
                "scores": {disease.id: round(score, 3) for score, disease in scored[:5]},
            },
        )

    def _rank_candidates(
        self, context: ConsultationContext,
    ) -> list[tuple[float, Disease]]:
        candidates = self._candidate_pool(context)
        scored = self._score_candidates(
            context.patient, candidates, exam_results=context.exam_results
        )
        return self._apply_memory(context, scored)

    def _diagnose_with_deliberation(
        self, context: ConsultationContext,
    ) -> Action:
        scored = self._rank_candidates(context)
        for item in context.opinions:
            disease_id = item.get("disease_id", "")
            prior_weight = float(item.get("weight", 1.0))
            for index, (score, disease) in enumerate(scored):
                if disease.id == disease_id:
                    scored[index] = (
                        score + self.deliberation_weight * prior_weight,
                        disease,
                    )
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            return Action(
                "diagnose",
                {"disease_id": "", "disease_name": "未知", "reasoning": "无法识别", "scores": {}},
            )
        _, best = scored[0]
        reasoning = self._build_reasoning(context, scored)
        if context.opinions:
            reasoning += f"；参考已有会诊意见 {len(context.opinions)} 条"
        return Action(
            "diagnose",
            {
                "disease_id": best.id,
                "disease_name": best.name,
                "reasoning": reasoning,
                "scores": {disease.id: round(score, 3) for score, disease in scored[:5]},
            },
        )

    def _llm_diagnose(self, context: ConsultationContext) -> Action:
        self._retrieve_memory(context)
        candidates = self._candidate_pool(context)
        messages = [
            {"role": "system", "content": f"你是一名资深主治医生（{self.name}，{FOCUS_DESCRIPTIONS.get(self.focus, '综合判断')}）。请依据病人信息、检查结果和检索到的相似案例、经验规则，从候选疾病中选择最可能的诊断。只输出 JSON：{{\"disease_id\": \"...\", \"disease_name\": \"...\", \"reasoning\": \"...\"}}。"},
            {"role": "user", "content": self._build_llm_prompt(context, candidates)},
        ]
        try:
            text = self.llm.chat(messages, temperature=0.1, max_tokens=400)
        except Exception:
            return self._diagnose_rule(context)

        parsed = self._parse_json(text)
        disease = None
        if parsed:
            disease = self.kb.get(str(parsed.get("disease_id", "")).strip())
            if disease is None:
                disease = self.kb.by_name(str(parsed.get("disease_name", "")).strip())
        if disease is None:
            return self._diagnose_rule(context)

        reasoning = str(parsed.get("reasoning") or text.strip())
        return Action(
            "diagnose",
            {
                "disease_id": disease.id,
                "disease_name": disease.name,
                "reasoning": reasoning[:500],
                "scores": {},
            },
        )

    def _prescribe(self, context: ConsultationContext) -> Action:
        disease = self.kb.get(context.diagnosis_id)
        return Action(
            "prescribe",
            {
                "treatment": list(disease.treatments) if disease else [],
                "disease_id": disease.id if disease else "",
                "disease_name": disease.name if disease else "",
            },
        )

    def _retrieve_memory(
        self,
        context: ConsultationContext,
    ) -> tuple[list[dict], list[dict]]:
        cases: list[dict] = []
        if self.case_base is not None:
            query = {
                "symptoms": context.patient.symptoms,
                "exam_names": [exam.name for exam in context.exam_results if exam.is_abnormal()],
            }
            for hit in self.case_base.retrieve(query, top_k=self.top_k_cases):
                cases.append(
                    {
                        "diagnosis": hit.case.diagnosis,
                        "diagnosis_id": hit.case.diagnosis_id,
                        "score": round(hit.score, 3),
                    }
                )

        rules: list[dict] = []
        if self.experience_base is not None:
            query = {
                "symptoms": context.patient.symptoms,
                "medical_history": context.patient.medical_history,
                "exam_names": [exam.name for exam in context.exam_results if exam.is_abnormal()],
            }
            for hit in self.experience_base.retrieve(query, top_k=self.top_k_rules):
                rule = hit.rule
                rules.append(
                    {
                        "rule": rule.rule,
                        "favor": rule.favor,
                        "against": rule.against,
                        "strength": rule.strength,
                        "score": round(hit.score, 3),
                        "rule_id": rule.rule_id,
                    }
                )

        context.retrieved_cases = cases
        context.retrieved_rules = rules
        context.memory_events.append(
            {
                "agent": self.name,
                "case_hits": len(cases),
                "rule_hits": len(rules),
            }
        )
        return cases, rules

    def _apply_memory(
        self,
        context: ConsultationContext,
        scored: list[tuple[float, Disease]],
    ) -> list[tuple[float, Disease]]:
        """Inject retrieved cases and experience rules into candidate scores."""
        case_hits, rule_hits = self._retrieve_memory(context)
        case_bonus: dict[str, float] = {}
        for hit in case_hits:
            target = self.kb.get(hit["diagnosis_id"]) or self.kb.by_name(hit["diagnosis"])
            if target:
                case_bonus[target.id] = case_bonus.get(target.id, 0.0) + hit["score"] * self.case_weight
        scored = [
            (score + case_bonus.get(disease.id, 0.0), disease)
            for score, disease in scored
        ]

        for hit in rule_hits:
            # A reflection rule is a conjunction of evidence, not a keyword
            # vote. Partial matches are too ambiguous and caused negative
            # transfer in the 1k mechanism audit.
            if hit["score"] < 1.0:
                continue
            delta = hit["strength"] * hit["score"]
            for index, (score, disease) in enumerate(scored):
                if disease.id == hit["favor"]:
                    scored[index] = (score + delta, disease)
                if disease.id == hit["against"]:
                    scored[index] = (score - delta, disease)

        scored.sort(key=lambda item: item[0], reverse=True)
        return scored

    def _build_llm_prompt(
        self,
        context: ConsultationContext,
        candidates: list[Disease],
    ) -> str:
        patient = context.patient
        lines = [
            f"病人：{'男' if patient.gender == 'male' else '女'}，{patient.age}岁",
            f"症状：{'、'.join(patient.symptoms)}",
        ]
        if patient.medical_history:
            lines.append(f"既往史：{'、'.join(patient.medical_history)}")
        if patient.risk_factors:
            lines.append(f"危险因素：{'、'.join(patient.risk_factors)}")
        if context.exam_results:
            exam_text = "；".join(
                f"{exam.name}: {exam.findings}" for exam in context.exam_results
            )
            lines.append(f"检查结果：{exam_text}")

        candidate_text = "；".join(
            f"{disease.id} {disease.name}" for disease in candidates
        )
        lines.append(f"候选疾病：{candidate_text}")

        if context.retrieved_cases:
            case_text = "；".join(
                f"{hit['diagnosis']}(相似度{hit['score']})" for hit in context.retrieved_cases
            )
            lines.append(f"相似案例：{case_text}")
        if context.retrieved_rules:
            rule_text = "；".join(hit["rule"] for hit in context.retrieved_rules)
            lines.append(f"经验规则：{rule_text}")
        if context.opinions:
            opinion_text = "；".join(
                f"{item.get('doctor', '医生')}认为{item.get('disease_name', '')}"
                f"（权重{item.get('weight', 1.0)}）"
                for item in context.opinions
            )
            lines.append(f"已有会诊意见：{opinion_text}")
            lines.append("你可以同意或提出不同意见，但需说明理由。")
        return "\n".join(lines)

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _candidate_pool(self, context: ConsultationContext) -> list[Disease]:
        if context.department:
            pool = self.kb.by_department(context.department)
            patient_symptoms = set(context.patient.symptoms)
            if pool and any(set(disease.symptoms) & patient_symptoms for disease in pool):
                return pool
        return self.kb.diseases

    def _score_candidates(
        self,
        patient: PatientRecord,
        candidates: list[Disease],
        exam_results: list | None,
    ) -> list[tuple[float, Disease]]:
        scored: list[tuple[float, Disease]] = []
        abnormal_names = {
            exam.name for exam in (exam_results or []) if exam.is_abnormal()
        }
        matched_risks = set(patient.medical_history) | set(patient.risk_factors)

        for disease in candidates:
            score = 0.0
            profile = disease.patient_profile
            weights = profile.symptom_weights if profile else {}
            symptom_set = set(disease.symptoms)
            for symptom in patient.symptoms:
                if symptom in symptom_set:
                    score += weights.get(symptom, 0.6) * self.symptom_weight
                else:
                    score -= 0.1 * self.symptom_weight

            exam_names = {exam.name for exam in disease.examinations}
            for name in abnormal_names:
                score += (1.5 if name in exam_names else -0.3) * self.exam_weight

            for factor in disease.risk_factors:
                if factor in matched_risks:
                    score += 0.4 * self.history_weight

            if profile:
                low, high = profile.age_range
                if low <= patient.age <= high:
                    score += 0.3
                if profile.gender_bias != "any" and patient.gender == profile.gender_bias:
                    score += 0.3
            scored.append((score, disease))

        scored.sort(key=lambda item: item[0], reverse=True)
        return scored

    def _build_reasoning(self, context: ConsultationContext, scored: list[tuple[float, Disease]]) -> str:
        parts = [
            "候选诊断: "
            + ", ".join(f"{disease.name}({score:.2f})" for score, disease in scored[:3])
        ]
        abnormal = [exam for exam in context.exam_results if exam.is_abnormal()]
        if abnormal:
            parts.append(
                "异常检查: "
                + ", ".join(f"{exam.name}: {exam.findings}" for exam in abnormal[:3])
            )
        return "；".join(parts)
