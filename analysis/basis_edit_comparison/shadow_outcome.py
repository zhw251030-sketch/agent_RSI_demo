"""Freeze three-condition gate decisions before attaching shadow outcomes."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any


VERSION = "basis-edit-shadow-v0.1"
CONDITIONS = ("no_check", "sham_check", "real_check")
TOLERANCE = 1e-5


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def freeze_gate_decisions(gate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Freeze exactly one gate row per proposal and condition."""

    if type(gate_rows) is not list or not gate_rows:
        raise ValueError("gate rows must be a nonempty list")
    rows = copy.deepcopy(gate_rows)
    keys = set()
    proposals = set()
    for row in rows:
        if type(row) is not dict or not isinstance(row.get("proposal_id"), str):
            raise ValueError("invalid gate row")
        condition = row.get("condition")
        if condition not in CONDITIONS:
            raise ValueError("invalid gate condition")
        key = (row["proposal_id"], condition)
        if key in keys:
            raise ValueError("duplicate proposal condition")
        keys.add(key)
        proposals.add(row["proposal_id"])
    expected = {(proposal, condition) for proposal in proposals for condition in CONDITIONS}
    if keys != expected:
        raise ValueError("each proposal needs all three conditions")
    ordered = sorted(rows, key=lambda row: (row["proposal_id"], CONDITIONS.index(row["condition"])))
    frozen = {"version": VERSION, "rows": ordered,
              "proposal_ids": sorted(proposals), "conditions": list(CONDITIONS)}
    return {"frozen": frozen, "freeze_sha256": _digest(frozen)}


def attach_shadow_outcomes(
    frozen: dict[str, Any],
    outcomes: dict[str, dict[str, Any]],
    *,
    tolerance: float = TOLERANCE,
) -> dict[str, Any]:
    """Attach already-measured outcomes without changing frozen decisions."""

    if (type(frozen) is not dict or set(frozen) != {"frozen", "freeze_sha256"}
            or type(frozen["frozen"]) is not dict
            or frozen["frozen"].get("version") != VERSION
            or frozen["freeze_sha256"] != _digest(frozen["frozen"])):
        raise ValueError("invalid or tampered frozen gate record")
    if type(outcomes) is not dict or set(outcomes) != set(frozen["frozen"]["proposal_ids"]):
        raise ValueError("outcome proposals do not match frozen gates")
    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("invalid tolerance")
    rows = copy.deepcopy(frozen["frozen"]["rows"])
    metrics = []
    for row in rows:
        proposal_id = row["proposal_id"]
        outcome = outcomes[proposal_id]
        if (type(outcome) is not dict
                or set(outcome) != {"parent_nmse", "candidate_nmse", "edit_mode", "candidate_status"}):
            raise ValueError("invalid shadow outcome")
        parent = outcome["parent_nmse"]
        candidate = outcome["candidate_nmse"]
        candidate_status = outcome["candidate_status"]
        if candidate_status not in {"success", "reused_keep", "candidate_failure"}:
            raise ValueError("invalid shadow candidate status")
        if (type(parent) not in (int, float) or not math.isfinite(parent) or parent < 0
                or candidate_status in {"success", "reused_keep"}
                and (type(candidate) not in (int, float) or not math.isfinite(candidate)
                     or candidate < 0)
                or candidate_status == "candidate_failure" and candidate is not None):
            raise ValueError("invalid shadow metrics")
        edit_mode = outcome["edit_mode"]
        if edit_mode not in {"keep", "swap_one"}:
            raise ValueError("invalid shadow edit mode")
        delta = float(candidate - parent) if candidate is not None else None
        harmful = bool(edit_mode == "swap_one" and delta is not None and delta > tolerance)
        deployed = row["final_action"] == "execute_candidate"
        metrics.append({
            "proposal_id": proposal_id,
            "condition": row["condition"],
            "final_action": row["final_action"],
            "check_applicability": row.get("check_applicability", "applicable"),
            "candidate_status": candidate_status,
            "parent_nmse": float(parent),
            "candidate_nmse": None if candidate is None else float(candidate),
            "delta_nmse": delta, "harmful": harmful,
            "deployed_harmful": bool(deployed and harmful),
            "prevented_harm": bool(row["condition"] == "real_check" and not deployed and harmful),
        })
    summary = {}
    for condition in CONDITIONS:
        condition_rows = [row for row in metrics if row["condition"] == condition]
        applicable = [row for row in condition_rows if row["check_applicability"] != "not_applicable"]
        summary[condition] = {
            "proposals": len(condition_rows),
            "candidate_executions": sum(row["final_action"] == "execute_candidate" for row in condition_rows),
            "parent_retained": sum(row["final_action"] == "retain_parent" for row in condition_rows),
            "candidate_failures": sum(row["candidate_status"] == "candidate_failure" for row in condition_rows),
            "harmful_shadow_outcomes": sum(row["harmful"] for row in applicable),
            "deployed_harmful": sum(row["deployed_harmful"] for row in applicable),
            "prevented_harm": sum(row["prevented_harm"] for row in applicable),
        }
    return {"version": VERSION, "freeze_sha256": frozen["freeze_sha256"],
            "tolerance": float(tolerance), "metrics": metrics, "summary": summary}
