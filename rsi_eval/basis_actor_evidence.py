"""Host adapter for turning a basis submission into an edit-evidence record.

The frozen basis actor still exchanges only ``feature_ids``.  This module
adds the missing host-side binding after an accepted submission: the parent
and child source hashes, the concrete feature delta, the pre-edit check, and
an optional posthoc metric result.  It does not trust model prose, execute a
candidate, or decide final deployment.
"""

from __future__ import annotations

import copy
from typing import Any

from .edit_evidence import (
    attach_check,
    build_edit,
    classify_observed_outcome,
    decide_from_check,
)


VERSION = "basis-actor-evidence-v0.1"


def bind_accepted_submission(
    accepted: dict[str, Any],
    *,
    task_id: str,
    parent_source_sha256: str,
    candidate_source_sha256: str,
    parent_feature_ids: list[str],
    check_id: str,
    check_status: str,
    check_scope: str,
    parent_metric: float | None = None,
    candidate_metric: float | None = None,
    metric_direction: str = "decrease",
    tolerance: float = 1e-5,
) -> dict[str, Any]:
    """Bind one accepted host submission to an edit and check.

    ``accepted`` is intentionally limited to the business payload produced by
    the basis actor.  If a runner also supplies ``execution_payload``, its
    feature IDs must match exactly; host-authored fields are ignored by this
    adapter.  Supplying both metrics records the posthoc result separately.
    """

    if type(accepted) is not dict or accepted.get("status") != "accepted":
        raise ValueError("basis submission is not accepted")
    business = accepted.get("business")
    if type(business) is not dict or set(business) != {"feature_ids"}:
        raise ValueError("basis business must contain feature_ids only")
    candidate_feature_ids = business["feature_ids"]
    if "execution_payload" in accepted:
        payload = accepted["execution_payload"]
        if (type(payload) is not dict or payload.get("feature_ids") != candidate_feature_ids):
            raise ValueError("execution payload changed feature IDs")

    edit = build_edit(
        task_id=task_id,
        parent_source_sha256=parent_source_sha256,
        candidate_source_sha256=candidate_source_sha256,
        parent_feature_ids=parent_feature_ids,
        candidate_feature_ids=candidate_feature_ids,
    )
    checked = attach_check(
        edit,
        check_id=check_id,
        status=check_status,
        scope=check_scope,
    )
    decision = decide_from_check(checked)
    result: dict[str, Any] = {
        "version": VERSION,
        "edit": edit,
        "check": checked,
        "pre_edit_decision": copy.deepcopy(decision),
        "model_explanation_used": False,
    }
    supplied_metrics = (parent_metric is not None, candidate_metric is not None)
    if any(supplied_metrics) and not all(supplied_metrics):
        raise ValueError("parent and candidate metrics must be supplied together")
    if all(supplied_metrics):
        result["posthoc_outcome"] = classify_observed_outcome(
            checked,
            parent_metric=parent_metric,
            candidate_metric=candidate_metric,
            direction=metric_direction,
            tolerance=tolerance,
        )
    return result
