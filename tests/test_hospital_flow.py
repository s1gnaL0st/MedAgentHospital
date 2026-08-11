"""D3-D4 acceptance: custom runtime and rule-mode doctor diagnosis."""

from medagent_hospital.knowledge import load_knowledge_base
from medagent_hospital.simulacrum.demo import build_runtime, run_small_diagnostic_test
from medagent_hospital.simulacrum.models import HospitalState
from medagent_hospital.simulacrum.patient_generator import PatientGenerator


def test_small_diagnostic_test_accuracy() -> None:
    result = run_small_diagnostic_test(patients_per_department=5, seed=42)
    assert result["total"] == 30
    assert result["accuracy"] >= 0.8, result["by_department"]
    assert all(
        department["total"] == 5 for department in result["by_department"].values()
    )


def test_runtime_full_flow_reaches_end() -> None:
    kb = load_knowledge_base()
    runtime, _ = build_runtime(kb)
    generator = PatientGenerator(kb, seed=7)
    patient = generator.generate(disease_id="DERM-001")
    context = runtime.run_episode(patient)
    assert context.current_state == HospitalState.END
    assert context.diagnosis_id == "DERM-001"
    assert context.treatment
    assert len(context.transcript) >= 6


def test_triage_routes_typical_case() -> None:
    kb = load_knowledge_base()
    runtime, _ = build_runtime(kb)
    generator = PatientGenerator(kb, seed=3)
    patient = generator.generate(disease_id="RESP-001")
    context = runtime.run_episode(patient)
    assert context.department == "呼吸科"


def test_ground_truth_hidden_from_doctor_view() -> None:
    kb = load_knowledge_base()
    generator = PatientGenerator(kb, seed=1)
    patient = generator.generate(department="心内科")
    view = patient.doctor_view()
    assert "ground_truth_disease_id" not in view
    assert "ground_truth_disease_name" not in view
    assert "disease_id" not in view
