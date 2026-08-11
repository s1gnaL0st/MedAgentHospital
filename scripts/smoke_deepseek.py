"""Run one DeepSeek diagnosis smoke test.

Requires ``F:\\MedAgent\\.env`` with ``LLM_BACKEND=deepseek`` and
``DEEPSEEK_API_KEY=sk-...``.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from medagent_hospital.agents.doctor import DoctorAgent  # noqa: E402
from medagent_hospital.agents.nurse import NurseAgent  # noqa: E402
from medagent_hospital.agents.patient import PatientAgent  # noqa: E402
from medagent_hospital.knowledge import load_knowledge_base  # noqa: E402
from medagent_hospital.simulacrum.patient_generator import PatientGenerator  # noqa: E402
from medagent_hospital.simulacrum.runtime import HospitalRuntime  # noqa: E402


def main() -> int:
    kb = load_knowledge_base()
    patient = PatientGenerator(kb, seed=1).generate(disease_id="DERM-001")
    doctor = DoctorAgent(kb=kb, reasoner="llm")
    if doctor.llm.name == "rule":
        print("未检测到 DeepSeek API key，请先配置 .env")
        return 1
    runtime = HospitalRuntime(
        patient_agent=PatientAgent(),
        nurse_agent=NurseAgent(kb=kb),
        doctor_agent=doctor,
    )
    context = runtime.run_episode(patient)
    correct = context.diagnosis_id == patient.ground_truth_disease_id
    print(f"预测：{context.diagnosis_name} | 真实：{patient.ground_truth_disease_name} | 正确：{correct}")
    print(f"推理：{context.diagnosis_reasoning[:300]}")
    return 0 if correct else 2


if __name__ == "__main__":
    raise SystemExit(main())
