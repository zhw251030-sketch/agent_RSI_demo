"""Freeze and score replacement-round gates under protocol condition names."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any


VERSION = "replacement-shadow-outcome-v0.1"
CONDITIONS = ("no_check", "sham_check", "replacement_check")
TOLERANCE = 1e-5


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                     sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def freeze_gate_decisions(gate_rows: list[dict[str, Any]]) -> dict[str, Any]:
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
            raise ValueError("invalid replacement condition")
        key = (row["proposal_id"], condition)
        if key in keys:
            raise ValueError("duplicate proposal condition")
        keys.add(key)
        proposals.add(row["proposal_id"])
    expected = {(proposal, condition) for proposal in proposals for condition in CONDITIONS}
    if keys != expected:
        raise ValueError("each proposal needs all three replacement conditions")
    ordered = sorted(rows, key=lambda row: (row["proposal_id"], CONDITIONS.index(row["condition"])))
    frozen = {"version": VERSION, "rows": ordered,
              "proposal_ids": sorted(proposals), "conditions": list(CONDITIONS)}
    return {"frozen": frozen, "freeze_sha256": _digest(frozen)}


def attach_shadow_outcomes(frozen: dict[str, Any], outcomes: dict[str, dict[str, Any]],
                           *, tolerance: float = TOLERANCE) -> dict[str, Any]:
    if (type(frozen) is not dict or set(frozen) != {"frozen", "freeze_sha256"}
            or frozen["frozen"].get("version") != VERSION
            or frozen["freeze_sha256"] != _digest(frozen["frozen"])):
        raise ValueError("invalid or tampered replacement gates")
    if set(outcomes) != set(frozen["frozen"]["proposal_ids"]):
        raise ValueError("outcome proposals do not match frozen gates")
    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("invalid harmful tolerance")
    metrics = []
    for row in frozen["frozen"]["rows"]:
        outcome = outcomes[row["proposal_id"]]
        if type(outcome) is not dict or set(outcome) != {"parent_nmse", "candidate_nmse", "edit_mode", "candidate_status"}:
            raise ValueError("invalid outcome shadow record")
        parent = outcome["parent_nmse"]
        candidate = outcome["candidate_nmse"]
        status = outcome["candidate_status"]
        if status not in {"success", "reused_keep", "candidate_failure"}:
            raise ValueError("invalid candidate outcome status")
        if type(parent) not in (int, float) or not math.isfinite(parent) or parent < 0:
            raise ValueError("invalid parent outcome")
        if status in {"success", "reused_keep"} and (type(candidate) not in (int, float)
                or not math.isfinite(candidate) or candidate < 0):
            raise ValueError("invalid candidate outcome")
        if status == "candidate_failure" and candidate is not None:
            raise ValueError("failed candidate must not have a score")
        if outcome["edit_mode"] not in {"keep", "swap_one"}:
            raise ValueError("invalid edit mode")
        delta = None if candidate is None else float(candidate - parent)
        applicable = row.get("check_applicability", "applicable") != "not_applicable"
        harmful = bool(applicable and outcome["edit_mode"] == "swap_one" and delta is not None and delta > tolerance)
        deployed = row["final_action"] == "execute_candidate"
        metrics.append({
            "proposal_id": row["proposal_id"], "condition": row["condition"],
            "final_action": row["final_action"],
            "check_applicability": row.get("check_applicability", "applicable"),
            "candidate_status": status, "parent_nmse": float(parent),
            "candidate_nmse": None if candidate is None else float(candidate),
            "delta_nmse": delta, "harmful": harmful,
            "deployed_harmful": bool(deployed and harmful),
            "prevented_harm": bool(row["condition"] == "replacement_check" and not deployed and harmful),
        })
    summary = {}
    for condition in CONDITIONS:
        rows = [item for item in metrics if item["condition"] == condition]
        applicable = [item for item in rows if item["check_applicability"] != "not_applicable"]
        summary[condition] = {
            "proposals": len(rows),
            "candidate_executions": sum(item["final_action"] == "execute_candidate" for item in rows),
            "parent_retained": sum(item["final_action"] == "retain_parent" for item in rows),
            "candidate_failures": sum(item["candidate_status"] == "candidate_failure" for item in rows),
            "harmful_shadow_outcomes": sum(item["harmful"] for item in applicable),
            "deployed_harmful": sum(item["deployed_harmful"] for item in applicable),
            "prevented_harm": sum(item["prevented_harm"] for item in applicable),
        }
    return {"version": VERSION, "freeze_sha256": frozen["freeze_sha256"],
            "tolerance": float(tolerance), "metrics": metrics, "summary": summary}

