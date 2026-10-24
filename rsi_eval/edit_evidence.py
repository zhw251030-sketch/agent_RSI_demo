"""Bind a proposed structural edit to a check and its later outcome.

This is a task adapter for the existing ``evidence_checks`` contract.  It
does not run a check, execute a candidate, or promote a strategy.  Its purpose
is to make the unit of analysis explicit: one parent, one proposed edit, one
pre-edit check, and one observed parent/child outcome.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


VERSION = "edit-evidence-v0.1"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_STATUSES = {"supported", "contradicted", "unknown"}
_SCOPES = {"development", "selection"}


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise ValueError(f"invalid {name}")
    return value


def _hash(value: object, name: str) -> str:
    value = _text(value, name)
    if _HASH.fullmatch(value) is None:
        raise ValueError(f"invalid {name}")
    return value


def _features(value: object, name: str) -> list[str]:
    if type(value) is not list or not value or any(type(item) is not str or not item.strip()
                                                  or len(item) > 128 for item in value):
        raise ValueError(f"invalid {name}")
    if len(set(value)) != len(value):
        raise ValueError(f"duplicate features in {name}")
    return list(value)


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":"))


def _validate_edit(edit: object) -> dict[str, Any]:
    if type(edit) is not dict:
        raise ValueError("edit must be an object")
    expected = {
        "version", "edit_id", "task_id", "parent_source_sha256",
        "candidate_source_sha256", "parent_feature_ids", "candidate_feature_ids",
        "removed_feature_ids", "added_feature_ids", "mode", "canonical",
    }
    if set(edit) != expected or edit.get("version") != VERSION:
        raise ValueError("invalid edit schema")
    task_id = _text(edit["task_id"], "task_id")
    parent_source = _hash(edit["parent_source_sha256"], "parent_source_sha256")
    candidate_source = _hash(edit["candidate_source_sha256"], "candidate_source_sha256")
    parent = _features(edit["parent_feature_ids"], "parent_feature_ids")
    candidate = _features(edit["candidate_feature_ids"], "candidate_feature_ids")
    removed = sorted(set(parent) - set(candidate))
    added = sorted(set(candidate) - set(parent))
    if edit["removed_feature_ids"] != removed or edit["added_feature_ids"] != added:
        raise ValueError("edit delta does not match feature lists")
    mode = edit["mode"]
    if mode == "keep":
        if parent != candidate or removed or added:
            raise ValueError("keep edit has a structural delta")
    elif mode == "swap_one":
        if len(removed) != 1 or len(added) != 1:
            raise ValueError("swap_one requires exactly one removed and added feature")
    else:
        raise ValueError("unsupported edit mode")
    canonical_data = {
        "version": VERSION, "task_id": task_id,
        "parent_source_sha256": parent_source,
        "candidate_source_sha256": candidate_source,
        "parent_feature_ids": parent, "candidate_feature_ids": candidate,
        "removed_feature_ids": removed, "added_feature_ids": added, "mode": mode,
    }
    canonical = _canonical(canonical_data)
    if edit["canonical"] != canonical:
        raise ValueError("edit canonical form mismatch")
    if edit["edit_id"] != "edit_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]:
        raise ValueError("edit identifier mismatch")
    return dict(edit)


def build_edit(*, task_id: str, parent_source_sha256: str,
               candidate_source_sha256: str, parent_feature_ids: list[str],
               candidate_feature_ids: list[str]) -> dict[str, Any]:
    """Create a closed, content-addressed keep or one-swap edit record."""

    task_id = _text(task_id, "task_id")
    parent_source_sha256 = _hash(parent_source_sha256, "parent_source_sha256")
    candidate_source_sha256 = _hash(candidate_source_sha256, "candidate_source_sha256")
    parent_feature_ids = _features(parent_feature_ids, "parent_feature_ids")
    candidate_feature_ids = _features(candidate_feature_ids, "candidate_feature_ids")
    removed = sorted(set(parent_feature_ids) - set(candidate_feature_ids))
    added = sorted(set(candidate_feature_ids) - set(parent_feature_ids))
    if not (not removed and not added or len(removed) == 1 and len(added) == 1):
        raise ValueError("only keep or one feature swap is supported")
    mode = "keep" if not removed and not added else "swap_one"
    data = {
        "version": VERSION, "task_id": task_id,
        "parent_source_sha256": parent_source_sha256,
        "candidate_source_sha256": candidate_source_sha256,
        "parent_feature_ids": parent_feature_ids,
        "candidate_feature_ids": candidate_feature_ids,
        "removed_feature_ids": removed, "added_feature_ids": added, "mode": mode,
    }
    canonical = _canonical(data)
    return {**data, "edit_id": "edit_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16],
            "canonical": canonical}


def attach_check(edit: dict[str, Any], *, check_id: str, status: str,
                 scope: str) -> dict[str, Any]:
    """Bind one pre-edit check result to exactly one proposed edit.

    ``sealed`` is intentionally rejected: held-out evidence cannot influence a
    proposal or deployment decision. ``unknown`` is a valid result and must be
    carried forward instead of being treated as failure or success.
    """

    edit = _validate_edit(edit)
    check_id = _text(check_id, "check_id")
    if status not in _STATUSES:
        raise ValueError("invalid check status")
    if scope not in _SCOPES:
        raise ValueError("check scope cannot be sealed or unspecified")
    return {"version": VERSION, "edit_id": edit["edit_id"], "check_id": check_id,
            "check_status": status, "check_scope": scope, "edit": edit}


def decide_from_check(checked_edit: dict[str, Any]) -> dict[str, Any]:
    """Return a provisional decision; this is not the final deployment gate."""

    if type(checked_edit) is not dict or set(checked_edit) != {
            "version", "edit_id", "check_id", "check_status", "check_scope", "edit"}:
        raise ValueError("invalid checked edit")
    edit = _validate_edit(checked_edit["edit"])
    if checked_edit["version"] != VERSION or checked_edit["edit_id"] != edit["edit_id"]:
        raise ValueError("checked edit binding mismatch")
    if checked_edit["check_status"] not in _STATUSES or checked_edit["check_scope"] not in _SCOPES:
        raise ValueError("invalid checked edit status or scope")
    decision = {
        "supported": "allow_candidate",
        "contradicted": "retain_parent",
        "unknown": "defer",
    }[checked_edit["check_status"]]
    return {"version": VERSION, "edit_id": edit["edit_id"],
            "pre_edit_check_status": checked_edit["check_status"],
            "decision": decision, "decision_basis": "pre_edit_check"}


def classify_observed_outcome(checked_edit: dict[str, Any], *, parent_metric: float,
                              candidate_metric: float, direction: str,
                              tolerance: float) -> dict[str, Any]:
    """Attach the measured child outcome without rewriting the pre-edit decision."""

    provisional = decide_from_check(checked_edit)
    values = (parent_metric, candidate_metric, tolerance)
    if any(type(value) not in (int, float) or not __import__("math").isfinite(value)
           for value in values) or tolerance < 0:
        raise ValueError("metrics must be finite and tolerance nonnegative")
    if direction not in {"decrease", "increase"}:
        raise ValueError("invalid metric direction")
    delta = (parent_metric - candidate_metric
             if direction == "decrease" else candidate_metric - parent_metric)
    if delta > tolerance:
        status = "supported"
    elif delta < -tolerance:
        status = "contradicted"
    else:
        status = "unknown"
    return {
        **provisional, "pre_edit_decision": provisional["decision"],
        "posthoc_status": status, "metric_direction": direction,
        "parent_metric": float(parent_metric), "candidate_metric": float(candidate_metric),
        "delta": float(delta), "tolerance": float(tolerance),
    }
