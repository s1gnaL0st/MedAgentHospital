"""Run the external medical MCQ benchmark with the configured LLM backend.

Requires ``.env`` with ``LLM_BACKEND=deepseek`` or a local vLLM server.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from medagent_hospital.benchmarks.mcq import (  # noqa: E402
    MCQBenchmark,
    load_mcq_dataset,
)
from medagent_hospital.config import PROJECT_ROOT as ROOT  # noqa: E402
from medagent_hospital.llm.base import build_llm_backend  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        default=ROOT / "data" / "benchmarks" / "medical_mcq_sample.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "experiments" / "medical_mcq_benchmark.json",
    )
    args = parser.parse_args()

    backend = build_llm_backend()
    if backend.name == "rule":
        print("当前为规则后端，无法作答医学多选题；请先配置 LLM_BACKEND=deepseek 或 huatuo。")
        return 1

    items = load_mcq_dataset(args.data)
    report = MCQBenchmark(items).run(backend)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"backend: {backend.name}")
    print(f"accuracy: {report['accuracy']:.2%} ({report['correct']}/{report['total']})")
    for source, stats in report["by_source"].items():
        print(f"- {source}: {stats['accuracy']:.2%} ({stats['correct']}/{stats['total']})")
    print("saved:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
