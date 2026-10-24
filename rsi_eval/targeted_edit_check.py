"""Evaluate a typed parent claim and bind it to one proposed edit.

This is deliberately a thin adapter over ``EvidenceRegistry``.  A claim is
evidence for the proposed edit only when the host has written that meaning
into the claim and the typed check is supported.  Missing or malformed data
becomes ``unknown``; it never becomes permission to edit.  The adapter does
not infer causality from a coefficient or from natural-language feedback.
"""

from __future__ import annotations

from typing import Any

from .edit_evidence import attach_check, decide_from_check
from .evidence_ids import EvidenceRegistry


def evaluate_targeted_claim(
    edit: dict[str, Any],
    registry: EvidenceRegistry,
    claim: dict[str, Any],
    *,
    check_id: str,
    scope: str = "development",
) -> dict[str, Any]:
    """Check one visible parent claim and bind its result to ``edit``.

    ``supported`` and ``contradicted`` preserve the checker status.  The
    checker's ``unavailable`` and ``schema_invalid`` statuses are collapsed to
    an explicit edit-level ``unknown`` while the raw bounded result remains
    available for audit.
    """

    raw = registry.check_claim(claim)
    status = raw["status"] if raw["status"] in {"supported", "contradicted"} else "unknown"
    checked = attach_check(edit, check_id=check_id, status=status, scope=scope)
    return {
        "check_id": check_id,
        "raw_result": raw,
        "checked_edit": checked,
        "decision": decide_from_check(checked),
    }
