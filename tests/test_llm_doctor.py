"""D8: LLM doctor path, JSON parsing and rule fallback tests."""

from medagent_hospital.agents.doctor import DoctorAgent
from medagent_hospital.knowledge import load_knowledge_base
from medagent_hospital.llm.base import LLMBackend, RuleBackend, build_llm_backend
from medagent_hospital.simulacrum.models import ConsultationContext, PatientRecord


class FakeBackend(LLMBackend):
    name = "fake"

    def __init__(self, text: str) -> None:
        self.text = text

    def chat(self, messages, **kwargs) -> str:
        return self.text


class RaisingBackend(LLMBackend):
    name = "raising"

    def chat(self, messages, **kwargs) -> str:
        raise RuntimeError("api unavailable")


class CapturingBackend(LLMBackend):
    name = "capture"

    def __init__(self, text: str) -> None:
        self.text = text
        self.messages = None

    def chat(self, messages, **kwargs) -> str:
        self.messages = messages
        return self.text


def make_patient() -> PatientRecord:
    return PatientRecord(
        patient_id="LLM-TEST",
        name="测试病人",
        gender="male",
        age=60,
        symptoms=["沿神经分布簇集性水疱", "局部灼痛"],
        medical_history=["水痘病史"],
        risk_factors=["高龄"],
        exam_results=[],
        ground_truth_disease_id="DERM-001",
        ground_truth_disease_name="带状疱疹",
    )


def run_llm_doctor(backend: LLMBackend):
    from medagent_hospital.agents.nurse import NurseAgent
    from medagent_hospital.agents.patient import PatientAgent
    from medagent_hospital.simulacrum.runtime import HospitalRuntime

    kb = load_knowledge_base()
    doctor = DoctorAgent(kb=kb, reasoner="llm", llm=backend)
    runtime = HospitalRuntime(
        patient_agent=PatientAgent(),
        nurse_agent=NurseAgent(kb=kb),
        doctor_agent=doctor,
    )
    return runtime.run_episode(make_patient())


def test_llm_valid_json_diagnosis() -> None:
    payload = '{"disease_id": "DERM-001", "disease_name": "带状疱疹", "reasoning": "水疱沿神经分布且既往水痘史"}'
    context = run_llm_doctor(FakeBackend(payload))
    assert context.diagnosis_id == "DERM-001"
    assert context.diagnosis_reasoning.startswith("水疱")


def test_llm_malformed_output_falls_back_to_rule() -> None:
    context = run_llm_doctor(FakeBackend("抱歉，我无法诊断。"))
    assert context.diagnosis_id == "DERM-001"


def test_llm_api_error_falls_back_to_rule() -> None:
    context = run_llm_doctor(RaisingBackend())
    assert context.diagnosis_id == "DERM-001"


def test_build_llm_backend_rule_without_key() -> None:
    from medagent_hospital.config import Settings

    settings = Settings(llm_backend="deepseek", deepseek_api_key="")
    assert isinstance(build_llm_backend(settings), RuleBackend)
    assert isinstance(build_llm_backend(Settings(llm_backend="rule")), RuleBackend)


def test_llm_arbitration_uses_llm() -> None:
    from medagent_hospital.knowledge import load_knowledge_base

    kb = load_knowledge_base()
    backend = FakeBackend(
        '{"disease_id": "RESP-004", "disease_name": "肺结核", "reasoning": "病史与流行病学支持"}'
    )
    doctor = DoctorAgent(kb=kb, reasoner="llm", llm=backend)
    context = ConsultationContext(patient=make_patient())
    context.opinions = [
        {"doctor": "A", "disease_id": "RESP-001", "disease_name": "社区获得性肺炎", "weight": 2.0}
    ]
    action = doctor._arbitrate(context)
    assert action.type == "final_diagnosis"
    assert action.payload["disease_id"] == "RESP-004"
    assert action.payload["reasoning"].startswith("主任仲裁")


def test_llm_consultation_sees_prior_opinions() -> None:
    from medagent_hospital.knowledge import load_knowledge_base

    kb = load_knowledge_base()
    backend = CapturingBackend(
        '{"disease_id": "RESP-004", "disease_name": "肺结核", "reasoning": "参考既往意见"}'
    )
    doctor = DoctorAgent(kb=kb, reasoner="llm", llm=backend)
    context = ConsultationContext(patient=make_patient())
    context.department = "呼吸科"
    context.opinions = [
        {
            "doctor": "主诊医生",
            "disease_id": "RESP-001",
            "disease_name": "社区获得性肺炎",
            "weight": 2.0,
        }
    ]
    action = doctor._consult_opinion(context)
    user_content = backend.messages[-1]["content"]
    assert "已有会诊意见" in user_content
    assert "主诊医生" in user_content
    assert action.payload["disease_id"] == "RESP-004"
