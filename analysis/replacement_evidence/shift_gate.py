"""Host-only input support diagnostics for the next replacement-gate round.

This module deliberately does not inspect targets, candidate scores, model
text, or official holdout files.  It builds a reference profile from a frozen
development input split and scores another input batch against that profile.
The result is a diagnostic state; integrating it into a real gate requires a
separate pre-registered development experiment.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Sequence


SCHEMA = "replacement-shift-profile-v0.1"
DEFAULT_LOWER_QUANTILE = 0.01
DEFAULT_UPPER_QUANTILE = 0.99
DEFAULT_OUTSIDE_RATE_MAX = 0.05
DEFAULT_MEAN_Z_MAX = 3.0
DEFAULT_VARIANCE_RATIO_MIN = 0.25
DEFAULT_VARIANCE_RATIO_MAX = 4.0


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _validate_matrix(rows: Sequence[Sequence[Any]], feature_names: Sequence[str]) -> list[list[float]]:
    if not feature_names or len(set(feature_names)) != len(feature_names):
        raise ValueError("feature_names must be nonempty and unique")
    if not rows:
        raise ValueError("rows must be nonempty")
    width = len(feature_names)
    result: list[list[float]] = []
    for row_index, row in enumerate(rows):
        if len(row) != width:
            raise ValueError(f"row {row_index} has wrong width")
        result.append([_finite(value, f"row {row_index}") for value in row])
    return result


def _quantile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot compute a quantile of an empty sequence")
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def build_profile(
    rows: Sequence[Sequence[Any]],
    feature_names: Sequence[str],
    *,
    lower_quantile: float = DEFAULT_LOWER_QUANTILE,
    upper_quantile: float = DEFAULT_UPPER_QUANTILE,
) -> dict[str, Any]:
    """Build a deterministic reference profile from input rows only."""

    if not 0.0 <= lower_quantile < upper_quantile <= 1.0:
        raise ValueError("quantiles must satisfy 0 <= lower < upper <= 1")
    matrix = _validate_matrix(rows, feature_names)
    stats: dict[str, dict[str, float]] = {}
    for column, name in enumerate(feature_names):
        values = [row[column] for row in matrix]
        mean = math.fsum(values) / len(values)
        variance = math.fsum((value - mean) ** 2 for value in values) / len(values)
        stats[str(name)] = {
            "mean": mean,
            "std": math.sqrt(variance),
            "lower": _quantile(values, lower_quantile),
            "upper": _quantile(values, upper_quantile),
        }
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "feature_names": list(feature_names),
        "n_rows": len(matrix),
        "quantiles": {"lower": lower_quantile, "upper": upper_quantile},
        "stats": stats,
    }
    body["profile_sha256"] = _sha256(_canonical(body))
    return body


def score_batch(
    profile: dict[str, Any],
    rows: Sequence[Sequence[Any]],
    *,
    outside_rate_max: float = DEFAULT_OUTSIDE_RATE_MAX,
    mean_z_max: float = DEFAULT_MEAN_Z_MAX,
    variance_ratio_min: float = DEFAULT_VARIANCE_RATIO_MIN,
    variance_ratio_max: float = DEFAULT_VARIANCE_RATIO_MAX,
) -> dict[str, Any]:
    """Score input coverage against a profile without using target values."""

    if profile.get("schema") != SCHEMA:
        raise ValueError("profile schema mismatch")
    if not 0.0 <= outside_rate_max <= 1.0:
        raise ValueError("outside_rate_max must be in [0, 1]")
    if mean_z_max <= 0.0 or variance_ratio_min < 0.0 or variance_ratio_max < variance_ratio_min:
        raise ValueError("invalid shift thresholds")
    feature_names = tuple(profile.get("feature_names", ()))
    matrix = _validate_matrix(rows, feature_names)
    per_feature: dict[str, dict[str, Any]] = {}
    shifted_features: list[str] = []
    for column, name in enumerate(feature_names):
        reference = profile["stats"][name]
        values = [row[column] for row in matrix]
        mean = math.fsum(values) / len(values)
        variance = math.fsum((value - mean) ** 2 for value in values) / len(values)
        std = math.sqrt(variance)
        reference_std = float(reference["std"])
        scale = max(reference_std, 1e-12)
        outside = sum(value < reference["lower"] or value > reference["upper"] for value in values)
        outside_rate = outside / len(values)
        mean_z = (mean - reference["mean"]) / scale
        reference_variance = reference_std ** 2
        if reference_variance <= 1e-24:
            # A constant reference feature is covered when the scored batch is
            # also constant; only newly appearing variation is a shift.
            variance_ratio = 1.0 if variance <= 1e-24 else math.inf
        else:
            variance_ratio = variance / reference_variance
        reasons: list[str] = []
        if outside_rate > outside_rate_max:
            reasons.append("outside_rate")
        if abs(mean_z) > mean_z_max:
            reasons.append("mean_z")
        if variance_ratio < variance_ratio_min or variance_ratio > variance_ratio_max:
            reasons.append("variance_ratio")
        if reasons:
            shifted_features.append(name)
        per_feature[name] = {
            "mean": mean,
            "std": std,
            "outside_rate": outside_rate,
            "mean_z": mean_z,
            "variance_ratio": variance_ratio,
            "shifted": bool(reasons),
            "reasons": reasons,
        }
    return {
        "schema": SCHEMA,
        "profile_sha256": profile.get("profile_sha256"),
        "n_rows": len(matrix),
        "status": "shifted" if shifted_features else "covered",
        "shifted_features": shifted_features,
        "per_feature": per_feature,
        "thresholds": {
            "outside_rate_max": outside_rate_max,
            "mean_z_max": mean_z_max,
            "variance_ratio_min": variance_ratio_min,
            "variance_ratio_max": variance_ratio_max,
        },
    }

