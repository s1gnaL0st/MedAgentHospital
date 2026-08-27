"""Reproducible mechanism experiments for multi-agent hospital evolution.

The experiment evaluates orchestration and memory mechanisms, not clinical
safety or real-world diagnostic validity. Every condition receives the same
generated cohorts. Training can update memory, validation is used only for
admitting reflection rules, and the held-out test cohort is read-only.
"""

from __future__ import annotations

import hashlib
import json
import random
import statistics
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from medagent_hospital.agents.nurse import NurseAgent
from medagent_hospital.agents.patient import PatientAgent
from medagent_hospital.agents.registry import DoctorRegistry
from medagent_hospital.knowledge import KnowledgeBase, load_knowledge_base
from medagent_hospital.llm.base import build_llm_backend
from medagent_hospital.memory.case_base import MedicalCaseBase
from medagent_hospital.memory.experience_base import ExperienceBase
from medagent_hospital.memory.skill_base import DiagnosticSkill, DiagnosticSkillBase
from medagent_hospital.simulacrum.evolution import CONFUSABLE_GROUPS
from medagent_hospital.simulacrum.memory_manager import MemoryManager
from medagent_hospital.simulacrum.models import ConsultationContext, PatientRecord
from medagent_hospital.simulacrum.patient_generator import PatientGenerator
from medagent_hospital.simulacrum.runtime import HospitalRuntime


@dataclass
class ExperimentConfig:
    """Configuration for the first paired, offline-friendly experiment."""

    reasoner: str = "rule"
    seeds: tuple[int, ...] = (42, 2024, 7)
    # 6 departments x 168 = 1,008 patients per split, close to the planned 1k.
    patients_per_department: int = 168
    # The validation set is also used for checkpoint selection; four examples
    # per disease are too noisy for a 48-disease hospital.
    validation_patients_per_disease: int = 8
    test_patients_per_department: int = 168
    batch_size: int = 24
    symptom_omission_probability: float = 0.35
    distractor_probability: float = 0.5
    exam_hit_rate: float = 0.6
    confusable_probability: float = 0.8
    confusable_true_ratio: float = 0.5
    consultation_threshold: float = 0.35
    max_consultants: int = 2
    max_steps: int = 20
    nurse_questions: int = 0
    # Cases are evidence, not a vote for their historical diagnosis. A large
    # bonus lets one partially similar case override the knowledge-base score.
    case_weight: float = 0.2
    top_k_cases: int = 3
    top_k_rules: int = 4
    dedup_threshold: float = 0.9
    rule_strength: float = 0.6
    replay_every_rounds: int = 1
    replay_buffer_size: int = 50
    selective_replay_size: int = 20
    lifecycle_every_rounds: int = 1
    min_survival_rate: float = 0.4
    min_validations: int = 3
    use_curriculum: bool = False

    def __post_init__(self) -> None:
        if self.reasoner not in {"rule", "llm"}:
            raise ValueError("reasoner must be 'rule' or 'llm'")
        if not self.seeds:
            raise ValueError("at least one seed is required")
        if self.patients_per_department < 0 or self.test_patients_per_department < 0:
            raise ValueError("patient counts cannot be negative")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self.max_consultants < 1:
            raise ValueError("max_consultants must be at least one")


# B0/B1 isolate memory; B0/B2 isolate collaboration; B3/B4 isolate evolution;
# B2/B5 isolate adaptive routing from a fixed, always-consult workflow.
CONDITIONS: dict[str, dict[str, Any]] = {
    "B0": {
        "label": "单医生 + 无记忆",
        "multi_agent": False,
        "memory": "none",
        "evolve": False,
        "fixed": False,
    },
    "B1": {
        "label": "单医生 + 案例记忆",
        "multi_agent": False,
        "memory": "cases",
        "evolve": False,
        "fixed": False,
    },
    "B2": {
        "label": "动态会诊 + 无记忆",
        "multi_agent": True,
        "memory": "none",
        "evolve": False,
        "fixed": False,
    },
    "B3": {
        "label": "动态会诊 + 案例记忆",
        "multi_agent": True,
        "memory": "cases",
        "evolve": False,
        "fixed": False,
    },
    "B4": {
        "label": "动态会诊 + 失败反思自进化",
        "multi_agent": True,
        "memory": "full",
        "evolve": True,
        "fixed": False,
    },
    "B5": {
        "label": "固定流程 + 每例会诊",
        "multi_agent": True,
        "memory": "none",
        "evolve": False,
        "fixed": True,
    },
    "B6": {
        "label": "验证器驱动的选择性自进化",
        "multi_agent": True,
        "memory": "full",
        "evolve": True,
        "fixed": False,
        "selective": True,
    },
    "B7": {
        "label": "技能级自进化（验证器准入）",
        "multi_agent": True,
        "memory": "cases",
        "evolve": True,
        "fixed": False,
        "skill": True,
        "selective": True,
    },
    "B8": {
        "label": "主动检查技能自进化（验证器准入）",
        "multi_agent": True,
        "memory": "cases",
        "evolve": True,
        "fixed": False,
        "skill": True,
        "active_skill": True,
        "selective": True,
    },
}


@dataclass
class Cohorts:
    train: dict[str, list[PatientRecord]]
    validation: dict[str, list[PatientRecord]]
    test: dict[str, list[PatientRecord]]
    test_tags: dict[str, str]


