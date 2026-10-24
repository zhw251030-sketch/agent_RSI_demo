"""Pure numeric evidence for a feature replacement on a held-out dev split.

This module deliberately does not fit models or call an agent.  The caller must
fit ``parent``, ``common`` and ``added`` on the same ``fit_dev`` rows, then
provide their fixed-parameter scores on the same ``check_dev`` rows.  Keeping
the scoring contract separate from the existing fit-and-score executor prevents
the check split from being used to refit a candidate.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Iterable, Mapping
from typing import Any


VERSION = "replacement-evidence-v0.1"
METRIC_SCOPE = "check_dev_nmse_population_variance"
DEFAULT_TOLERANCE = 1e-5
DEFAULT_DENOMINATOR_FLOOR = 1e-8
DEFAULT_RATIO_THRESHOLD = 1.0
_SHA256_HEX = set("0123456789abcdefABCDEF")
_BINDING_FIELDS = {
    "task_id",
    "split_id",
    "check_data_sha256",
    "parent_source_sha256",
    "common_source_sha256",
    "added_source_sha256",
    "removed_feature_id",
    "added_feature_id",
    "parent_feature_ids",
    "fit_protocol_sha256",
    "metric_scope",
}


def _number(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a real number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _hash(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in _SHA256_HEX for ch in value):
        raise ValueError(f"binding field {name} must be a SHA-256 hex digest")
    return value.lower()


def _validate_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(binding, Mapping):
        raise ValueError("binding must be a mapping")
    missing = _BINDING_FIELDS - set(binding)
    if missing:
        raise ValueError(f"binding missing fields: {sorted(missing)}")
    if binding["metric_scope"] != METRIC_SCOPE:
        raise ValueError("binding metric_scope is incompatible with replacement evidence")
    for field in (
        "check_data_sha256",
        "parent_source_sha256",
        "common_source_sha256",
        "added_source_sha256",
        "fit_protocol_sha256",
    ):
        _hash(binding[field], name=field)
    for field in ("task_id", "split_id", "removed_feature_id", "added_feature_id"):
        if not isinstance(binding[field], str) or not binding[field]:
            raise ValueError(f"binding field {field} must be a nonempty string")
    features = binding["parent_feature_ids"]
    if (not isinstance(features, list) or not features
            or any(not isinstance(feature, str) or not feature for feature in features)
            or len(set(features)) != len(features)):
        raise ValueError("binding parent_feature_ids must be a unique nonempty list")
    if binding["removed_feature_id"] not in features:
        raise ValueError("binding removed_feature_id is not in parent_feature_ids")
    if binding["added_feature_id"] in features:
        raise ValueError("binding added_feature_id must not already be in parent_feature_ids")
    return copy.deepcopy(dict(binding))


def _base_result(
    *,
    binding: dict[str, Any],
    common_nmse: float | None,
    parent_nmse: float | None,
    added_nmse: float | None,
    tolerance: float,
    denominator_floor: float,
    ratio_threshold: float,
    status: str,
    reason: str,
    deletion_loss: float | None = None,
    restoration_gain: float | None = None,
    ratio: float | None = None,
) -> dict[str, Any]:
    return {
        "schema": VERSION,
        "status": status,
        "decision_reason": reason,
        "binding": binding,
        "metric_scope": METRIC_SCOPE,
        "common_nmse": common_nmse,
        "parent_nmse": parent_nmse,
        "added_nmse": added_nmse,
        "deletion_loss": deletion_loss,
        "restoration_gain": restoration_gain,
        "ratio": ratio,
        "tolerance": float(tolerance),
        "denominator_floor": float(denominator_floor),
        "ratio_threshold": float(ratio_threshold),
    }


def compute_replacement_evidence(
    *,
    common_nmse: Any,
    parent_nmse: Any,
    added_nmse: Any,
    fit_statuses: Mapping[str, Any],
    binding: Mapping[str, Any],
    target_variance: Any | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
    denominator_floor: float = DEFAULT_DENOMINATOR_FLOOR,
    ratio_threshold: float = DEFAULT_RATIO_THRESHOLD,
) -> dict[str, Any]:
    """Classify evidence that an added feature replaces a removed feature.

    ``I_minus = common_nmse - parent_nmse`` measures the observed loss from
    deletion.  ``I_plus = common_nmse - added_nmse`` measures recovery after
    adding the proposed replacement.  Only ``I_minus > floor``, ``I_plus >
    tolerance`` and ``I_plus / I_minus >= threshold`` is supported.  A weak or
    nonpositive deletion effect is ``unknown`` rather than a failed edit.
    """

    checked_binding = _validate_binding(binding)
    try:
        tol = _number(tolerance, name="tolerance")
        floor = _number(denominator_floor, name="denominator_floor")
        threshold = _number(ratio_threshold, name="ratio_threshold")
    except ValueError as exc:
        raise ValueError(f"invalid evidence thresholds: {exc}") from exc
    if tol < 0 or floor < 0 or threshold < 0:
        raise ValueError("evidence thresholds must be nonnegative")
    if not isinstance(fit_statuses, Mapping) or set(fit_statuses) != {"parent", "common", "added"}:
        raise ValueError("fit_statuses must contain parent, common and added")

    metrics: dict[str, float] = {}
    try:
        for label, value in (("common", common_nmse), ("parent", parent_nmse), ("added", added_nmse)):
            metric = _number(value, name=f"{label}_nmse")
            if metric < 0:
                return _base_result(
                    binding=checked_binding,
                    common_nmse=None,
                    parent_nmse=None,
                    added_nmse=None,
                    tolerance=tol,
                    denominator_floor=floor,
                    ratio_threshold=threshold,
                    status="invalid",
                    reason="negative_nmse",
                )
            metrics[label] = metric
    except ValueError as exc:
        reason = "nonfinite_nmse" if "finite" in str(exc) else "invalid_nmse"
        return _base_result(
            binding=checked_binding,
            common_nmse=None,
            parent_nmse=None,
            added_nmse=None,
            tolerance=tol,
            denominator_floor=floor,
            ratio_threshold=threshold,
            status="invalid",
            reason=reason,
        )

    if target_variance is not None:
        try:
            variance = _number(target_variance, name="target_variance")
        except ValueError as exc:
            return _base_result(
                binding=checked_binding,
                common_nmse=metrics["common"],
                parent_nmse=metrics["parent"],
                added_nmse=metrics["added"],
                tolerance=tol,
                denominator_floor=floor,
                ratio_threshold=threshold,
                status="unknown",
                reason="unavailable_check_metric",
            )
        if variance <= 0:
            return _base_result(
                binding=checked_binding,
                common_nmse=metrics["common"],
                parent_nmse=metrics["parent"],
                added_nmse=metrics["added"],
                tolerance=tol,
                denominator_floor=floor,
                ratio_threshold=threshold,
                status="unknown",
                reason="unavailable_check_metric",
            )

    if any(fit_statuses[label] != "success" for label in ("parent", "common", "added")):
        return _base_result(
            binding=checked_binding,
            common_nmse=metrics["common"],
            parent_nmse=metrics["parent"],
            added_nmse=metrics["added"],
            tolerance=tol,
            denominator_floor=floor,
            ratio_threshold=threshold,
            status="unknown",
            reason="fit_failure",
        )

    deletion_loss = metrics["common"] - metrics["parent"]
    restoration_gain = metrics["common"] - metrics["added"]
    if deletion_loss <= 0:
        return _base_result(
            binding=checked_binding,
            common_nmse=metrics["common"],
            parent_nmse=metrics["parent"],
            added_nmse=metrics["added"],
            tolerance=tol,
            denominator_floor=floor,
            ratio_threshold=threshold,
            status="unknown",
            reason="nonpositive_deletion_loss",
            deletion_loss=deletion_loss,
            restoration_gain=restoration_gain,
        )
    if deletion_loss <= floor:
        return _base_result(
            binding=checked_binding,
            common_nmse=metrics["common"],
            parent_nmse=metrics["parent"],
            added_nmse=metrics["added"],
            tolerance=tol,
            denominator_floor=floor,
            ratio_threshold=threshold,
            status="unknown",
            reason="tiny_deletion_loss",
            deletion_loss=deletion_loss,
            restoration_gain=restoration_gain,
        )

    ratio = restoration_gain / deletion_loss
    if not math.isfinite(ratio):
        return _base_result(
            binding=checked_binding,
            common_nmse=metrics["common"],
            parent_nmse=metrics["parent"],
            added_nmse=metrics["added"],
            tolerance=tol,
            denominator_floor=floor,
            ratio_threshold=threshold,
            status="unknown",
            reason="nonfinite_ratio",
            deletion_loss=deletion_loss,
            restoration_gain=restoration_gain,
        )
    if restoration_gain <= tol:
        reason = "non_improving_replacement" if restoration_gain < 0 else "insufficient_replacement"
        return _base_result(
            binding=checked_binding,
            common_nmse=metrics["common"],
            parent_nmse=metrics["parent"],
            added_nmse=metrics["added"],
            tolerance=tol,
            denominator_floor=floor,
            ratio_threshold=threshold,
            status="contradicted",
            reason=reason,
            deletion_loss=deletion_loss,
            restoration_gain=restoration_gain,
            ratio=ratio,
        )
    status = "supported" if ratio >= threshold else "contradicted"
    reason = "replacement_restores_required_fraction" if status == "supported" else "insufficient_replacement"
    return _base_result(
        binding=checked_binding,
        common_nmse=metrics["common"],
        parent_nmse=metrics["parent"],
        added_nmse=metrics["added"],
        tolerance=tol,
        denominator_floor=floor,
        ratio_threshold=threshold,
        status=status,
        reason=reason,
        deletion_loss=deletion_loss,
        restoration_gain=restoration_gain,
        ratio=ratio,
    )


def standardized_contribution(
    *,
    coefficient: Any,
    feature_values: Iterable[Any],
    near_constant_floor: float = 1e-12,
) -> dict[str, Any]:
    """Return a scale-aware diagnostic; this never changes gate status."""

    coef = _number(coefficient, name="coefficient")
    floor = _number(near_constant_floor, name="near_constant_floor")
    if floor < 0:
        raise ValueError("near_constant_floor must be nonnegative")
    if isinstance(feature_values, (str, bytes)):
        raise ValueError("feature_values must be numeric iterable")
    try:
        values = [_number(value, name="feature_value") for value in feature_values]
    except TypeError as exc:
        raise ValueError("feature_values must be numeric iterable") from exc
    if not values:
        raise ValueError("feature_values must be nonempty")
    mean = math.fsum(values) / len(values)
    variance = math.fsum((value - mean) ** 2 for value in values) / len(values)
    std = math.sqrt(variance)
    if std <= floor:
        return {
            "status": "unavailable",
            "reason": "constant_or_near_constant_feature",
            "feature_std": std,
            "standardized_contribution": None,
        }
    return {
        "status": "available",
        "reason": None,
        "feature_std": std,
        "standardized_contribution": abs(coef) * std,
    }
