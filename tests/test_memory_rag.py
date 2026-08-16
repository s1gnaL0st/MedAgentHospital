"""D5-D6: RAG memory-augmented diagnosis tests."""

from medagent_hospital.agents.doctor import DoctorAgent
from medagent_hospital.knowledge import load_knowledge_base
from medagent_hospital.memory.case_base import MedicalCase, MedicalCaseBase
from medagent_hospital.memory.experience_base import ExperienceBase, ExperienceRule
from medagent_hospital.simulacrum.demo import build_runtime
from medagent_hospital.simulacrum.memory_manager import MemoryManager
from medagent_hospital.simulacrum.models import ConsultationContext, ExamResult, PatientRecord
from medagent_hospital.simulacrum.patient_generator import PatientGenerator


def make_patient(
    symptoms: list[str],
    ground_truth_id: str = "",
    ground_truth_name: str = "",
    exams: list[ExamResult] | None = None,
) -> PatientRecord:
    return PatientRecord(
        patient_id="TEST-PATIENT",
        name="测试病人",
        gender="any",
        age=50,
        symptoms=symptoms,
        medical_history=[],
        risk_factors=[],
        exam_results=exams or [],
        ground_truth_disease_id=ground_truth_id,
        ground_truth_disease_name=ground_truth_name,
    )


def hard_patient() -> PatientRecord:
    return make_patient(
        symptoms=["喘息", "胸闷", "咳嗽"],
        ground_truth_id="RESP-002",
        ground_truth_name="慢性阻塞性肺疾病",
        exams=[
            ExamResult(name="肺功能", findings="未见明显异常"),
            ExamResult(name="胸部CT", findings="未见明显异常"),
            ExamResult(name="血气分析", findings="未见明显异常"),
        ],
    )


def easy_copd_patient() -> PatientRecord:
    return make_patient(
        symptoms=["慢性咳嗽", "喘息"],
        ground_truth_id="RESP-002",
        ground_truth_name="慢性阻塞性肺疾病",
        exams=[
            ExamResult(name="肺功能", findings="未见明显异常"),
            ExamResult(name="胸部CT", findings="未见明显异常"),
            ExamResult(name="血气分析", findings="未见明显异常"),
        ],
    )


def test_case_base_jaccard_retrieval() -> None:
    base = MedicalCaseBase()
    base.add(
        MedicalCase(
            patient={"symptoms": ["发热", "咳嗽"], "exam_names": ["胸部CT"]},
            diagnosis="社区获得性肺炎",
            diagnosis_id="RESP-001",
            treatment="抗生素",
        )
    )
    base.add(
        MedicalCase(
            patient={"symptoms": ["多饮", "多尿"], "exam_names": []},
            diagnosis="2型糖尿病",
            diagnosis_id="ENDO-001",
            treatment="二甲双胍",
        )
    )
    hits = base.retrieve({"symptoms": ["发热", "咳嗽", "乏力"], "exam_names": ["胸部CT"]}, top_k=1)
    assert hits[0].case.diagnosis_id == "RESP-001"
    assert hits[0].score > 0


def test_experience_rule_retrieval() -> None:
    base = ExperienceBase()
    rule = ExperienceRule(
        trigger=("胸骨后压榨样疼痛", "肌钙蛋白升高"),
        rule="胸痛伴肌钙蛋白升高优先考虑心梗",
        favor="CARD-001",
    )
    base.add(rule)
    patient = make_patient(
        symptoms=["胸骨后压榨样疼痛"],
        exams=[ExamResult(name="肌钙蛋白", findings="显著升高")],
    )
    hits = base.retrieve(patient, top_k=4)
    assert hits and hits[0].rule.favor == "CARD-001"