@dataclass
class ConditionState:
    doctors: DoctorRegistry
    case_bases: dict[str, MedicalCaseBase]
    rule_bases: dict[str, ExperienceBase]
    skill_bases: dict[str, DiagnosticSkillBase]
    validation: dict[str, list[PatientRecord]]
    managers: dict[str, MemoryManager]
    replay_buffers: dict[str, list[tuple[float, PatientRecord]]]
    llm_backend: Any | None = None
    replay_episodes: int = 0
    replay_recovered: int = 0


def _patient_payload(patient: PatientRecord) -> dict[str, Any]:
    return {
        "patient_id": patient.patient_id,
        "age": patient.age,
        "gender": patient.gender,
        "symptoms": list(patient.symptoms),
        "medical_history": list(patient.medical_history),
        "risk_factors": list(patient.risk_factors),
        "exams": [{"name": e.name, "findings": e.findings} for e in patient.exam_results],
        "ground_truth": patient.ground_truth_disease_id,
    }


def _case_payload(case: Any) -> dict[str, Any]:
    return {
        "patient": case.patient,
        "diagnosis_id": case.diagnosis_id,
        "diagnosis": case.diagnosis,
        "treatment": case.treatment,
        "created_at": case.created_at,
        "last_accessed_at": case.last_accessed_at,
        "importance": case.importance,
        "retrieval_count": case.retrieval_count,
    }


