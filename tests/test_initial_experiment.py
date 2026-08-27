"""Tests for the paired multi-agent mechanism experiment."""

from medagent_hospital.simulacrum.experiment import (
    CONDITIONS,
    ExperimentConfig,
    ExperimentRunner,
    plot_initial_experiment,
    save_experiment_result,
)


def small_config() -> ExperimentConfig:
    return ExperimentConfig(
        seeds=(42,),
        patients_per_department=4,
        validation_patients_per_disease=1,
        test_patients_per_department=4,
        batch_size=2,
    )


def test_initial_experiment_uses_paired_cohorts_and_read_only_test_set() -> None:
    result = ExperimentRunner(config=small_config()).run(("B0", "B1", "B4", "B5"))

    assert result["protocol"] == "mechanism-v1"
    assert result["cohort_manifest"]["seeds"]["42"]["counts"]["test"] == 24
    assert set(result["reports"]) == {"B0", "B1", "B4", "B5"}
    assert all(
        report["test_memory_isolation"]
        for reports in result["reports"].values()
        for report in reports
    )

    baseline = result["reports"]["B0"][0]
    evolution = result["reports"]["B4"][0]
    fixed = result["reports"]["B5"][0]
    assert baseline["final"]["case_count"] == 0
    assert evolution["final"]["case_count"] > 0
    assert fixed["final"]["consultation_trigger_rate"] == 1.0
    assert len(evolution["checkpoints"]) == 3
    assert result["summary"]["B4"]["test_memory_isolation"] is True


def test_initial_experiment_writes_json_and_plot(tmp_path) -> None:
    result = ExperimentRunner(config=small_config()).run(("B0", "B2"))
    output = tmp_path / "initial.json"
    plot = tmp_path / "initial.png"
    save_experiment_result(result, output, plot)

    assert output.exists()
    assert plot.exists()
    assert plot_initial_experiment(result, tmp_path / "repeat.png") is True
    assert set(CONDITIONS) == {"B0", "B1", "B2", "B3", "B4", "B5", "B6"}


def test_selective_evolution_reports_validation_checkpoint_selection() -> None:
    result = ExperimentRunner(config=small_config()).run(("B6",))
    report = result["reports"]["B6"][0]
    assert report["selected_patients_treated"] is not None
    assert report["selected_validation_score"] is not None
