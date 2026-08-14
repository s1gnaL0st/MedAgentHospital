"""External medical multiple-choice benchmark.

Unlike the in-simulation virtual test set, questions come from a static JSON
dataset and no candidate diseases are injected into the prompt, so results
measure the model's own medical knowledge instead of closed-loop selection.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from medagent_hospital.llm.base import LLMBackend

SYSTEM_PROMPT = (
    "你是一名医学考试作答者。根据题目选择最合适的选项，"
    "只输出选项字母（A、B、C、D 中的一个），不要输出其他内容。"
)

_ANSWER_PATTERN = re.compile(r"(?i)(?:答案\s*[::：]\s*)?\b([A-D])\b")


@dataclass(frozen=True)
class MCQItem:
    id: str
    question: str
    options: dict[str, str]
    answer: str
    source: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MCQItem":
        return cls(
            id=str(raw["id"]),
            question=str(raw["question"]),
            options={str(k): str(v) for k, v in raw["options"].items()},
            answer=str(raw["answer"]).strip().upper(),
            source=str(raw.get("source", "")),
        )

    def prompt(self) -> str:
        option_lines = "\n".join(
            f"{letter}. {text}" for letter, text in self.options.items()
        )
        return f"题目：{self.question}\n{option_lines}"


def extract_answer(text: str) -> str:
    """Extract the answer letter from model output; returns '' if none found."""
    if not text:
        return ""
    first_line = text.strip().splitlines()[0]
    match = re.search(r"(?i)(?:答案\s*[::：]\s*)?\b([A-D])\b", first_line)
    if match:
        return match.group(1).upper()
    match = _ANSWER_PATTERN.search(text)
    return match.group(1).upper() if match else ""


def load_mcq_dataset(path: str | Path) -> list[MCQItem]:
    with open(path, encoding="utf-8") as file:
        raw = json.load(file)
    if not isinstance(raw, list):
        raise ValueError("MCQ 数据集必须是 JSON 数组")
    return [MCQItem.from_dict(item) for item in raw]


@dataclass
class MCQBenchmark:
    items: list[MCQItem]

    def run(
        self,
        backend: LLMBackend,
        *,
        temperature: float = 0.0,
        max_tokens: int = 24,
    ) -> dict[str, Any]:
        correct = 0
        details: list[dict[str, Any]] = []
        by_source: dict[str, dict[str, int]] = defaultdict(
            lambda: {"total": 0, "correct": 0}
        )
        for item in self.items:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": item.prompt()},
            ]
            raw = backend.chat(
                messages, temperature=temperature, max_tokens=max_tokens
            )
            predicted = extract_answer(raw)
            is_correct = bool(predicted) and predicted == item.answer
            correct += int(is_correct)
            details.append(
                {
                    "id": item.id,
                    "answer": item.answer,
                    "predicted": predicted,
                    "correct": is_correct,
                    "source": item.source,
                    "raw": raw[:200],
                }
            )
            source_stats = by_source[item.source]
            source_stats["total"] += 1
            source_stats["correct"] += int(is_correct)

        total = len(self.items)
        return {
            "total": total,
            "correct": correct,
            "accuracy": correct / total if total else 0.0,
            "details": details,
            "by_source": {
                source: {
                    "total": stats["total"],
                    "correct": stats["correct"],
                    "accuracy": (
                        stats["correct"] / stats["total"]
                        if stats["total"]
                        else 0.0
                    ),
                }
                for source, stats in by_source.items()
            },
        }
