"""Common pre-execution gate for no-check, sham-check and real-check arms.

The candidate is generated once and then passed through this gate under each
condition.  All arms use the same final rule: execute only when the edit-level
status is ``supported``.  No-check and sham are explicit controls that return
supported without inspecting the edit; the real arm receives the typed check
result from ``targeted_edit_check``.  This module never executes a candidate.
"""

from __future__ import annotations

from typing import Any

from .edit_evidence import attach_check, decide_from_check


VERSION = "edit-condition-gate-v0.1"
CONDITIONS = ("no_check", "sham_check", "real_check")


def apply_gate(
    edit: dict[str, Any],
    *,
    condition: str,
    check_id: str,
    real_status: str | None = None,
    scope: str = "development",
) -> dict[str, Any]:
    """Return an auditable pre-execution decision for one condition.

    ``no_check`` and ``sham_check`` deliberately do not read the edit or
    evidence.  They consume the same record shape and use a common final gate,
    which makes the later comparison about gating rather than output schema.
    ``real_check`` requires an explicit typed result; absence is an error so a
    failed checker cannot silently become permission to execute.
    """

    if condition not in CONDITIONS:
        raise ValueError("unknown edit condition")
    if edit.get("mode") == "keep":
        checked = attach_check(edit, check_id=check_id, status="unknown", scope=scope)
        provisional = decide_from_check(checked)
        return {
            "version": VERSION,
            "condition": condition,
            "check_reason": "no_edit",
            "check_applicability": "not_applicable",
            "checked_edit": checked,
            "decision": provisional,
            "final_action": "retain_parent",
            "common_gate": "execute_only_when_supported",
        }
    if condition == "real_check":
        if real_status is None:
            raise ValueError("real check status is required")
        status = real_status
        reason = "targeted_check"
    else:
        status = "supported"
        reason = "control_bypass" if condition == "no_check" else "uninformative_sham"
    checked = attach_check(edit, check_id=check_id, status=status, scope=scope)
    provisional = decide_from_check(checked)
    execute = provisional["decision"] == "allow_candidate"
    return {
        "version": VERSION,
        "condition": condition,
        "check_reason": reason,
        "checked_edit": checked,
        "decision": provisional,
        "final_action": "execute_candidate" if execute else "retain_parent",
        "common_gate": "execute_only_when_supported",
    }
