"""Run the paired multi-agent / memory / evolution mechanism experiment.

Examples:
    D:\\python\\python.exe scripts\\run_initial_experiment.py
    D:\\python\\python.exe scripts\\run_initial_experiment.py --seeds 42 --patients-per-department 8 --test-per-department 8
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from medagent_hospital.config import PROJECT_ROOT as ROOT  # noqa: E402
from medagent_hospital.simulacrum.experiment import (  # noqa: E402
    CONDITIONS,
    ExperimentConfig,
    ExperimentRunner,
    save_experiment_result,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 2024, 7])
    parser.add_argument("--patients-per-department", type=int, default=168)
    parser.add_argument("--validation-per-disease", type=int, default=8)
    parser.add_argument("--test-per-department", type=int, default=168)
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--reasoner", choices=["rule", "llm"], default="rule")
    parser.add_argument(
        "--conditions",
        nargs="+",
        choices=tuple(CONDITIONS),
        default=tuple(CONDITIONS),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "experiments" / "initial_experiment.json",
    )
    parser.add_argument(
        "--plot",
        type=Path,
        default=ROOT / "data" / "experiments" / "initial_learning_curves.png",
    )
    args = parser.parse_args()

    config = ExperimentConfig(
        reasoner=args.reasoner,
        seeds=tuple(args.seeds),
        patients_per_department=args.patients_per_department,
        validation_patients_per_disease=args.validation_per_disease,
        test_patients_per_department=args.test_per_department,
        batch_size=args.batch_size,
    )
    result = ExperimentRunner(config=config).run(tuple(args.conditions))
    save_experiment_result(result, args.out, args.plot)

    print("condition\taccuracy(mean+-std)\tconsultation rate\taverage steps")
    for condition in args.conditions:
        final = result["summary"][condition]["final"]
        accuracy = final["diagnosis_accuracy"]
        consultation = final["consultation_trigger_rate"]
        steps = final["average_steps"]
        print(
            f"{condition}\t{accuracy['mean']:.3f}+/-{accuracy['std']:.3f}\t"
            f"{consultation['mean']:.3f}\t{steps['mean']:.2f}"
        )
    print("test memory isolation:", all(
        report["test_memory_isolation"]
        for report in result["summary"].values()
    ))
    print("saved:", args.out)
    print("plot:", args.plot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