def _cohort_hash(cohort: dict[str, list[PatientRecord]]) -> str:
    payload = [
        _patient_payload(patient)
        for department in sorted(cohort)
        for patient in cohort[department]
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _memory_signature(
    case_bases: dict[str, MedicalCaseBase],
    rule_bases: dict[str, ExperienceBase],
    skill_bases: dict[str, DiagnosticSkillBase] | None = None,
) -> str:
    payload = {
        "cases": {
            department: [_case_payload(case) for case in base._cases]
            for department, base in sorted(case_bases.items())
        },
        "rules": {
            department: [asdict(rule) for rule in base]
            for department, base in sorted(rule_bases.items())
        },
        "skills": {
            department: [asdict(skill) for skill in base]
            for department, base in sorted((skill_bases or {}).items())
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ExperimentRunner:
    """Run paired mechanism conditions with a non-mutating test evaluator."""

    def __init__(
        self,
        kb: KnowledgeBase | None = None,
        config: ExperimentConfig | None = None,
    ) -> None:
        self.kb = kb or load_knowledge_base()
        self.config = config or ExperimentConfig()

    def run(self, conditions: tuple[str, ...] = tuple(CONDITIONS)) -> dict[str, Any]:
        if not conditions:
            raise ValueError("at least one experiment condition is required")
        for condition in conditions:
            if condition not in CONDITIONS:
                raise ValueError(f"unknown experiment condition: {condition}")

        datasets = {seed: self._build_cohorts(seed) for seed in self.config.seeds}
        reports: dict[str, list[dict[str, Any]]] = {
            condition: [] for condition in conditions
        }
        for seed, cohorts in datasets.items():
            for condition in conditions:
                reports[condition].append(
                    self._run_condition(condition, seed, cohorts)
                )

        return {
            "protocol": "mechanism-v1",
            "objective": (
                "在相同病例、推理后端和实验预算下，评估多 Agent 协作、记忆检索"
                "与失败反思自进化对未见仿真病例决策的影响。"
            ),
            "scope": "机制验证，不代表临床有效性或医疗安全性",
            "config": asdict(self.config),
            "conditions": {
                condition: CONDITIONS[condition] for condition in conditions
            },
            "cohort_manifest": {
                "knowledge_base": str(self.kb.source or ""),
                "disease_count": len(self.kb.diseases),
                "departments": list(self.kb.departments),
                "seeds": {
                    str(seed): {
                        "train": _cohort_hash(cohorts.train),
                        "validation": _cohort_hash(cohorts.validation),
                        "test": _cohort_hash(cohorts.test),
                        "counts": {
                            "train": sum(len(items) for items in cohorts.train.values()),
                            "validation": sum(
                                len(items) for items in cohorts.validation.values()
                            ),
                            "test": sum(len(items) for items in cohorts.test.values()),
                        },
                    }
                    for seed, cohorts in datasets.items()
                },
            },
            "reports": reports,
            "summary": self._summarize(reports),
        }

    def _build_cohorts(self, seed: int) -> Cohorts:
        train: dict[str, list[PatientRecord]] = {}
        validation: dict[str, list[PatientRecord]] = {}
        test: dict[str, list[PatientRecord]] = {}
        test_tags: dict[str, str] = {}

        for department_index, department in enumerate(self.kb.departments):
            train[department] = self._build_train_department(
                seed, department_index, department
            )
            validation[department] = self._build_validation_department(
                seed, department_index, department
            )
            test[department], tags = self._build_test_department(
                seed, department_index, department
            )
            test_tags.update(tags)
        return Cohorts(train, validation, test, test_tags)

    def _build_train_department(
        self,
        seed: int,
        department_index: int,
        department: str,
    ) -> list[PatientRecord]:
        total = self.config.patients_per_department
        rounds = max(1, (total + self.config.batch_size - 1) // self.config.batch_size)
        patients: list[PatientRecord] = []
        for round_index in range(rounds):
            # The main experiment uses the same difficulty distribution as the
            # held-out test set. Curriculum is a separate ablation, otherwise
            # train/test shift can masquerade as failed self-evolution.
            difficulty = (round_index + 1) / rounds if self.config.use_curriculum else 1.0
            generator = self._make_generator(
                seed * 1009 + department_index * 97 + round_index * 13 + 11,
                difficulty,
            )
            rng = random.Random(
                seed * 1009 + department_index * 97 + round_index * 13 + 101
            )
            remaining = total - len(patients)
            for _ in range(min(self.config.batch_size, max(0, remaining))):
                patient, _ = self._generate_patient(department, generator, rng, difficulty)
                patients.append(
                    self._label_patient(
                        patient,
                        f"train-{seed}-{department_index:02d}-{len(patients):04d}",
                    )
                )
        return patients

    def _build_validation_department(
        self,
        seed: int,
        department_index: int,
        department: str,
    ) -> list[PatientRecord]:
        generator = self._make_generator(
            seed * 1009 + department_index * 97 + 23,
            difficulty=1.0,
        )
        rng = random.Random(seed * 1009 + department_index * 97 + 211)
        patients: list[PatientRecord] = []
        for disease in self.kb.by_department(department):
            for _ in range(self.config.validation_patients_per_disease):
                # Validation must match the held-out target distribution. A
                # clean-only validation set would admit rules that fail on the
                # confusable cases the experiment is designed to measure.
                patient, _ = self._generate_patient(department, generator, rng, 1.0)
                # Keep equal disease coverage while retaining the same
                # confusable-symptom construction used by the test cohort.
                if patient.ground_truth_disease_id != disease.id:
                    patient = generator.generate(disease_id=disease.id)
                    groups = CONFUSABLE_GROUPS.get(department, [])
                    group = next((item for item in groups if disease.id in item), ())
                    if group and rng.random() < self.config.confusable_probability:
                        patient = self._mix_symptoms(patient, group, rng)
                patients.append(
                    self._label_patient(
                        patient,
                        f"validation-{seed}-{department_index:02d}-{len(patients):04d}",
                    )
                )
        return patients

    def _build_test_department(
        self,
        seed: int,
        department_index: int,
        department: str,
    ) -> tuple[list[PatientRecord], dict[str, str]]:
        generator = self._make_generator(
            seed * 1009 + department_index * 97 + 37,
            difficulty=1.0,
        )
        rng = random.Random(seed * 1009 + department_index * 97 + 401)
        patients: list[PatientRecord] = []
        tags: dict[str, str] = {}
        for _ in range(self.config.test_patients_per_department):
            patient, tag = self._generate_patient(department, generator, rng, 1.0)
            patient = self._label_patient(
                patient,
                f"test-{seed}-{department_index:02d}-{len(patients):04d}",
            )
            patients.append(patient)
            tags[patient.patient_id] = tag
        return patients, tags

    def _make_generator(self, seed: int, difficulty: float) -> PatientGenerator:
        return PatientGenerator(
            self.kb,
            seed=seed,
            distractor_probability=min(
                1.0, self.config.distractor_probability * difficulty
            ),
            symptom_omission_probability=min(
                1.0, self.config.symptom_omission_probability * difficulty
            ),
            exam_hit_rate_override=0.85
            + (self.config.exam_hit_rate - 0.85) * difficulty,
        )

    def _generate_patient(
        self,
        department: str,
        generator: PatientGenerator,
        rng: random.Random,
        difficulty: float,
    ) -> tuple[PatientRecord, str]:
        groups = CONFUSABLE_GROUPS.get(department, [])
        probability = min(
            1.0, max(0.0, self.config.confusable_probability * difficulty)
        )
        if groups and rng.random() < probability:
            group = rng.choice(groups)
            patient = generator.generate(disease_id=rng.choice(group))
            return self._mix_symptoms(patient, group, rng), "confusable"
        return generator.generate(department=department), "ordinary"

    def _mix_symptoms(
        self,
        patient: PatientRecord,
        group: tuple[str, ...],
        rng: random.Random,
    ) -> PatientRecord:
        true_disease = self.kb.get(patient.ground_truth_disease_id)
        true_weights = (
            dict(true_disease.patient_profile.symptom_weights)
            if true_disease and true_disease.patient_profile
            else {}
        )
        other_weights: dict[str, float] = {}
        for disease_id in group:
            if disease_id == patient.ground_truth_disease_id:
                continue
            disease = self.kb.get(disease_id)
            if disease and disease.patient_profile:
                for symptom, weight in disease.patient_profile.symptom_weights.items():
                    if symptom not in true_weights:
                        other_weights[symptom] = max(
                            other_weights.get(symptom, 0.0), weight
                        )

        true_pool = list(true_weights)
        other_pool = list(other_weights)
        if not true_pool:
            return patient
        count = rng.randint(3, min(5, max(3, len(true_pool) + len(other_pool))))
        true_count = max(1, round(count * self.config.confusable_true_ratio))
        symptoms = rng.choices(
            true_pool,
            weights=[true_weights[symptom] for symptom in true_pool],
            k=true_count,
        )
        if other_pool:
            other_count = max(1, count - true_count)
            symptoms += rng.choices(
                other_pool,
                weights=[other_weights[symptom] for symptom in other_pool],
                k=other_count,
            )
        return replace(patient, symptoms=list(dict.fromkeys(symptoms)))

    @staticmethod
    def _label_patient(patient: PatientRecord, patient_id: str) -> PatientRecord:
        return replace(
            patient,
            patient_id=patient_id,
            symptoms=list(patient.symptoms),
            medical_history=list(patient.medical_history),
            risk_factors=list(patient.risk_factors),
            exam_results=list(patient.exam_results),
        )

    def _run_condition(
        self,
        name: str,
        seed: int,
        cohorts: Cohorts,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        spec = CONDITIONS[name]
        state = self._build_state(spec, cohorts)
        before_dataset = self._dataset_signature(cohorts)
        points: list[dict[str, Any]] = []
        isolation_checks: list[bool] = []
        best_validation = -1
        best_treated = 0
        best_cases: dict[str, MedicalCaseBase] | None = None
        best_rules: dict[str, ExperienceBase] | None = None
        best_skills: dict[str, DiagnosticSkillBase] | None = None

        points.append(
            self._checkpoint(
                0,
                self._evaluate(state, cohorts.test, cohorts.test_tags, spec),
                state,
                isolation_checks,
            )
        )
        if spec.get("selective", False):
            best_validation = self._validation_score(state, spec)
            best_cases = deepcopy(state.case_bases)
            best_rules = deepcopy(state.rule_bases)
            best_skills = deepcopy(state.skill_bases)
        for start in range(0, self.config.patients_per_department, self.config.batch_size):
            for department in self.kb.departments:
                batch = cohorts.train[department][start : start + self.config.batch_size]
                for patient in batch:
                    context = self._episode(state.doctors, department, patient, spec)
                    self._learn(state, department, context, patient, spec)
                    if (
                        spec["evolve"]
                        and context.diagnosis_id != patient.ground_truth_disease_id
                    ):
                        priority = self._failure_priority(context, patient)
                        state.replay_buffers[department].append((priority, deepcopy(patient)))
                        state.replay_buffers[department] = state.replay_buffers[department][
                            -self.config.replay_buffer_size :
                        ]

            round_index = start // self.config.batch_size + 1
            if spec["evolve"] and round_index % max(1, self.config.replay_every_rounds) == 0:
                for department in self.kb.departments:
                    self._replay(state, department, spec)
            if spec["evolve"] and round_index % max(1, self.config.lifecycle_every_rounds) == 0:
                self._lifecycle(state)

            if spec.get("selective", False):
                validation_score = self._validation_score(state, spec)
                if validation_score > best_validation:
                    best_validation = validation_score
                    best_treated = min(
                        self.config.patients_per_department,
                        start + self.config.batch_size,
                    )
                    best_cases = deepcopy(state.case_bases)
                    best_rules = deepcopy(state.rule_bases)
                    best_skills = deepcopy(state.skill_bases)

            treated = min(
                self.config.patients_per_department,
                start + self.config.batch_size,
            )
            points.append(
                self._checkpoint(
                    treated,
                    self._evaluate(state, cohorts.test, cohorts.test_tags, spec),
                    state,
                    isolation_checks,
                )
            )

        after_dataset = self._dataset_signature(cohorts)
        if before_dataset != after_dataset:
            raise AssertionError("experiment mutated its source cohorts")
        if best_cases is not None and best_rules is not None and best_skills is not None:
            self._restore_memory(state, best_cases, best_rules, best_skills)
            points[-1] = self._checkpoint(
                best_treated,
                self._evaluate(state, cohorts.test, cohorts.test_tags, spec),
                state,
                isolation_checks,
            )
        return {
            "condition": name,
            "label": spec["label"],
            "seed": seed,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "checkpoints": points,
            "initial": points[0],
            "final": points[-1],
            "test_memory_isolation": all(isolation_checks),
            "replay_episodes": state.replay_episodes,
            "replay_recovered": state.replay_recovered,
            "selected_patients_treated": best_treated if best_cases is not None else None,
            "selected_validation_score": best_validation if best_cases is not None else None,
        }

    def _validation_score(self, state: ConditionState, spec: dict[str, Any]) -> int:
        """Score a candidate state without mutating its retrieval memories."""
        if spec.get("skill"):
            return sum(
                self._skill_validation_score(state, department, spec)
                for department in self.kb.departments
            )
        return sum(
            state.managers[department]._evaluate(
                deepcopy(state.rule_bases[department])
            )
            for department in self.kb.departments
        )

    @staticmethod
    def _restore_memory(
        state: ConditionState,
        cases: dict[str, MedicalCaseBase],
        rules: dict[str, ExperienceBase],
        skills: dict[str, DiagnosticSkillBase],
    ) -> None:
        """Restore stores in place so already-constructed doctors keep references."""
        for department in cases:
            state.case_bases[department]._cases = deepcopy(cases[department]._cases)
            state.case_bases[department].skipped = cases[department].skipped
            state.rule_bases[department]._rules = deepcopy(rules[department]._rules)
            state.skill_bases[department]._skills = deepcopy(skills[department]._skills)

    def _build_state(self, spec: dict[str, Any], cohorts: Cohorts) -> ConditionState:
        llm_backend = build_llm_backend() if self.config.reasoner == "llm" else None
        skill_bases = {
            department: DiagnosticSkillBase() for department in self.kb.departments
        }
        doctors = self._new_registry(spec, llm_backend)
        case_bases = {
            department: MedicalCaseBase(
                self.config.dedup_threshold if spec["memory"] != "none" else 0.0
            )
            for department in self.kb.departments
        }
        rule_bases = {department: ExperienceBase() for department in self.kb.departments}
        for department in self.kb.departments:
            lead = doctors.get(department, 0)
            if spec["memory"] == "none":
                lead.case_base = None
                lead.experience_base = None
            else:
                lead.case_base = case_bases[department]
            lead.experience_base = (
                rule_bases[department] if spec["memory"] == "full" else None
            )
            lead.skill_base = skill_bases[department] if spec.get("skill") else None

        managers = {
            department: MemoryManager(
                self.kb,
                case_base=case_bases[department],
                experience_base=rule_bases[department],
                validation_patients=cohorts.validation[department],
                rule_strength=self.config.rule_strength,
                strict_rule_improvement=bool(spec.get("selective", False)),
                min_rule_accuracy_gain=1 if spec.get("selective", False) else 0,
                case_weight=self.config.case_weight,
                reasoner=self.config.reasoner,
            )
            for department in self.kb.departments
        }
        return ConditionState(
            doctors=doctors,
            case_bases=case_bases,
            rule_bases=rule_bases,
            skill_bases=skill_bases,
            validation=cohorts.validation,
            managers=managers,
            replay_buffers={department: [] for department in self.kb.departments},
            llm_backend=llm_backend,
        )

    def _new_registry(
        self,
        spec: dict[str, Any],
        llm_backend: Any | None,
        skill_bases: dict[str, DiagnosticSkillBase] | None = None,
    ) -> DoctorRegistry:
        kwargs: dict[str, Any] = {
            "reasoner": self.config.reasoner,
            "case_weight": self.config.case_weight,
            "top_k_cases": self.config.top_k_cases,
            "top_k_rules": self.config.top_k_rules,
            "skill_weight": 0.25,
        }
        if llm_backend is not None:
            kwargs["llm"] = llm_backend
        return DoctorRegistry(
            self.kb,
            doctors_per_department=(
                self.config.max_consultants + 1 if spec["multi_agent"] else 1
            ),
            **kwargs,
        )

    def _clone_evaluation_registry(
        self,
        state: ConditionState,
        spec: dict[str, Any],
    ) -> DoctorRegistry:
        registry = self._new_registry(spec, state.llm_backend)
        for department in self.kb.departments:
            lead = registry.get(department, 0)
            if spec["memory"] == "none":
                lead.case_base = None
                lead.experience_base = None
            else:
                # Evaluation reads cloned stores, so retrieval counters in the
                # training state cannot be changed by the held-out cohort.
                lead.case_base = deepcopy(state.case_bases[department])
                lead.experience_base = (
                    deepcopy(state.rule_bases[department])
                    if spec["memory"] == "full"
                    else None
                )
                lead.skill_base = (
                    deepcopy(state.skill_bases[department])
                    if spec.get("skill") else None
                )
        return registry

    def _episode(
        self,
        doctors: DoctorRegistry,
        department: str,
        patient: PatientRecord,
        spec: dict[str, Any],
    ) -> ConsultationContext:
        doctor_agent: Any = (
            doctors if spec["multi_agent"] else doctors.get(department, 0)
        )
        runtime = HospitalRuntime(
            patient_agent=PatientAgent(kb=self.kb),
            nurse_agent=NurseAgent(kb=self.kb),
            doctor_agent=doctor_agent,
            max_steps=self.config.max_steps,
            nurse_questions=self.config.nurse_questions,
            consultation=spec["multi_agent"],
            consultation_threshold=(
                10**9 if spec["fixed"] else self.config.consultation_threshold
            ),
            max_consultants=self.config.max_consultants,
        )
        return runtime.run_episode(deepcopy(patient))

    def _learn(
        self,
        state: ConditionState,
        department: str,
        context: ConsultationContext,
        patient: PatientRecord,
        spec: dict[str, Any],
    ) -> None:
        if spec["memory"] == "none":
            return
        if spec.get("skill"):
            self._record_skill_utility(state, department, context, patient)
            if context.diagnosis_id == patient.ground_truth_disease_id:
                return
            manager = state.managers[department]
            rule = manager.reflect(patient, context)
            if rule is None:
                return
            skill = DiagnosticSkill(
                skill_id=f"S-{department}-{len(state.skill_bases[department]) + 1}",
                name=f"鉴别 {rule.favor} 与 {rule.against}",
                trigger=(
                    self._skill_trigger(rule.trigger, context)
                    if spec.get("active_skill") else rule.trigger
                ),
                favor=rule.favor,
                against=rule.against,
                action="add_exam" if spec.get("active_skill") else "rerank",
                target_exam=(
                    self._discriminative_exam(patient, context)
                    if spec.get("active_skill") else ""
                ),
                strength=0.25,
            )
            if spec.get("active_skill") and not skill.target_exam:
                return
            before = self._skill_validation_score(state, department, spec)
            candidate = deepcopy(state.skill_bases[department])
            candidate.add(skill)
            after = self._skill_validation_score(state, department, spec, candidate)
            if after > before:
                state.skill_bases[department].add(skill)
            return
        if spec["evolve"]:
            state.managers[department].update(context, patient)
            return
        # B1/B3 deliberately expose only successful case memory. Failure
        # reflection is reserved for B4 so the effect can be isolated.
        if context.diagnosis_id == patient.ground_truth_disease_id:
            if any(exam.is_abnormal() for exam in context.exam_results):
                manager = state.managers[department]
                manager.case_base.add(manager._to_case(context, patient))

    def _replay(self, state: ConditionState, department: str, spec: dict[str, Any]) -> None:
        buffer = state.replay_buffers[department]
        if not buffer:
            return
        if spec.get("selective", False):
            buffer = self._select_replay_cases(buffer)
        still_wrong: list[PatientRecord] = []
        for _, patient in buffer:
            context = self._episode(state.doctors, department, patient, spec)
            state.replay_episodes += 1
            self._learn(state, department, context, patient, spec)
            # The buffer contains only previously misdiagnosed training cases.
            if context.diagnosis_id == patient.ground_truth_disease_id:
                state.replay_recovered += 1
            if context.diagnosis_id != patient.ground_truth_disease_id:
                still_wrong.append(patient)
        state.replay_buffers[department] = [
            (0.0, patient) for patient in still_wrong[-self.config.replay_buffer_size :]
        ]

    def _skill_validation_score(
        self,
        state: ConditionState,
        department: str,
        spec: dict[str, Any],
        skills: DiagnosticSkillBase | None = None,
    ) -> int:
        """Evaluate one department's candidate skill on a frozen dev cohort."""
        lead = self._new_registry(spec, state.llm_backend).get(department, 0)
        lead.case_base = deepcopy(state.case_bases[department])
        lead.experience_base = None
        lead.skill_base = deepcopy(skills or state.skill_bases[department])
        runtime = HospitalRuntime(
            patient_agent=PatientAgent(kb=self.kb),
            nurse_agent=NurseAgent(kb=self.kb),
            doctor_agent=lead,
            consultation=False,
            max_steps=self.config.max_steps,
            nurse_questions=self.config.nurse_questions,
        )
        return sum(
            int(runtime.run_episode(deepcopy(patient)).diagnosis_id == patient.ground_truth_disease_id)
            for patient in state.validation[department]
        )

    @staticmethod
    def _record_skill_utility(
        state: ConditionState,
        department: str,
        context: ConsultationContext,
        patient: PatientRecord,
    ) -> None:
        """Credit only skill-induced action changes, never passive retrieval."""
        for action in context.skill_actions:
            if not action.get("changed"):
                continue
            if action.get("action") == "add_exam":
                # The final outcome credits an active information-gathering
                # action only if its requested exam was actually abnormal.
                requested = set(action.get("after_exams", [])) - set(action.get("before_exams", []))
                after_correct = context.diagnosis_id == patient.ground_truth_disease_id
                before_correct = False
                if not any(exam.name in requested and exam.is_abnormal() for exam in context.exam_results):
                    continue
            else:
                before_correct = (
                    action.get("before_diagnosis_id") == patient.ground_truth_disease_id
                )
                after_correct = (
                    action.get("after_diagnosis_id") == patient.ground_truth_disease_id
                )
            # Counterfactual credit is local to the changed ranking, rather
            # than a blanket reward from the entire multi-agent trajectory.
            if before_correct == after_correct:
                continue
            for skill_id in action.get("skill_ids", []):
                skill = state.skill_bases[department].get(skill_id)
                if skill is not None:
                    state.skill_bases[department].record(
                        skill,
                        correct=after_correct,
                        changed=True,
                    )

    def _discriminative_exam(
        self, patient: PatientRecord, context: ConsultationContext,
    ) -> str:
        """Derive a testable action from outcome feedback in the simulator."""
        true = self.kb.get(patient.ground_truth_disease_id)
        wrong = self.kb.get(context.diagnosis_id)
        if true is None or wrong is None:
            return ""
        wrong_exams = {exam.name for exam in wrong.examinations}
        for exam in true.examinations:
            if exam.name not in wrong_exams:
                return exam.name
        return ""

    @staticmethod
    def _skill_trigger(
        trigger: tuple[str, ...], context: ConsultationContext,
    ) -> tuple[str, ...]:
        """Active skills must be usable before the new test is ordered."""
        observed = set(context.patient.symptoms) | set(context.patient.medical_history)
        usable = tuple(term for term in trigger if term in observed)
        return usable or tuple(context.patient.symptoms[:1])

    def _failure_priority(
        self,
        context: ConsultationContext,
        patient: PatientRecord,
    ) -> float:
        """Prioritize uncertain and explicitly confusable failures for replay."""
        values = sorted(context.scores.values(), reverse=True)
        margin = values[0] - values[1] if len(values) > 1 else 0.0
        department = self.kb.get(patient.ground_truth_disease_id)
        groups = CONFUSABLE_GROUPS.get(department.department, []) if department else []
        is_confusable = any(patient.ground_truth_disease_id in group for group in groups)
        return (1.0 / (0.05 + max(0.0, margin))) + (1.0 if is_confusable else 0.0)

    def _select_replay_cases(
        self,
        buffer: list[tuple[float, PatientRecord]],
    ) -> list[tuple[float, PatientRecord]]:
        """Keep high-value failures while avoiding one-disease replay collapse."""
        selected: list[tuple[float, PatientRecord]] = []
        seen_diseases: set[str] = set()
        for item in sorted(buffer, key=lambda pair: pair[0], reverse=True):
            if item[1].ground_truth_disease_id in seen_diseases:
                continue
            selected.append(item)
            seen_diseases.add(item[1].ground_truth_disease_id)
            if len(selected) >= self.config.selective_replay_size:
                return selected
        for item in sorted(buffer, key=lambda pair: pair[0], reverse=True):
            if item not in selected:
                selected.append(item)
            if len(selected) >= self.config.selective_replay_size:
                break
        return selected

    def _lifecycle(self, state: ConditionState) -> None:
        for department in self.kb.departments:
            base = state.rule_bases[department]
            base.prune(self.config.min_survival_rate, self.config.min_validations)
            base.adjust_strengths(self.config.min_validations)
            state.skill_bases[department].prune(
                min_trials=self.config.min_validations,
                min_utility=0.0,
            )

    def _checkpoint(
        self,
        patients_treated: int,
        metrics: dict[str, Any],
        state: ConditionState,
        isolation_checks: list[bool],
    ) -> dict[str, Any]:
        isolation_checks.append(bool(metrics.pop("_test_memory_isolation")))
        return {
            "patients_treated": patients_treated,
            **metrics,
            **self._memory_metrics(state),
        }

    def _evaluate(
        self,
        state: ConditionState,
        cohort: dict[str, list[PatientRecord]],
        tags: dict[str, str],
        spec: dict[str, Any],
    ) -> dict[str, Any]:
        before = _memory_signature(state.case_bases, state.rule_bases, state.skill_bases)
        evaluation_doctors = self._clone_evaluation_registry(state, spec)
        outcomes: list[dict[str, Any]] = []
        for department in self.kb.departments:
            for patient in cohort[department]:
                context = self._episode(evaluation_doctors, department, patient, spec)
                scores = context.scores or {}
                ranked = sorted(scores, key=scores.get, reverse=True) if scores else []
                lead_id = self._lead_diagnosis(context)
                case_hits = sum(
                    int(event.get("case_hits", 0)) for event in context.memory_events
                )
                rule_hits = sum(
                    int(event.get("rule_hits", 0)) for event in context.memory_events
                )
                outcomes.append(
                    {
                        "department": department,
                        "disease_id": patient.ground_truth_disease_id,
                        "case_type": tags.get(patient.patient_id, "ordinary"),
                        "correct": context.diagnosis_id == patient.ground_truth_disease_id,
                        "lead_correct": lead_id == patient.ground_truth_disease_id,
                        "department_correct": context.department == department,
                        "top_k_correct": patient.ground_truth_disease_id in ranked[:3],
                        "scored": bool(scores),
                        "consulted": context.consultation_triggered,
                        "steps": context.steps,
                        "exams": len(context.ordered_exams),
                        "case_hits": case_hits,
                        "rule_hits": rule_hits,
                    }
                )
        after = _memory_signature(state.case_bases, state.rule_bases, state.skill_bases)
        if before != after:
            raise AssertionError("held-out test evaluation mutated agent memory")
        metrics = self._summarize_outcomes(outcomes)
        metrics["_test_memory_isolation"] = True
        return metrics

    @staticmethod
    def _lead_diagnosis(context: ConsultationContext) -> str:
        if context.lead_diagnosis_id:
            return context.lead_diagnosis_id
        for entry in context.transcript:
            if entry.get("state") == "diagnosis":
                return str(entry.get("payload", {}).get("disease_id", ""))
        return context.diagnosis_id

    def _summarize_outcomes(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        metrics = self._aggregate(outcomes)
        metrics["per_department"] = {
            department: self._aggregate(
                [item for item in outcomes if item["department"] == department]
            )
            for department in self.kb.departments
        }
        disease_ids = sorted({item["disease_id"] for item in outcomes})
        metrics["per_disease"] = {
            disease_id: self._aggregate(
                [item for item in outcomes if item["disease_id"] == disease_id]
            )
            for disease_id in disease_ids
        }
        metrics["per_case_type"] = {
            case_type: self._aggregate(
                [item for item in outcomes if item["case_type"] == case_type]
            )
            for case_type in sorted({item["case_type"] for item in outcomes})
        }
        return metrics

    @staticmethod
    def _aggregate(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(outcomes)
        if not n:
            return {
                "n": 0,
                "diagnosis_accuracy": 0.0,
                "department_accuracy": 0.0,
                "top_k_accuracy": None,
                "top_k_coverage": 0.0,
                "consultation_trigger_rate": 0.0,
                "consultation_gain": None,
                "consultation_correction_rate": None,
                "consultation_harm_rate": None,
                "lead_accuracy": 0.0,
                "average_steps": 0.0,
                "average_exam_count": 0.0,
                "case_memory_hits": 0,
                "rule_memory_hits": 0,
                "case_memory_hit_rate": 0.0,
                "rule_memory_hit_rate": 0.0,
            }
        consulted = [item for item in outcomes if item["consulted"]]
        scored = [item for item in outcomes if item["scored"]]
        return {
            "n": n,
            "diagnosis_accuracy": sum(item["correct"] for item in outcomes) / n,
            "department_accuracy": sum(item["department_correct"] for item in outcomes) / n,
            "top_k_accuracy": (
                sum(item["top_k_correct"] for item in scored) / len(scored)
                if scored
                else None
            ),
            "top_k_coverage": len(scored) / n,
            "consultation_trigger_rate": len(consulted) / n,
            "consultation_gain": (
                sum(int(item["correct"]) - int(item["lead_correct"]) for item in consulted)
                / len(consulted)
                if consulted
                else None
            ),
            "consultation_correction_rate": (
                sum(not item["lead_correct"] and item["correct"] for item in consulted)
                / len(consulted)
                if consulted
                else None
            ),
            "consultation_harm_rate": (
                sum(item["lead_correct"] and not item["correct"] for item in consulted)
                / len(consulted)
                if consulted
                else None
            ),
            "lead_accuracy": sum(item["lead_correct"] for item in outcomes) / n,
            "average_steps": sum(item["steps"] for item in outcomes) / n,
            "average_exam_count": sum(item["exams"] for item in outcomes) / n,
            "case_memory_hits": sum(item["case_hits"] for item in outcomes),
            "rule_memory_hits": sum(item["rule_hits"] for item in outcomes),
            "case_memory_hit_rate": sum(item["case_hits"] > 0 for item in outcomes) / n,
            "rule_memory_hit_rate": sum(item["rule_hits"] > 0 for item in outcomes) / n,
        }

    def _memory_metrics(self, state: ConditionState) -> dict[str, Any]:
        rules = [rule for base in state.rule_bases.values() for rule in base]
        observed_rules = [rule for rule in rules if rule.validations > 0]
        return {
            "case_count": sum(len(base) for base in state.case_bases.values()),
            "case_counts": {
                department: len(state.case_bases[department])
                for department in self.kb.departments
            },
            "case_skipped": {
                department: state.case_bases[department].skipped
                for department in self.kb.departments
            },
            "rule_count": sum(len(base) for base in state.rule_bases.values()),
            "rule_counts": {
                department: len(state.rule_bases[department])
                for department in self.kb.departments
            },
            "rule_survival_rate": (
                sum(rule.survival_rate for rule in observed_rules) / len(observed_rules)
                if observed_rules
                else 0.0
            ),
            "rule_survival_by_department": {
                department: self._rule_survival(state.rule_bases[department])
                for department in self.kb.departments
            },
            "replay_episodes": state.replay_episodes,
            "replay_recovered": state.replay_recovered,
            "rule_candidates": sum(manager.rule_candidates for manager in state.managers.values()),
            "rules_accepted": sum(manager.rules_accepted for manager in state.managers.values()),
            "rules_discarded": sum(manager.rules_discarded for manager in state.managers.values()),
            "skill_count": sum(len(base) for base in state.skill_bases.values()),
        }

    @staticmethod
    def _rule_survival(base: ExperienceBase) -> float:
        rules = [rule for rule in base if rule.validations > 0]
        return sum(rule.survival_rate for rule in rules) / len(rules) if rules else 0.0

    @staticmethod
    def _dataset_signature(cohorts: Cohorts) -> str:
        payload = {
            "train": _cohort_hash(cohorts.train),
            "validation": _cohort_hash(cohorts.validation),
            "test": _cohort_hash(cohorts.test),
            "tags": cohorts.test_tags,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _summarize(reports: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        metric_names = (
            "diagnosis_accuracy",
            "department_accuracy",
            "consultation_trigger_rate",
            "consultation_gain",
            "average_steps",
            "average_exam_count",
            "case_memory_hits",
            "rule_memory_hits",
            "case_count",
            "rule_count",
            "rule_survival_rate",
            "rule_candidates",
            "rules_accepted",
            "skill_count",
        )
        for condition, runs in reports.items():
            metrics: dict[str, Any] = {}
            for metric in metric_names:
                values = [run["final"].get(metric) for run in runs]
                values = [float(value) for value in values if value is not None]
                metrics[metric] = {
                    "mean": statistics.fmean(values) if values else None,
                    "std": statistics.stdev(values) if len(values) > 1 else 0.0,
                    "values": values,
                }
            result[condition] = {
                "seeds": len(runs),
                "final": metrics,
                "test_memory_isolation": all(
                    run["test_memory_isolation"] for run in runs
                ),
            }
        return result


def plot_initial_experiment(result: dict[str, Any], path: str | Path) -> bool:
    """Plot mean held-out learning curves across seeds."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    figure, axis = plt.subplots(figsize=(8, 5))
    for condition, runs in result.get("reports", {}).items():
        if not runs:
            continue
        grouped = list(zip(*(run["checkpoints"] for run in runs)))
        x = [point[0]["patients_treated"] for point in grouped]
        y = [
            statistics.fmean(point["diagnosis_accuracy"] for point in group)
            for group in grouped
        ]
        axis.plot(
            x,
            y,
            marker="o",
            label=condition,
        )
    axis.set_xlabel("Patients treated per department")
    axis.set_ylabel("Held-out diagnosis accuracy")
    axis.set_title("Mechanism experiment learning curves")
    axis.grid(True, alpha=0.3)
    axis.legend(fontsize=8)
    figure.tight_layout()
    figure.savefig(path, dpi=140)
    plt.close(figure)
    return True


def save_experiment_result(
    result: dict[str, Any],
    out: str | Path,
    plot: str | Path | None = None,
) -> None:
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if plot is not None:
        plot_path = Path(plot)
        plot_path.parent.mkdir(parents=True, exist_ok=True)
        plot_initial_experiment(result, plot_path)


def run_initial_experiment(
    config: ExperimentConfig | None = None,
    out: str | Path | None = None,
    plot: str | Path | None = None,
) -> dict[str, Any]:
    result = ExperimentRunner(config=config).run()
    if out:
        save_experiment_result(result, out, plot)
    return result
