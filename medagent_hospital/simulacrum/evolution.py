"""D7: evolution training loop, evaluations, learning curves and ablations."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from medagent_hospital.agents.nurse import NurseAgent
from medagent_hospital.agents.patient import PatientAgent
from medagent_hospital.agents.registry import DoctorRegistry
from medagent_hospital.config import PROJECT_ROOT
from medagent_hospital.knowledge import KnowledgeBase, load_knowledge_base
from medagent_hospital.memory.case_base import MedicalCaseBase
from medagent_hospital.memory.experience_base import ExperienceBase
from medagent_hospital.simulacrum.memory_manager import MemoryManager
from medagent_hospital.simulacrum.models import PatientRecord
from medagent_hospital.simulacrum.patient_generator import PatientGenerator
from medagent_hospital.simulacrum.runtime import HospitalRuntime


@dataclass
class EvolutionConfig:
    reasoner: str = "rule"
    patients_per_department: int = 500
    test_patients_per_department: int = 100
    validation_patients_per_disease: int = 2
    batch_size: int = 50
    replay_every_rounds: int = 1
    replay_buffer_size: int = 50
    seed: int = 42
    symptom_omission_probability: float = 0.35
    distractor_probability: float = 0.5
    exam_hit_rate: float = 0.6
    dedup_threshold: float = 0.9
    use_case_dedup: bool = True
    use_rule_lifecycle: bool = True
    lifecycle_every_rounds: int = 1
    min_survival_rate: float = 0.4
    min_validations: int = 3
    use_failure_replay: bool = True
    curriculum_weight: float = 2.0
    confusable_weight: float = 0.8
    confusable_true_ratio: float = 0.5
    case_weight: float = 1.5
    rule_strength: float = 0.6
    top_k_cases: int = 3
    top_k_rules: int = 4
    use_curriculum: bool = True


# Disease pairs with heavily overlapping symptoms; used to make evolution non-trivial.
CONFUSABLE_GROUPS: dict[str, list[tuple[str, ...]]] = {
    "心内科": [("CARD-001", "CARD-002"), ("CARD-006", "CARD-004")],
    "呼吸科": [
        ("RESP-002", "RESP-003"),
        ("RESP-001", "RESP-004"),
        ("RESP-005", "RESP-006"),
    ],
    "消化科": [
        ("GI-001", "GI-002"),
        ("GI-002", "GI-008"),
        ("GI-006", "GI-007"),
    ],
    "神经内科": [
        ("NEURO-001", "NEURO-002"),
        ("NEURO-002", "NEURO-003"),
        ("NEURO-007", "NEURO-001"),
    ],
    "内分泌科": [("ENDO-001", "ENDO-002"), ("ENDO-003", "ENDO-004")],
    "皮肤科": [("DERM-001", "DERM-008"), ("DERM-002", "DERM-006")],
}


def apply_variant(config: EvolutionConfig, variant: str) -> EvolutionConfig:
    """Map ablation labels to config flags."""
    cfg = replace(config)
    if variant == "A":
        cfg.use_case_dedup = False
        cfg.use_rule_lifecycle = False
        cfg.use_failure_replay = False
    elif variant == "B":
        cfg.use_case_dedup = True
        cfg.use_rule_lifecycle = False
        cfg.use_failure_replay = False
    elif variant == "C":
        cfg.use_case_dedup = True
        cfg.use_rule_lifecycle = True
        cfg.use_failure_replay = False
    elif variant == "D":
        cfg.use_case_dedup = True
        cfg.use_rule_lifecycle = True
        cfg.use_failure_replay = True
        cfg.use_curriculum = True
    if variant != "D":
        cfg.use_curriculum = False
    return cfg


class EvolutionTrainer:
    """Reasoner-agnostic evolution loop with per-department doctor memories."""

    def __init__(
        self,
        kb: KnowledgeBase,
        config: EvolutionConfig | None = None,
        db_agent: Any | None = None,
    ) -> None:
        self.kb = kb
        self.config = config or EvolutionConfig()
        self.db_agent = db_agent

    def train(self, variant: str = "D", return_doctors: bool = False):
        cfg = self.config
        kb = self.kb
        rng = random.Random(cfg.seed)
        if self.db_agent:
            self.db_agent.ensure_session(
                self._memory_session_id(variant),
                {"type": "training", "variant": variant, "seed": cfg.seed},
            )
            for department in kb.departments:
                self.db_agent.register_agent(
                    self._memory_agent_id(variant, department),
                    "doctor",
                    f"{department}训练医生",
                    department,
                )

        doctors = DoctorRegistry(
            kb,
            reasoner=cfg.reasoner,
            case_weight=cfg.case_weight,
            top_k_cases=cfg.top_k_cases,
            top_k_rules=cfg.top_k_rules,
        )
        case_bases = {
            department: MedicalCaseBase(
                dedup_threshold=cfg.dedup_threshold if cfg.use_case_dedup else 0.0
            )
            for department in kb.departments
        }
        experience_bases = {
            department: ExperienceBase() for department in kb.departments
        }
        for department in kb.departments:
            doctors[department].case_base = case_bases[department]
            doctors[department].experience_base = experience_bases[department]

        validation_patients = self._build_validation_sets()
        test_sets = self._build_test_sets()
        managers = {
            department: MemoryManager(
                kb,
                case_base=case_bases[department],
                experience_base=experience_bases[department],
                validation_patients=validation_patients[department],
                rule_strength=cfg.rule_strength,
                reasoner=cfg.reasoner,
                db_agent=self.db_agent,
                memory_agent_id=self._memory_agent_id(variant, department),
                memory_session_id=self._memory_session_id(variant),
                department=department,
            )
            for department in kb.departments
        }
        for manager in managers.values():
            manager.load_persisted()
        replay_buffers: dict[str, list] = {
            department: [] for department in kb.departments
        }
        error_rates: dict[str, int] = {}

        rounds = max(1, cfg.patients_per_department // cfg.batch_size)
        points = [(0, self._evaluate_all(doctors, test_sets))]
        patients_treated = 0

        for round_index in range(rounds):
            difficulty = (round_index + 1) / rounds if cfg.use_curriculum else 1.0
            for department in kb.departments:
                batch = self._next_batch(
                    department, cfg.batch_size, rng, error_rates, difficulty
                )
                runtime = HospitalRuntime(
                    patient_agent=PatientAgent(),
                    nurse_agent=NurseAgent(kb=kb),
                    doctor_agent=doctors[department],
                )
                for patient in batch:
                    context = runtime.run_episode(patient)
                    managers[department].update(context, patient)
                    patients_treated += 1
                    if context.diagnosis_id != patient.ground_truth_disease_id:
                        disease_id = patient.ground_truth_disease_id
                        error_rates[disease_id] = error_rates.get(disease_id, 0) + 1
                        replay_buffers[department].append(patient)

                if (
                    cfg.use_failure_replay
                    and replay_buffers[department]
                    and (round_index + 1) % max(1, cfg.replay_every_rounds) == 0
                ):
                    replay_buffers[department] = self._replay(
                        department,
                        doctors[department],
                        managers[department],
                        replay_buffers[department],
                    )

                if (
                    cfg.use_rule_lifecycle
                    and (round_index + 1) % max(1, cfg.lifecycle_every_rounds) == 0
                ):
                    experience_bases[department].prune(
                        cfg.min_survival_rate, cfg.min_validations
                    )
                    experience_bases[department].adjust_strengths(cfg.min_validations)
                    managers[department].persist_all()

            points.append(
                (patients_treated, self._evaluate_all(doctors, test_sets))
            )

        report = {
            "variant": variant,
            "patients_treated": [treated for treated, _ in points],
            "accuracy": [accuracy for _, accuracy in points],
            "initial_accuracy": points[0][1],
            "final_accuracy": points[-1][1],
            "total_patients_treated": patients_treated,
            "case_counts": {
                department: len(case_bases[department])
                for department in kb.departments
            },
            "case_skipped": {
                department: case_bases[department].skipped
                for department in kb.departments
            },
            "rule_counts": {
                department: len(experience_bases[department])
                for department in kb.departments
            },
            "rule_survival": {
                department: self._average_survival(experience_bases[department])
                for department in kb.departments
            },
        }
        if return_doctors:
            return report, doctors
        return report

    def _memory_session_id(self, variant: str) -> str:
        return f"training-{variant}-{self.config.seed}"

    def _memory_agent_id(self, variant: str, department: str) -> str:
        index = self.kb.departments.index(department) + 1
        return f"doctor-{variant.lower()}-{index:02d}"

    def _build_validation_sets(self) -> dict[str, list]:
        sets: dict[str, list] = {}
        for index, department in enumerate(self.kb.departments):
            generator = self._make_generator(seed=self.config.seed * 31 + index)
            patients = []
            for disease in self.kb.by_department(department):
                for _ in range(self.config.validation_patients_per_disease):
                    patients.append(generator.generate(disease_id=disease.id))
            sets[department] = patients
        return sets

    def _build_test_sets(self) -> dict[str, list]:
        sets: dict[str, list] = {}
        for index, department in enumerate(self.kb.departments):
            generator = self._make_generator(seed=self.config.seed * 101 + index)
            rng = random.Random(self.config.seed * 101 + index)
            patients = []
            for _ in range(self.config.test_patients_per_department):
                disease_id, group = self._choose_disease(department, rng, {})
                patient = generator.generate(disease_id=disease_id)
                if group:
                    patient = self._mix_symptoms(patient, group, rng)
                patients.append(patient)
            sets[department] = patients
        return sets

    def _make_generator(self, seed: int, difficulty: float = 1.0) -> PatientGenerator:
        return PatientGenerator(
            self.kb,
            seed=seed,
            distractor_probability=self.config.distractor_probability * difficulty,
            symptom_omission_probability=self.config.symptom_omission_probability * difficulty,
            exam_hit_rate_override=0.85 + (self.config.exam_hit_rate - 0.85) * difficulty,
        )

    def _next_batch(
        self,
        department: str,
        size: int,
        rng: random.Random,
        error_rates: dict,
        difficulty: float,
    ) -> list:
        patients = []
        for _ in range(size):
            disease_id, group = self._choose_disease(
                department,
                rng,
                error_rates,
                self.config.confusable_weight * difficulty,
            )
            generator = self._make_generator(
                seed=rng.randint(0, 2**31 - 1), difficulty=difficulty
            )
            patient = generator.generate(disease_id=disease_id)
            if group:
                patient = self._mix_symptoms(patient, group, rng)
            patients.append(patient)
        return patients

    def _choose_disease(
        self,
        department: str,
        rng: random.Random,
        error_rates: dict,
        confusable_weight: float | None = None,
    ) -> tuple[str, tuple[str, ...] | None]:
        weight = (
            self.config.confusable_weight
            if confusable_weight is None
            else confusable_weight
        )
        if rng.random() < weight:
            groups = CONFUSABLE_GROUPS.get(department, [])
            if groups:
                group = rng.choice(groups)
                return rng.choice(group), group
        diseases = self.kb.by_department(department)
        weights = [
            1.0 + self.config.curriculum_weight * error_rates.get(disease.id, 0)
            for disease in diseases
        ]
        return rng.choices(diseases, weights=weights, k=1)[0].id, None

    def _mix_symptoms(
        self,
        patient: PatientRecord,
        group: tuple[str, ...],
        rng: random.Random,
    ) -> PatientRecord:
        """Mix symptoms from a confusable group, leaning toward the true disease."""
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
                        other_weights[symptom] = max(other_weights.get(symptom, 0.0), weight)

        true_pool = list(true_weights)
        other_pool = list(other_weights)
        count = rng.randint(3, min(5, max(3, len(true_pool) + len(other_pool))))
        true_count = max(1, round(count * self.config.confusable_true_ratio))
        symptoms = rng.choices(
            true_pool, weights=[true_weights[symptom] for symptom in true_pool], k=true_count
        )
        if other_pool:
            other_count = max(1, count - true_count)
            symptoms += rng.choices(
                other_pool,
                weights=[other_weights[symptom] for symptom in other_pool],
                k=other_count,
            )
        symptoms = list(dict.fromkeys(symptoms))
        if self.config.symptom_omission_probability > 0 and len(symptoms) > 2:
            kept = [
                symptom
                for symptom in symptoms
                if rng.random() >= self.config.symptom_omission_probability
            ]
            if len(kept) < 2:
                ranked = sorted(true_pool + other_pool, key=lambda s: true_weights.get(s, other_weights.get(s, 0.0)), reverse=True)
                for symptom in ranked:
                    if symptom not in kept:
                        kept.append(symptom)
                    if len(kept) >= 2:
                        break
            symptoms = kept
        return PatientRecord(
            patient_id=patient.patient_id,
            name=patient.name,
            gender=patient.gender,
            age=patient.age,
            symptoms=symptoms,
            medical_history=patient.medical_history,
            risk_factors=patient.risk_factors,
            exam_results=patient.exam_results,
            ground_truth_disease_id=patient.ground_truth_disease_id,
            ground_truth_disease_name=patient.ground_truth_disease_name,
        )

    def _replay(self, department: str, doctor, manager, buffer: list) -> list:
        runtime = HospitalRuntime(
            patient_agent=PatientAgent(),
            nurse_agent=NurseAgent(kb=self.kb),
            doctor_agent=doctor,
        )
        still_wrong = []
        for patient in buffer:
            context = runtime.run_episode(patient)
            manager.update(context, patient)
            if context.diagnosis_id != patient.ground_truth_disease_id:
                still_wrong.append(patient)
        return still_wrong[: self.config.replay_buffer_size]

    def _evaluate_all(self, doctors: DoctorRegistry, test_sets: dict) -> float:
        total = 0
        correct = 0
        for department, doctor in doctors.items():
            runtime = HospitalRuntime(
                patient_agent=PatientAgent(),
                nurse_agent=NurseAgent(kb=self.kb),
                doctor_agent=doctor,
            )
            for patient in test_sets[department]:
                context = runtime.run_episode(patient)
                total += 1
                correct += int(context.diagnosis_id == patient.ground_truth_disease_id)
        return correct / total if total else 0.0

    @staticmethod
    def _average_survival(base: ExperienceBase) -> float:
        rules = [rule for rule in base if rule.validations > 0]
        if not rules:
            return 0.0
        return sum(rule.survival_rate for rule in rules) / len(rules)


def run_evolution_experiment(
    config: EvolutionConfig | None = None,
    variants: tuple[str, ...] = ("A", "B", "C", "D"),
    out_dir: str | Path | None = None,
) -> dict:
    kb = load_knowledge_base()
    base_config = config or EvolutionConfig()
    results: dict[str, dict] = {}
    for variant in variants:
        trainer = EvolutionTrainer(kb, apply_variant(base_config, variant))
        results[variant] = trainer.train(variant)

    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "evolution_metrics.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        plot_evolution_comparison(results, out_dir / "evolution_comparison.png")
    return results


def plot_evolution_comparison(results: dict, path: str | Path) -> bool:
    """Save an accuracy-vs-patients learning curve for each ablation variant."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    figure, axis = plt.subplots(figsize=(7, 5))
    for variant, report in results.items():
        axis.plot(
            report["patients_treated"],
            report["accuracy"],
            marker="o",
            label=f"Variant {variant}",
        )
    axis.set_xlabel("Patients Treated")
    axis.set_ylabel("Test Accuracy")
    axis.set_title("Evolution Learning Curves")
    axis.legend()
    axis.grid(True, alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)
    return True


if __name__ == "__main__":
    experiment_dir = PROJECT_ROOT / "data" / "experiments"
    experiment = run_evolution_experiment(out_dir=experiment_dir)
    for variant, report in experiment.items():
        print(
            f"{variant}: {report['initial_accuracy']:.3f} -> {report['final_accuracy']:.3f}"
        )
