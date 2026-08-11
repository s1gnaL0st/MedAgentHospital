"""API smoke tests for the demo dashboard."""

from medagent_hospital.web.server import _kb_overview, _run_episode


def test_kb_overview() -> None:
    overview = _kb_overview()
    assert overview["total_diseases"] == 48
    assert len(overview["departments"]) == 6
    assert all(item["disease_count"] == 8 for item in overview["departments"])


def test_run_episode() -> None:
    result = _run_episode(
        {"department": "皮肤科", "disease_id": "DERM-001", "seed": 1}
    )
    assert result["transcript"]
    assert result["diagnosis"]["disease_id"] == "DERM-001"
    assert result["correct"] is True
    assert result["patient"]["symptoms"]
