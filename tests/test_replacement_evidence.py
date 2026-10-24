import math

import pytest

from analysis.basis_edit_comparison.replacement_evidence import (
    compute_replacement_evidence,
    standardized_contribution,
)


def binding(**overrides):
    value = {
        "task_id": "bactgrow",
        "split_id": "bactgrow-train-fit-check-v01",
        "check_data_sha256": "a" * 64,
        "parent_source_sha256": "b" * 64,
        "common_source_sha256": "c" * 64,
        "added_source_sha256": "d" * 64,
        "removed_feature_id": "m_1_0_0",
        "added_feature_id": "m_0_1_1",
        "parent_feature_ids": ["m_0_0_0", "m_1_0_0"],
        "fit_protocol_sha256": "e" * 64,
        "metric_scope": "check_dev_nmse_population_variance",
    }
    value.update(overrides)
    return value


def test_boundary_ratio_one_is_supported():
    result = compute_replacement_evidence(
        common_nmse=1.0,
        parent_nmse=0.5,
        added_nmse=0.5,
        fit_statuses={"parent": "success", "common": "success", "added": "success"},
        binding=binding(),
    )
    assert result["status"] == "supported"
    assert result["ratio"] == pytest.approx(1.0)
    assert result["decision_reason"] == "replacement_restores_required_fraction"


@pytest.mark.parametrize(
    ("added_nmse", "reason"),
    [(0.9, "insufficient_replacement"), (1.1, "non_improving_replacement")],
)
def test_insufficient_or_harmful_replacement_is_contradicted(added_nmse, reason):
    result = compute_replacement_evidence(
        common_nmse=1.0,
        parent_nmse=0.5,
        added_nmse=added_nmse,
        fit_statuses={"parent": "success", "common": "success", "added": "success"},
        binding=binding(),
    )
    assert result["status"] == "contradicted"
    assert result["decision_reason"] == reason


@pytest.mark.parametrize(
    ("parent_nmse", "reason"),
    [(1.0, "nonpositive_deletion_loss"), (1.0 - 5e-9, "tiny_deletion_loss")],
)
def test_uninformative_deletion_is_unknown(parent_nmse, reason):
    result = compute_replacement_evidence(
        common_nmse=1.0,
        parent_nmse=parent_nmse,
        added_nmse=0.5,
        fit_statuses={"parent": "success", "common": "success", "added": "success"},
        binding=binding(),
    )
    assert result["status"] == "unknown"
    assert result["ratio"] is None
    assert result["decision_reason"] == reason


def test_fit_failure_and_nonfinite_inputs_are_unknown_or_invalid():
    failed = compute_replacement_evidence(
        common_nmse=1.0,
        parent_nmse=0.5,
        added_nmse=0.5,
        fit_statuses={"parent": "failed", "common": "success", "added": "success"},
        binding=binding(),
    )
    assert failed["status"] == "unknown"
    assert failed["decision_reason"] == "fit_failure"

    invalid = compute_replacement_evidence(
        common_nmse=math.nan,
        parent_nmse=0.5,
        added_nmse=0.5,
        fit_statuses={"parent": "success", "common": "success", "added": "success"},
        binding=binding(),
    )
    assert invalid["status"] == "invalid"
    assert invalid["decision_reason"] == "nonfinite_nmse"


def test_target_variance_zero_is_unknown():
    result = compute_replacement_evidence(
        common_nmse=1.0,
        parent_nmse=0.5,
        added_nmse=0.5,
        fit_statuses={"parent": "success", "common": "success", "added": "success"},
        target_variance=0.0,
        binding=binding(),
    )
    assert result["status"] == "unknown"
    assert result["decision_reason"] == "unavailable_check_metric"


def test_binding_mismatch_is_rejected_before_scoring():
    with pytest.raises(ValueError, match="binding"):
        compute_replacement_evidence(
            common_nmse=1.0,
            parent_nmse=0.5,
            added_nmse=0.5,
            fit_statuses={"parent": "success", "common": "success", "added": "success"},
            binding=binding(check_data_sha256="not-a-sha256"),
        )


def test_standardized_contribution_uses_feature_scale_not_raw_coefficient():
    result = standardized_contribution(
        coefficient=2.0,
        feature_values=[1.0, 3.0, 5.0],
    )
    assert result["status"] == "available"
    assert result["feature_std"] == pytest.approx(math.sqrt(8 / 3))
    assert result["standardized_contribution"] == pytest.approx(2 * math.sqrt(8 / 3))


def test_constant_feature_does_not_gate_main_evidence():
    result = standardized_contribution(coefficient=2.0, feature_values=[4.0, 4.0])
    assert result == {
        "status": "unavailable",
        "reason": "constant_or_near_constant_feature",
        "feature_std": 0.0,
        "standardized_contribution": None,
    }
