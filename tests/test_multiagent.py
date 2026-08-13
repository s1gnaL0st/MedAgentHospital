"""True multi-agent collaboration tests: nurse follow-up and doctor consultation."""

from medagent_hospital.agents.nurse import NurseAgent
from medagent_hospital.agents.patient import PatientAgent
from medagent_hospital.agents.registry import DoctorRegistry
from medagent_hospital.knowledge import load_knowledge_base
from medagent_hospital.simulacrum.models import ConsultationContext, ExamResult, HospitalState, PatientRecord
from medagent_hospital.simulacrum.patient_generator import PatientGenerator
from medagent_hospital.simulacrum.runtime import HospitalRuntime


def make_hard_patient() -> PatientRecord:
    return PatientRecord(
        patient_id="MULTI-001",
        name="会诊病人",
        gender="male",
        age=60,
        symptoms=["喘息", "胸闷", "咳嗽"],
        medical_history=["吸烟"],
        risk_factors=["吸烟"],
        exam_results=[
            ExamResult(name="肺功能", findings="未见明显异常"),
            ExamResult(name="胸部CT", findings="未见明显异常"),
            ExamResult(name="血气分析", findings="未见明显异常"),
        ],
        ground_truth_disease_id="RESP-002",
        ground_truth_disease_name="慢性阻塞性肺疾病",
    )


def test_registry_provides_consultants() -> None:
    kb = load_knowledge_base()
    registry = DoctorRegistry(kb, reasoner="rule", doctors_per_department=3)
    assert len(registry) == 18
    department = kb.departments[1]
    lead = registry.get(department, 0)
    consultant = registry.get(department, 1)
    assert lead is not consultant
    assert "会诊医生" in consultant.name


def test_doctor_followup_adds_symptoms() -> None:
    kb = load_knowledge_base()
    generator = PatientGenerator(
        kb,
        seed=3,
        symptom_omission_probability=0.8,
        distractor_probability=0.3,
    )
    patient = generator.generate(disease_id="RESP-002")
    initial_symptoms = list(patient.symptoms)
    runtime = HospitalRuntime(
        patient_agent=PatientAgent(kb=kb),
        nurse_agent=NurseAgent(kb=kb),
        doctor_agent=DoctorRegistry(kb, reasoner="rule", doctors_per_department=1),
        nurse_questions=2,
    )
    context = runtime.run_episode(patient)
    assert context.nurse_questions == 2
    question_entries = [
        entry for entry in context.transcript if entry["state"] == "symptom_question"
    ]
    assert question_entries and "医生" in question_entries[0]["agent"]
    assert any(entry["state"] == "symptom_answer" for entry in context.transcript)
    assert len(context.patient.symptoms) >= len(initial_symptoms)


def test_consultation_triggers_on_low_confidence() -> None:
    kb = load_knowledge_base()
    registry = DoctorRegistry(kb, reasoner="rule", doctors_per_department=3)
    runtime = HospitalRuntime(
        patient_agent=PatientAgent(kb=kb),
        nurse_agent=NurseAgent(kb=kb),
        doctor_agent=registry,
        consultation=True,
        consultation_threshold=0.9,
        max_consultants=2,
    )
    context = runtime.run_episode(make_hard_patient())
    assert context.current_state == HospitalState.END
    assert context.consultation_triggered is True
    assert len(context.opinions) == 3
    assert any(entry["state"] == "consultation_round" for entry in context.transcript)
    assert any(entry["state"] == "consultation_summary" for entry in context.transcript)
    assert context.diagnosis_id


def make_perspective_patient() -> PatientRecord:
    return PatientRecord(
        patient_id="PERSP-001",
        name="视角病人",
        gender="male",
        age=50,
        symptoms=["发热", "咳嗽", "午后低热", "盗汗"],
        medical_history=["糖尿病"],
        risk_factors=["糖尿病"],
        exam_results=[ExamResult(name="胸部CT", findings="肺叶实变影")],
        ground_truth_disease_id="RESP-001",
        ground_truth_disease_name="社区获得性肺炎",
    )


def test_consultants_have_different_perspectives() -> None:
    kb = load_knowledge_base()
    registry = DoctorRegistry(kb, reasoner="rule", doctors_per_department=3)
    department = kb.departments[1]
    exam_doctor = registry.get(department, 1)
    history_doctor = registry.get(department, 2)
    assert exam_doctor.focus == "exam"
    assert history_doctor.focus == "history"

    patient = make_perspective_patient()
    context_one = ConsultationContext(patient=patient)
    context_one.department = department
    context_one.exam_results = patient.exam_results
    context_two = ConsultationContext(patient=patient)
    context_two.department = department
    context_two.exam_results = patient.exam_results

    opinion_one = exam_doctor._consult_opinion(context_one)
    opinion_two = history_doctor._consult_opinion(context_two)
    assert opinion_one.payload["disease_id"] == "RESP-001"
    assert opinion_two.payload["disease_id"] == "RESP-004"
    assert opinion_one.payload["disease_id"] != opinion_two.payload["disease_id"]


def test_arbitration_resolves_conflict() -> None:
    kb = load_knowledge_base()
    registry = DoctorRegistry(kb, reasoner="rule", doctors_per_department=3)
    arbiter = registry.get(kb.departments[1], 0)
    context = ConsultationContext(patient=make_perspective_patient())
    context.lead_diagnosis_id = "RESP-001"
    context.opinions = [
        {"doctor": "主诊医生", "disease_id": "RESP-001", "disease_name": "社区获得性肺炎", "weight": 3.5},
        {"doctor": "检查导向会诊医生", "disease_id": "RESP-001", "disease_name": "社区获得性肺炎", "weight": 4.5},
        {"doctor": "病史导向会诊医生", "disease_id": "RESP-004", "disease_name": "肺结核", "weight": 3.2},
    ]
    action = arbiter._arbitrate(context)
    assert action.type == "final_diagnosis"
    assert action.payload["disease_id"] == "RESP-001"
    assert action.payload["reasoning"].startswith("主任仲裁")
