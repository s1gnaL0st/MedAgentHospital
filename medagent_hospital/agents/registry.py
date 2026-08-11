"""Per-department doctor registry for independent memories."""

from __future__ import annotations

from medagent_hospital.agents.doctor import DoctorAgent
from medagent_hospital.knowledge import KnowledgeBase


class DoctorRegistry:
    def __init__(
        self,
        kb: KnowledgeBase,
        reasoner: str = "rule",
        doctors_per_department: int = 1,
        **kwargs,
    ) -> None:
        self.kb = kb
        self.doctors = {
            department: DoctorAgent(
                name=f"{department}医生",
                kb=kb,
                reasoner=reasoner,
                **kwargs,
            )
            for department in kb.departments
        }
        self.consultants = {
            department: [
                (
                    DoctorAgent(
                        name=f"{department}会诊医生{i}（检查导向）",
                        kb=kb,
                        reasoner=reasoner,
                        focus="exam",
                        symptom_weight=0.9,
                        exam_weight=1.8,
                        history_weight=0.9,
                        **kwargs,
                    )
                    if i == 1
                    else DoctorAgent(
                        name=f"{department}会诊医生{i}（病史导向）",
                        kb=kb,
                        reasoner=reasoner,
                        focus="history",
                        symptom_weight=0.9,
                        exam_weight=0.7,
                        history_weight=2.0,
                        **kwargs,
                    )
                )
                for i in range(1, doctors_per_department)
            ]
            for department in kb.departments
        }

    def get(self, department: str | None, index: int = 0) -> DoctorAgent:
        if department and department in self.doctors:
            if index <= 0:
                return self.doctors[department]
            consultants = self.consultants[department]
            return consultants[index - 1] if consultants else self.doctors[department]
        return next(iter(self.doctors.values()))

    def values(self) -> list[DoctorAgent]:
        return list(self.doctors.values())

    def items(self):
        return self.doctors.items()

    def __getitem__(self, department: str) -> DoctorAgent:
        return self.get(department)

    def __len__(self) -> int:
        return len(self.doctors) + sum(len(items) for items in self.consultants.values())
