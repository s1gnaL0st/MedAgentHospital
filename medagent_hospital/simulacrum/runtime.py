"""HospitalRuntime: LangGraph-style state machine for the hospital workflow.

Supports optional multi-agent collaboration:
- nurse follow-up questions (``SYMPTOM_QUESTION`` / ``SYMPTOM_ANSWER``);
- doctor consultation rounds when the lead diagnosis is low-confidence.
"""

from __future__ import annotations

from medagent_hospital.agents.base import Agent
from medagent_hospital.agents.registry import DoctorRegistry
from medagent_hospital.simulacrum.models import (
    Action,
    ConsultationContext,
    ExamResult,
    HospitalState,
    PatientRecord,
)


class HospitalRuntime:
    def __init__(
        self,
        patient_agent: Agent,
        nurse_agent: Agent,
        doctor_agent: Agent | dict[str, Agent] | DoctorRegistry,
        max_steps: int = 20,
        nurse_questions: int = 0,
        consultation: bool = False,
        consultation_threshold: float = 0.35,
        max_consultants: int = 2,
    ) -> None:
        self.patient_agent = patient_agent
        self.nurse_agent = nurse_agent
        self.doctor_agent = doctor_agent
        self.max_steps = max_steps
        self.nurse_questions = nurse_questions
        self.consultation = consultation
        self.consultation_threshold = consultation_threshold
        self.max_consultants = max_consultants

    def run_episode(self, patient: PatientRecord) -> ConsultationContext:
        context = ConsultationContext(patient=patient)
        state = HospitalState.DISEASE_ONSET
        while state != HospitalState.END:
            if context.steps >= self.max_steps:
                context.add_transcript(
                    "runtime", state, "abort", {"reason": "max_steps_exceeded"}
                )
                break
            context.current_state = state
            action = self._dispatch(state, context)
            context.add_transcript(
                self._agent_name(state, context), state, action.type, action.payload
            )
            context.steps += 1
            state = self._apply(state, action, context)
        context.current_state = state
        return context

    def _dispatch(self, state: HospitalState, context: ConsultationContext) -> Action:
        if state in {
            HospitalState.DISEASE_ONSET,
            HospitalState.REGISTRATION,
            HospitalState.SYMPTOM_ANSWER,
            HospitalState.FOLLOW_UP,
        }:
            return self.patient_agent.run(context)
        if state in {
            HospitalState.TRIAGE,
            HospitalState.SYMPTOM_QUESTION,
            HospitalState.EXAMINATION,
        }:
            return self.nurse_agent.run(context)
        if state in {
            HospitalState.CONSULTATION,
            HospitalState.DIAGNOSIS,
            HospitalState.CONSULTATION_ROUND,
            HospitalState.CONSULTATION_SUMMARY,
            HospitalState.TREATMENT,
        }:
            index = context.consultation_round if state == HospitalState.CONSULTATION_ROUND else 0
            return self._doctor_for(context, index).run(context)
        raise ValueError(f"未知状态: {state}")

    def _agent_name(self, state: HospitalState, context: ConsultationContext) -> str:
        if state in {
            HospitalState.DISEASE_ONSET,
            HospitalState.REGISTRATION,
            HospitalState.SYMPTOM_ANSWER,
            HospitalState.FOLLOW_UP,
        }:
            return self.patient_agent.name
        if state in {
            HospitalState.TRIAGE,
            HospitalState.SYMPTOM_QUESTION,
            HospitalState.EXAMINATION,
        }:
            return self.nurse_agent.name
        index = context.consultation_round if state == HospitalState.CONSULTATION_ROUND else 0
        return self._doctor_for(context, index).name

    def _doctor_for(self, context: ConsultationContext, index: int = 0) -> Agent:
        if isinstance(self.doctor_agent, (dict, DoctorRegistry)):
            return self.doctor_agent.get(context.department, index)
        return self.doctor_agent

    def _apply(self, state: HospitalState, action: Action, context: ConsultationContext) -> HospitalState:
        if state == HospitalState.DISEASE_ONSET:
            return HospitalState.TRIAGE
        if state == HospitalState.TRIAGE:
            context.department = action.payload.get("department", "")
            context.triage_reason = action.payload.get("reason", "")
            return HospitalState.REGISTRATION
        if state == HospitalState.REGISTRATION:
            if self.nurse_questions > 0 and context.nurse_questions < self.nurse_questions:
                return HospitalState.SYMPTOM_QUESTION
            return HospitalState.CONSULTATION
        if state == HospitalState.SYMPTOM_QUESTION:
            context.pending_question = action.payload.get("symptom", "")
            if context.pending_question and context.pending_question not in context.asked_symptoms:
                context.asked_symptoms.append(context.pending_question)
            return HospitalState.SYMPTOM_ANSWER
        if state == HospitalState.SYMPTOM_ANSWER:
            symptom = action.payload.get("symptom", "")
            if action.payload.get("present") and symptom and symptom not in context.patient.symptoms:
                context.patient.symptoms.append(symptom)
            context.nurse_questions += 1
            if self.nurse_questions > 0 and context.nurse_questions < self.nurse_questions:
                return HospitalState.SYMPTOM_QUESTION
            return HospitalState.CONSULTATION
        if state == HospitalState.CONSULTATION:
            if action.type == "order_exams":
                context.ordered_exams = list(action.payload.get("exams", []))
                return HospitalState.EXAMINATION
            if action.type == "diagnose":
                self._apply_diagnosis(context, action)
                return HospitalState.DIAGNOSIS
            return HospitalState.DIAGNOSIS
        if state == HospitalState.EXAMINATION:
            context.exam_results = [
                ExamResult(name=item["name"], findings=item["findings"])
                for item in action.payload.get("exam_results", [])
            ]
            return HospitalState.DIAGNOSIS
        if state == HospitalState.DIAGNOSIS:
            if self._should_consult(action):
                context.consultation_triggered = True
                context.lead_diagnosis_id = action.payload.get("disease_id", "")
                context.lead_diagnosis_name = action.payload.get("disease_name", "")
                context.lead_diagnosis_reasoning = action.payload.get("reasoning", "")
                scores = action.payload.get("scores") or {}
                weight = max((float(v) for v in scores.values()), default=1.0)
                context.opinions.append(
                    {
                        "doctor": self._doctor_for(context, 0).name,
                        "disease_id": context.lead_diagnosis_id,
                        "disease_name": context.lead_diagnosis_name,
                        "reasoning": context.lead_diagnosis_reasoning,
                        "weight": weight,
                    }
                )
                context.consultation_round = 1
                return HospitalState.CONSULTATION_ROUND
            self._apply_diagnosis(context, action)
            return HospitalState.TREATMENT
        if state == HospitalState.CONSULTATION_ROUND:
            opinion = dict(action.payload)
            opinion["doctor"] = self._doctor_for(context, context.consultation_round).name
            context.opinions.append(opinion)
            if context.consultation_round < self.max_consultants:
                context.consultation_round += 1
                return HospitalState.CONSULTATION_ROUND
            return HospitalState.CONSULTATION_SUMMARY
        if state == HospitalState.CONSULTATION_SUMMARY:
            self._apply_diagnosis(context, action)
            return HospitalState.TREATMENT
        if state == HospitalState.TREATMENT:
            context.treatment = list(action.payload.get("treatment", []))
            return HospitalState.FOLLOW_UP
        if state == HospitalState.FOLLOW_UP:
            return HospitalState.END
        raise ValueError(f"未知状态: {state}")

    def _should_consult(self, action: Action) -> bool:
        if not self.consultation:
            return False
        scores = action.payload.get("scores") or {}
        if not scores:
            return True
        ordered = sorted((float(value) for value in scores.values()), reverse=True)
        if len(ordered) < 2:
            return False
        return (ordered[0] - ordered[1]) < self.consultation_threshold

    @staticmethod
    def _apply_diagnosis(context: ConsultationContext, action: Action) -> None:
        context.diagnosis_id = action.payload.get("disease_id", "")
        context.diagnosis_name = action.payload.get("disease_name", "")
        context.diagnosis_reasoning = action.payload.get("reasoning", "")
        context.scores = {
            str(k): float(v) for k, v in action.payload.get("scores", {}).items()
        }
