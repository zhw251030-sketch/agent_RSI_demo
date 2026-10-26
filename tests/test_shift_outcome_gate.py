import math

import pytest

from analysis.replacement_evidence.shift_outcome_gate import decide_shift_outcome


def test_supported_covered_keeps_existing_replacement_action_without_validation():
    result = decide_shift_outcome(
        evidence_status="supported", shift_status="covered", n_rows=0,
    )
    assert result["decision"] == "allow"
    assert result["final_action"] == "execute_candidate"
    assert result["validation_status"] == "not_required"


def test_supported_shifted_allows_candidate_after_clear_proxy_improvement():
    result = decide_shift_outcome(
        evidence_status="supported", shift_status="shifted",
        parent_nmse=1.0, candidate_nmse=0.8, n_rows=64,
    )
    assert result["decision"] == "allow_after_validation"
    assert result["final_action"] == "execute_candidate"
    assert result["validation_status"] == "passed"
    assert result["delta_nmse"] == pytest.approx(-0.2)


def test_supported_shifted_retains_candidate_when_proxy_is_harmful():
    result = decide_shift_outcome(
        evidence_status="supported", shift_status="shifted",
        parent_nmse=0.9, candidate_nmse=1.2, n_rows=64,
    )
    assert result["decision"] == "retain"
    assert result["final_action"] == "retain_parent"
    assert result["validation_status"] == "failed"
    assert result["delta_nmse"] == pytest.approx(0.3)


@pytest.mark.parametrize("evidence", ["contradicted", "unknown"])
def test_non_supported_evidence_never_deploys_candidate(evidence):
    result = decide_shift_outcome(
        evidence_status=evidence, shift_status="shifted",
        parent_nmse=1.0, candidate_nmse=0.5, n_rows=64,
    )
    assert result["final_action"] == "retain_parent"
    assert result["decision"] in {"retain", "defer"}
    assert result["validation_status"] == "not_required"


@pytest.mark.parametrize(
    "parent_nmse,candidate_nmse,n_rows",
    [(None, 0.5, 64), (1.0, None, 64), (math.nan, 0.5, 64), (1.0, math.inf, 64), (1.0, 0.5, 31)],
)
def test_invalid_shift_validation_defers_and_retains(parent_nmse, candidate_nmse, n_rows):
    result = decide_shift_outcome(
        evidence_status="supported", shift_status="shifted",
        parent_nmse=parent_nmse, candidate_nmse=candidate_nmse, n_rows=n_rows,
    )
    assert result["decision"] == "defer"
    assert result["final_action"] == "retain_parent"
    assert result["validation_status"] == "unavailable"


def test_small_improvement_below_fixed_threshold_is_retained():
    result = decide_shift_outcome(
        evidence_status="supported", shift_status="shifted",
        parent_nmse=1.0, candidate_nmse=1.0 - 0.5e-5, n_rows=64,
    )
    assert result["decision"] == "retain"
    assert result["final_action"] == "retain_parent"
    assert result["validation_status"] == "failed"
