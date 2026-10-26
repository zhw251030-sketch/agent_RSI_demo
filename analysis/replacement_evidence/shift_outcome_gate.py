"""Development-only outcome validation for supported shifted proposals.

The function in this module is deliberately pure.  It does not read files,
execute candidates, inspect model text, or access official holdout data.
"""

from __future__ import annotations

import math
from typing import Any


MIN_IMPROVEMENT = 1e-5
MIN_VALIDATION_ROWS = 32


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
