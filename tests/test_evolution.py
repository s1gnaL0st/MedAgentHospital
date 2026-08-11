"""D7: evolution training loop, ablations and learning curve tests."""

from medagent_hospital.agents.registry import DoctorRegistry
from medagent_hospital.agents.nurse import NurseAgent
from medagent_hospital.agents.patient import PatientAgent
from medagent_hospital.knowledge import load_knowledge_base
from medagent_hospital.memory.case_base import MedicalCase, MedicalCaseBase
from medagent_hospital.memory.experience_base import ExperienceBase, ExperienceRule
from medagent_hospital.simulacrum.evolution import (
    EvolutionConfig,
    EvolutionTrainer,
    run_evolution_experiment,
)
from medagent_hospital.simulacrum.models import HospitalState
from medagent_hospital.simulacrum.patient_generator import PatientGenerator
from medagent_hospital.simulacrum.runtime import HospitalRuntime


def test_doctor_registry_routing() -> None:
    kb = load_knowledge_base()
    registry = DoctorRegistry(kb, reasoner="rule")
    runtime = HospitalRuntime(
        patient_agent=PatientAgent(),
        nurse_agent=NurseAgent(kb=kb),
        doctor_agent=registry,
    )
    patient = PatientGenerator(kb, seed=1).generate(disease_id="DERM-001")
    context = runtime.run_episode(patient)
    assert context.current_state == HospitalState.END
    doctor_names = {
        entry["agent"]
        for entry in context.transcript
        if entry["action"] in {"order_exams", "diagnose", "prescribe"}
    }
    assert "皮肤科医生" in doctor_names


def test_case_base_dedup() -> None:
    base = MedicalCaseBase(dedup_threshold=0.9)
    case = MedicalCase(
        patient={"symptoms": ["发热", "咳嗽"], "exam_names": ["胸部CT"]},
        diagnosis="肺炎",
        diagnosis_id="RESP-001",
        treatment="抗生素",
    )
    assert base.add(case) is True
    assert (
        base.add(
            MedicalCase(
                patient={"symptoms": ["发热", "咳嗽"], "exam_names": ["胸部CT"]},
                diagnosis="肺炎",
                diagnosis_id="RESP-001",
                treatment="抗生素",
            )
        )
        is False
    )
    assert len(base) == 1
    assert base.skipped == 1


def test_rule_lifecycle() -> None:
    base = ExperienceBase()
    bad = ExperienceRule(
        trigger=("发热",), rule="bad", favor="X", validations=5, successes=1
    )
    good = ExperienceRule(
        trigger=("胸痛",), rule="good", favor="Y", validations=5, successes=4, strength=0.6
    )
    base.add(bad)
    base.add(good)
    removed = base.prune(min_survival_rate=0.4, min_validations=3)
    assert removed == 1
    assert len(base) == 1
    changed = base.adjust_strengths(min_validations=3)
    assert changed == 1
    assert good.strength > 0.6


def small_config() -> EvolutionConfig:
    return EvolutionConfig(
        patients_per_department=24,
        test_patients_per_department=8,
        validation_patients_per_disease=1,
        batch_size=8,
        seed=7,
        symptom_omission_probability=0.35,
        distractor_probability=0.5,
        exam_hit_rate=0.6,
        use_case_dedup=True,
        use_rule_lifecycle=True,
        use_failure_replay=True,
        confusable_weight=0.8,
        confusable_true_ratio=0.5,
    )


def test_evolution_trainer_smoke() -> None:
    kb = load_knowledge_base()
    trainer = EvolutionTrainer(kb, small_config())
    report = trainer.train("D")
    assert report["patients_treated"][0] == 0
    assert len(report["accuracy"]) == 4  # baseline + 3 rounds
    assert report["final_accuracy"] >= 0.4
    assert sum(report["case_counts"].values()) > 0
    assert report["rule_counts"]


def test_evolution_comparison_smoke() -> None:
    results = run_evolution_experiment(small_config(), variants=("A", "B", "C", "D"))
    assert set(results) == {"A", "B", "C", "D"}
    for report in results.values():
        assert report["patients_treated"][0] == 0
        assert len(report["accuracy"]) == 4


def test_evolution_plot(tmp_path) -> None:
    results = run_evolution_experiment(
        small_config(), variants=("A", "D"), out_dir=tmp_path
    )
    assert (tmp_path / "evolution_metrics.json").exists()
    assert (tmp_path / "evolution_comparison.png").exists()
    assert set(results) == {"A", "D"}