def test_case_base_boosts_diagnosis() -> None:
    kb = load_knowledge_base()
    patient = hard_patient()

    runtime, _ = build_runtime(kb)
    baseline = runtime.run_episode(patient)
    assert baseline.diagnosis_id != patient.ground_truth_disease_id

    case_base = MedicalCaseBase()
    case_base.add(
        MedicalCase(
            patient={"symptoms": ["喘息", "胸闷", "咳嗽"], "exam_names": []},
            diagnosis="慢性阻塞性肺疾病",
            diagnosis_id="RESP-002",
            treatment="支气管扩张剂",
        )
    )
    memory_runtime, _ = build_runtime_with_doctor(
        kb, DoctorAgent(kb=kb, case_base=case_base, case_weight=2.0, reasoner="rule")
    )
    context = memory_runtime.run_episode(patient)
    assert context.diagnosis_id == patient.ground_truth_disease_id
    assert context.retrieved_cases


def test_experience_rule_boosts_diagnosis() -> None:
    kb = load_knowledge_base()
    patient = hard_patient()
    experience_base = ExperienceBase()
    experience_base.add(
        ExperienceRule(
            trigger=("喘息", "胸闷", "咳嗽"),
            rule="喘息胸闷咳嗽组合优先考虑慢阻肺",
            favor="RESP-002",
            strength=2.0,
        )
    )
    memory_runtime, _ = build_runtime_with_doctor(
        kb, DoctorAgent(kb=kb, experience_base=experience_base, reasoner="rule")
    )
    context = memory_runtime.run_episode(patient)
    assert context.diagnosis_id == patient.ground_truth_disease_id
    assert context.retrieved_rules


def test_memory_manager_reflect() -> None:
    kb = load_knowledge_base()
    manager = MemoryManager(kb)
    patient = make_patient(
        symptoms=["沿神经分布簇集性水疱", "局部灼痛"],
        ground_truth_id="DERM-001",
        ground_truth_name="带状疱疹",
    )
    context = ConsultationContext(patient=patient, diagnosis_id="DERM-008", diagnosis_name="单纯疱疹")
    rule = manager.reflect(patient, context)
    assert rule is not None
    assert rule.favor == "DERM-001"
    assert rule.against == "DERM-008"
    assert rule.trigger


def test_memory_manager_update_success_adds_case() -> None:
    kb = load_knowledge_base()
    manager = MemoryManager(kb)
    patient = PatientGenerator(kb, seed=1).generate(disease_id="RESP-001")
    runtime, _ = build_runtime(kb)
    context = runtime.run_episode(patient)
    result = manager.update(context, patient)
    has_evidence = any(exam.is_abnormal() for exam in context.exam_results)
    assert result == ("case_added" if has_evidence else "case_skipped_no_evidence")
    assert len(manager.case_base) == (1 if has_evidence else 0)


def test_memory_manager_validation_keeps_helpful_rule() -> None:
    kb = load_knowledge_base()
    easy = easy_copd_patient()
    hard = hard_patient()
    manager = MemoryManager(kb, validation_patients=[easy, hard])
    rule = ExperienceRule(
        trigger=("喘息", "胸闷", "咳嗽"),
        rule="喘息胸闷咳嗽组合优先考虑慢阻肺",
        favor="RESP-002",
        strength=5.0,
    )
    assert manager.validate_rule(rule) is True


def test_memory_manager_validation_discards_harmful_rule() -> None:
    kb = load_knowledge_base()
    easy = easy_copd_patient()
    hard = hard_patient()
    manager = MemoryManager(kb, validation_patients=[easy, hard])
    rule = ExperienceRule(
        trigger=("慢性咳嗽",),
        rule="慢性咳嗽优先考虑哮喘",
        favor="RESP-003",
        strength=5.0,
    )
    assert manager.validate_rule(rule) is False


def build_runtime_with_doctor(kb, doctor):
    from medagent_hospital.agents.nurse import NurseAgent
    from medagent_hospital.agents.patient import PatientAgent
    from medagent_hospital.simulacrum.runtime import HospitalRuntime

    return HospitalRuntime(
        patient_agent=PatientAgent(),
        nurse_agent=NurseAgent(kb=kb),
        doctor_agent=doctor,
    ), kb
