"""Development-only outcome validation for supported shifted proposals.

The function in this module is deliberately pure.  It does not read files,
execute candidates, inspect model text, or access official holdout data.
"""

from __future__ import annotations

import math
from typing import Any


MIN_IMPROVEMENT = 1e-5
MIN_VALIDATION_ROWS = 32
MIN_DOMAIN_FRACTION = 1.0
MAX_DOMAIN_HARM = 0.0


def _finite(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def decide_shift_outcome(
    *,
    evidence_status: str,
    shift_status: str,
    parent_nmse: float | None = None,
    candidate_nmse: float | None = None,
    n_rows: int = 0,
    min_improvement: float = MIN_IMPROVEMENT,
    min_rows: int = MIN_VALIDATION_ROWS,
) -> dict[str, Any]:
    """Return an auditable decision for one proposal.

    A shifted proposal is deployable only when evidence is ``supported`` and
    the candidate's development proxy NMSE improves by at least the fixed
    threshold.  All unavailable or invalid validations defer to the parent.
    """

    if evidence_status not in {"supported", "contradicted", "unknown"}:
        raise ValueError("unsupported evidence_status")
    if shift_status not in {"covered", "shifted"}:
        raise ValueError("unsupported shift_status")
    if not _finite(min_improvement) or float(min_improvement) < 0.0:
        raise ValueError("min_improvement must be finite and nonnegative")
    if isinstance(min_rows, bool) or not isinstance(min_rows, int) or min_rows < 1:
        raise ValueError("min_rows must be a positive integer")

    result: dict[str, Any] = {
        "evidence_status": evidence_status,
        "shift_status": shift_status,
        "threshold": float(min_improvement),
        "min_rows": min_rows,
        "parent_nmse": parent_nmse,
        "candidate_nmse": candidate_nmse,
        "delta_nmse": None,
        "decision": None,
        "final_action": "retain_parent",
        "validation_status": "not_required",
        "reason": None,
    }

    if evidence_status == "contradicted":
        result.update(decision="retain", reason="replacement_evidence_contradicted")
        return result
    if evidence_status == "unknown":
        result.update(decision="defer", reason="replacement_evidence_unknown")
        return result
    if shift_status == "covered":
        result.update(
            decision="allow",
            final_action="execute_candidate",
            reason="supported_and_covered",
        )
        return result

    if (
        isinstance(n_rows, bool)
        or not isinstance(n_rows, int)
        or n_rows < min_rows
        or not _finite(parent_nmse)
        or not _finite(candidate_nmse)
    ):
        result.update(
            decision="defer",
            validation_status="unavailable",
            reason="shift_outcome_validation_unavailable",
        )
        return result

    delta = float(candidate_nmse) - float(parent_nmse)
    result["delta_nmse"] = delta
    if delta <= -float(min_improvement):
        result.update(
            decision="allow_after_validation",
            final_action="execute_candidate",
            validation_status="passed",
            reason="shift_outcome_improved",
        )
    else:
        result.update(
            decision="retain",
            validation_status="failed",
            reason="shift_outcome_not_improved_enough",
        )
    return result


def decide_dual_outcome(
    *,
    evidence_status: str,
    shift_status: str,
    ordinary_parent_nmse: float | None = None,
    ordinary_candidate_nmse: float | None = None,
    ordinary_n_rows: int = 0,
    domain_blocks: list[dict[str, Any]] | None = None,
    min_improvement: float = MIN_IMPROVEMENT,
    min_rows: int = MIN_VALIDATION_ROWS,
    required_fraction: float = MIN_DOMAIN_FRACTION,
    max_domain_harm: float = MAX_DOMAIN_HARM,
) -> dict[str, Any]:
    """Apply the v04 ordinary-plus-natural-domain outcome gate.

    This is a pure, development-only policy.  For shifted, supported
    proposals the candidate must improve the ordinary outcome and every
    valid natural-domain block by the fixed improvement threshold.  The
    function never loads data or executes a candidate; callers must provide
    frozen block results and their provenance separately.
    """

    if evidence_status not in {"supported", "contradicted", "unknown"}:
        raise ValueError("unsupported evidence_status")
    if shift_status not in {"covered", "shifted"}:
        raise ValueError("unsupported shift_status")
    if not _finite(min_improvement) or float(min_improvement) < 0.0:
        raise ValueError("min_improvement must be finite and nonnegative")
    if isinstance(min_rows, bool) or not isinstance(min_rows, int) or min_rows < 1:
        raise ValueError("min_rows must be a positive integer")
    if (
        not _finite(required_fraction)
        or not 0.0 < float(required_fraction) <= 1.0
    ):
        raise ValueError("required_fraction must be in (0, 1]")
    if not _finite(max_domain_harm) or float(max_domain_harm) < 0.0:
        raise ValueError("max_domain_harm must be finite and nonnegative")

    blocks = list(domain_blocks or [])
    result: dict[str, Any] = {
        "evidence_status": evidence_status,
        "shift_status": shift_status,
        "threshold": float(min_improvement),
        "min_rows": min_rows,
        "required_domain_fraction": float(required_fraction),
        "max_domain_harm": float(max_domain_harm),
        "ordinary_parent_nmse": ordinary_parent_nmse,
        "ordinary_candidate_nmse": ordinary_candidate_nmse,
        "ordinary_n_rows": ordinary_n_rows,
        "ordinary_delta_nmse": None,
        "domain_block_count": len(blocks),
        "valid_domain_block_count": 0,
        "domain_improved_count": 0,
        "domain_improvement_fraction": None,
        "max_domain_delta_nmse": None,
        "domain_deltas_nmse": [],
        "decision": None,
        "final_action": "retain_parent",
        "validation_status": "not_required",
        "reason": None,
    }

    if evidence_status == "contradicted":
        result.update(decision="retain", reason="replacement_evidence_contradicted")
        return result
    if evidence_status == "unknown":
        result.update(decision="defer", reason="replacement_evidence_unknown")
        return result
    if shift_status == "covered":
        result.update(
            decision="allow",
            final_action="execute_candidate",
            reason="supported_and_covered",
        )
        return result

    if (
        isinstance(ordinary_n_rows, bool)
        or not isinstance(ordinary_n_rows, int)
        or ordinary_n_rows < min_rows
        or not _finite(ordinary_parent_nmse)
        or not _finite(ordinary_candidate_nmse)
        or not blocks
    ):
        result.update(
            decision="defer",
            validation_status="unavailable",
            reason="dual_outcome_validation_unavailable",
        )
        return result

    ordinary_delta = float(ordinary_candidate_nmse) - float(ordinary_parent_nmse)
    result["ordinary_delta_nmse"] = ordinary_delta

    deltas: list[float] = []
    for block in blocks:
        if not isinstance(block, dict):
            result.update(
                decision="defer",
                validation_status="unavailable",
                reason="dual_outcome_validation_unavailable",
            )
            return result
        n_rows = block.get("n_rows", 0)
        parent = block.get("parent_nmse")
        candidate = block.get("candidate_nmse")
        if (
            block.get("valid") is not True
            or isinstance(n_rows, bool)
            or not isinstance(n_rows, int)
            or n_rows < min_rows
            or not _finite(parent)
            or not _finite(candidate)
        ):
            result.update(
                decision="defer",
                validation_status="unavailable",
                reason="dual_outcome_validation_unavailable",
            )
            return result
        delta = float(candidate) - float(parent)
        deltas.append(delta)
        result["domain_deltas_nmse"].append({
            "block_id": block.get("block_id"),
            "n_rows": n_rows,
            "parent_nmse": float(parent),
            "candidate_nmse": float(candidate),
            "delta_nmse": delta,
            "improved": delta <= -float(min_improvement),
        })

    result["valid_domain_block_count"] = len(deltas)
    result["domain_improved_count"] = sum(
        delta <= -float(min_improvement) for delta in deltas
    )
    result["domain_improvement_fraction"] = (
        result["domain_improved_count"] / len(deltas)
    )
    result["max_domain_delta_nmse"] = max(deltas)

    ordinary_improved = ordinary_delta <= -float(min_improvement)
    domain_fraction_passed = (
        result["domain_improvement_fraction"] >= float(required_fraction)
    )
    domain_harm_passed = max(deltas) <= float(max_domain_harm)
    if ordinary_improved and domain_fraction_passed and domain_harm_passed:
        result.update(
            decision="allow_after_dual_validation",
            final_action="execute_candidate",
            validation_status="passed",
            reason="ordinary_and_natural_domain_outcomes_improved",
        )
    else:
        result.update(
            decision="retain",
            validation_status="failed",
            reason="ordinary_or_natural_domain_outcome_not_improved_enough",
        )
    return result
