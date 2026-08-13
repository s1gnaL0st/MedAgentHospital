"""Guide agent (导医) tests."""

from medagent_hospital.agents.guide import GuideAgent
from medagent_hospital.agents.nurse import NurseAgent
from medagent_hospital.agents.patient import PatientAgent
from medagent_hospital.agents.registry import DoctorRegistry
from medagent_hospital.knowledge import load_knowledge_base
from medagent_hospital.simulacrum.models import ConsultationContext, HospitalState
from medagent_hospital.simulacrum.patient_generator import PatientGenerator
from medagent_hospital.simulacrum.runtime import HospitalRuntime


def test_guide_rule_triage() -> None:
    kb = load_knowledge_base()
    guide = GuideAgent(kb=kb, reasoner="rule")
    patient = PatientGenerator(kb, seed=1).generate(disease_id="RESP-001")
    context = ConsultationContext(patient=patient)
    context.current_state = HospitalState.TRIAGE
    action = guide.run(context)
    assert action.payload["department"] == "呼吸科"


def test_guide_memory_case_and_rule() -> None:
    kb = load_knowledge_base()
    guide = GuideAgent(kb=kb, reasoner="rule")
    patient = PatientGenerator(kb, seed=1).generate(disease_id="RESP-001")

    good = ConsultationContext(patient=patient)
    good.department = "呼吸科"
    assert guide.update_memory(good, patient) == "case_added"
    assert len(guide.case_base) == 1

    bad = ConsultationContext(patient=patient)
    bad.department = "心内科"
    assert guide.update_memory(bad, patient) == "rule_added"
    assert len(guide.experience_base) == 1


def test_runtime_uses_guide_for_triage() -> None:
    kb = load_knowledge_base()
    guide = GuideAgent(kb=kb, reasoner="rule")
    runtime = HospitalRuntime(
        patient_agent=PatientAgent(kb=kb),
        nurse_agent=NurseAgent(kb=kb),
        doctor_agent=DoctorRegistry(kb, reasoner="rule", doctors_per_department=1),
        guide_agent=guide,
    )
    patient = PatientGenerator(kb, seed=1).generate(disease_id="RESP-001")
    context = runtime.run_episode(patient)
    triage_entries = [entry for entry in context.transcript if entry["state"] == "triage"]
    assert triage_entries and "导医" in triage_entries[0]["agent"]
