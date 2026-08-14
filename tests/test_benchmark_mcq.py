"""External MCQ benchmark tests."""

import json

from medagent_hospital.benchmarks.mcq import (
    MCQBenchmark,
    MCQItem,
    extract_answer,
    load_mcq_dataset,
)
from medagent_hospital.llm.base import LLMBackend


class SequenceBackend(LLMBackend):
    name = "sequence"

    def __init__(self, answers: list[str]) -> None:
        self.answers = answers
        self.calls = 0

    def chat(self, messages, **kwargs) -> str:
        answer = self.answers[self.calls % len(self.answers)]
        self.calls += 1
        return answer


def sample_items() -> list[MCQItem]:
    return [
        MCQItem(
            id="q1",
            question="成人 2 型糖尿病一线口服药？",
            options={"A": "二甲双胍", "B": "格列本脲"},
            answer="A",
            source="s1",
        ),
        MCQItem(
            id="q2",
            question="心梗标志物？",
            options={"A": "CK", "B": "肌钙蛋白"},
            answer="B",
            source="s1",
        ),
        MCQItem(
            id="q3",
            question="高血压标准？",
            options={"A": "140/90", "B": "130/85"},
            answer="A",
            source="s2",
        ),
    ]


def test_extract_answer_variants() -> None:
    assert extract_answer("B") == "B"
    assert extract_answer("答案：B") == "B"
    assert extract_answer("B. 肌钙蛋白") == "B"
    assert extract_answer("我觉得是 A。") == "A"
    assert extract_answer("无法确定") == ""


def test_benchmark_accuracy_and_source_breakdown() -> None:
    backend = SequenceBackend(["A", "B", "A"])
    report = MCQBenchmark(sample_items()).run(backend)
    assert report["correct"] == 3
    assert report["accuracy"] == 1.0
    assert report["by_source"]["s1"]["total"] == 2
    assert report["by_source"]["s2"]["accuracy"] == 1.0


def test_benchmark_counts_failures() -> None:
    backend = SequenceBackend(["A", "A", "B"])
    report = MCQBenchmark(sample_items()).run(backend)
    assert report["correct"] == 1
    assert abs(report["accuracy"] - 1 / 3) < 1e-9


def test_load_mcq_dataset(tmp_path) -> None:
    path = tmp_path / "questions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "q1",
                    "question": "题目",
                    "options": {"A": "甲", "B": "乙"},
                    "answer": "a",
                    "source": "s",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    items = load_mcq_dataset(path)
    assert len(items) == 1
    assert items[0].answer == "A"
