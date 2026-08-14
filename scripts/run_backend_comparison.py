"""Multi-seed comparison of LLM backends on the virtual test set.

Usage:
    python scripts/run_backend_comparison.py --backends rule llm --seeds 42 2024 7

LLM runs reuse the configured backend from ``.env`` (DeepSeek / HuatuoGPT / vLLM).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from medagent_hospital.config import PROJECT_ROOT as ROOT  # noqa: E402
from medagent_hospital.knowledge import load_knowledge_base  # noqa: E402
from medagent_hospital.llm.base import build_llm_backend  # noqa: E402
from medagent_hospital.simulacrum.evolution import (  # noqa: E402
    EvolutionConfig,
    EvolutionTrainer,
    apply_variant,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backends",
        nargs="+",
        default=["rule"],
        choices=["rule", "llm"],
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 2024, 7])
    parser.add_argument("--patients-per-department", type=int, default=12)
    parser.add_argument("--test-per-department", type=int, default=8)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "experiments" / "backend_comparison.json",
    )
    args = parser.parse_args()

    if "llm" in args.backends and build_llm_backend().name == "rule":
        print("警告：未检测到 LLM 配置，llm 组将退化为规则模式。")

    kb = load_knowledge_base()
    summary: dict[str, dict] = {}
    for backend in args.backends:
        runs = []
        for seed in args.seeds:
            config = EvolutionConfig(
                reasoner=backend,
                patients_per_department=args.patients_per_department,
                test_patients_per_department=args.test_per_department,
                validation_patients_per_disease=0,
                batch_size=4,
                seed=seed,
            )
            start = time.time()
            report = EvolutionTrainer(kb, apply_variant(config, "D")).train("D")
            run = {
                "seed": seed,
                "elapsed_seconds": round(time.time() - start, 1),
                "initial_accuracy": report["initial_accuracy"],
                "final_accuracy": report["final_accuracy"],
                "cases": sum(report["case_counts"].values()),
                "rules": sum(report["rule_counts"].values()),
            }
            runs.append(run)
            print(
                f"[{backend} seed={seed}] "
                f"{run['initial_accuracy']:.3f} -> {run['final_accuracy']:.3f}"
            )

        initials = [run["initial_accuracy"] for run in runs]
        finals = [run["final_accuracy"] for run in runs]
        summary[backend] = {
            "runs": runs,
            "initial_mean": statistics.mean(initials),
            "initial_std": statistics.stdev(initials) if len(initials) > 1 else 0.0,
            "final_mean": statistics.mean(finals),
            "final_std": statistics.stdev(finals) if len(finals) > 1 else 0.0,
        }
        print(
            f"[{backend}] initial "
            f"{summary[backend]['initial_mean']:.3f}±{summary[backend]['initial_std']:.3f} "
            f"final "
            f"{summary[backend]['final_mean']:.3f}±{summary[backend]['final_std']:.3f}"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("saved:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
