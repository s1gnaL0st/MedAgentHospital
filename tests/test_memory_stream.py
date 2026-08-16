"""Memory stream scoring tests: recency, importance and reinforcement."""

import time

from medagent_hospital.memory.case_base import MedicalCase, MedicalCaseBase

QUERY = {"symptoms": ["发热", "咳嗽"], "exam_names": []}
CASE = {
    "patient": {"symptoms": ["发热", "咳嗽"], "exam_names": []},
    "diagnosis": "测试诊断",
    "diagnosis_id": "TEST-001",
    "treatment": "对症治疗",
}


def test_recency_decay_prefers_newer() -> None:
    base = MedicalCaseBase(decay_rate=1.0)
    now = time.time()
    old = MedicalCase(**CASE, created_at=now - 3)
    new = MedicalCase(**CASE, created_at=now - 1)
    base.add(old)
    base.add(new)
    hits = base.retrieve(QUERY, top_k=2, now=now)
    assert hits[0].case is new
    assert hits[0].score > hits[1].score


def test_importance_ranks_higher() -> None:
    base = MedicalCaseBase(decay_rate=0.0, reinforcement_factor=0.0)
    now = time.time()
    low = MedicalCase(**CASE, created_at=now, importance=1.0)
    high = MedicalCase(**CASE, created_at=now, importance=2.0)
    base.add(low)
    base.add(high)
    hits = base.retrieve(QUERY, top_k=2, now=now)
    assert hits[0].case is high


def test_retrieval_reinforces_memory() -> None:
    base = MedicalCaseBase(decay_rate=0.0)
    now = time.time()
    case = MedicalCase(**CASE, created_at=now)
    base.add(case)
    first = base.retrieve(QUERY, top_k=1, now=now)[0]
    assert case.retrieval_count == 1
    second = base.retrieve(QUERY, top_k=1, now=now)[0]
    assert second.score > first.score
    assert case.retrieval_count == 2


def test_recency_uses_last_access() -> None:
    base = MedicalCaseBase(decay_rate=1.0)
    now = time.time()
    first = MedicalCase(**CASE, created_at=now)
    second = MedicalCase(**CASE, created_at=now)
    base.add(first)
    base.add(second)
    # Retrieve first once so its last access time becomes fresh.
    first_hits = base.retrieve(QUERY, top_k=1, now=now)
    assert first_hits[0].case is first
    later = now + 2
    later_hits = base.retrieve(QUERY, top_k=2, now=later)
    assert later_hits[0].case is first
    assert later_hits[0].score > later_hits[1].score
