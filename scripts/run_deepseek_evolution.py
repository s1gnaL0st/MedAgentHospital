"""Run a small DeepSeek evolution experiment.

Requires ``.env`` with ``LLM_BACKEND=deepseek`` and ``DEEPSEEK_API_KEY``.
Training is intentionally small to control API cost.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from medagent_hospital.knowledge import load_knowledge_base  # noqa: E402
from medagent_hospital.llm.base import build_llm_backend  # noqa: E402
from medagent_hospital.simulacrum.evolution import (  # noqa: E402
    EvolutionConfig,
    EvolutionTrainer,
    apply_variant,
    plot_evolution_comparison,
)


def main() -> int:
    backend = build_llm_backend()
    if backend.name == "rule":
        print("未检测到 DeepSeek API key，请先配置 .env")
        return 1

    config = EvolutionConfig(
        reasoner="llm",
        patients_per_department=12,
        test_patients_per_department=8,
        validation_patients_per_disease=0,
        batch_size=4,
        seed=42,
    )
    kb = load_knowledge_base()
    start = time.time()
    report = EvolutionTrainer(kb, apply_variant(config, "D")).train("D")
    elapsed = round(time.time() - start, 1)

    out_dir = PROJECT_ROOT / "data" / "experiments"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "deepseek_evolution.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    plot_evolution_comparison({"D": report}, out_dir / "deepseek_evolution.png")

    print(f"elapsed: {elapsed}s")
    print("accuracy:", [round(value, 3) for value in report["accuracy"]])
    print("initial/final:", round(report["initial_accuracy"], 3), round(report["final_accuracy"], 3))
    print("cases:", sum(report["case_counts"].values()), "rules:", sum(report["rule_counts"].values()))
    print("saved:", out_dir / "deepseek_evolution.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
