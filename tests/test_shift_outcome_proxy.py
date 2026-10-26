import pytest

from analysis.replacement_evidence.shift_gate import build_profile
from scripts.build_shift_aware_outcome_proxy_v03 import build_task_proxy_fixture


def test_proxy_fixture_keeps_transformed_inputs_aligned_with_outcome_targets():
    headers = ["strain", "temp", "stress"]
    rows = [
        {"strain": "0.1", "temp": "0.2", "stress": "1.0"},
        {"strain": "0.3", "temp": "0.4", "stress": "2.0"},
        {"strain": "0.5", "temp": "0.6", "stress": "3.0"},
    ]
    profile = build_profile([[0.1, 0.2], [0.3, 0.4]], ["strain", "temp"])
    result = build_task_proxy_fixture(
        "stressstrain", headers, rows, [0, 2], profile,
    )
    assert result["fixture_id"] == "stressstrain-condition-collapse-v01"
    assert result["X"] == [[0.1, profile["stats"]["temp"]["mean"]], [0.5, profile["stats"]["temp"]["mean"]]]
    assert result["y"] == [1.0, 3.0]
    assert result["source_split"] == "outcome_dev_v2"
    assert result["target_source"] == "outcome_dev_v2 target rows"
    assert result["not_benchmark"] is True


def test_proxy_fixture_is_deterministic():
    headers = ["x", "v", "a"]
    rows = [{"x": "0", "v": "1", "a": "2"}, {"x": "1", "v": "2", "a": "3"}]
    profile = build_profile([[0.0, 1.0], [1.0, 2.0]], ["x", "v"])
    first = build_task_proxy_fixture("oscillator1", headers, rows, [0, 1], profile)
    second = build_task_proxy_fixture("oscillator1", headers, rows, [0, 1], profile)
    assert first == second
    assert len(first["source_row_indices_sha256"]) == 64
    assert len(first["fixture_sha256"]) == 64


def test_proxy_fixture_rejects_official_test_source():
    with pytest.raises(ValueError, match="official test"):
        build_task_proxy_fixture(
            "bactgrow", ["b", "s", "temp", "pH", "db"], [], [], {},
            source_split="official_test_ood",
        )
