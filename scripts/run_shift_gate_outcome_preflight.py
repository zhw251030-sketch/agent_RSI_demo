#!/usr/bin/env python3
"""Replay synthetic outcomes through the shift-aware action contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _synthetic_outcome(evidence_status: str, shift_status: str) -> tuple[float, float]:
    # The fixture is deliberately simple and declared here.  It tests counter
    # wiring, not a benchmark result: supported+covered is beneficial, while
    # the other three boundary states are harmful if executed.
    if evidence_status == "supported" and shift_status == "covered":
        return 1.0, 0.5
    return 1.0, 1.2


def _old_action(evidence_status: str) -> str:
    return "execute_candidate" if evidence_status == "supported" else "retain_parent"


def _new_action(evidence_status: str, shift_status: str) -> str:
    return "execute_candidate" if evidence_status == "supported" and shift_status == "covered" else "retain_parent"


def run(preflight_path: Path) -> dict:
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if preflight.get("status") != "passed_shift_action_preflight":
        raise ValueError("action preflight is incomplete")
    records = []
    for row in preflight["rows"]:
        parent, candidate = _synthetic_outcome(row["evidence_status"], row["shift_status"])
        harmful = candidate > parent + 1e-5
        beneficial = candidate < parent - 1e-5
        old_action = _old_action(row["evidence_status"])
        new_action = _new_action(row["evidence_status"], row["shift_status"])
        records.append({
            **{key: row[key] for key in ("proposal_id", "task_id", "evidence_status", "shift_status")},
            "parent_nmse": parent,
            "candidate_nmse": candidate,
            "harmful": harmful,
            "beneficial": beneficial,
            "old_replacement_action": old_action,
            "new_shift_aware_action": new_action,
            "old_deployed_harmful": old_action == "execute_candidate" and harmful,
            "new_deployed_harmful": new_action == "execute_candidate" and harmful,
            "new_prevented_harm": new_action == "retain_parent" and harmful,
            "new_retained_benefit": new_action == "retain_parent" and beneficial,
        })
    summary = {
        "proposals": len(records),
        "old_replacement_deployed_harmful": sum(r["old_deployed_harmful"] for r in records),
        "new_shift_aware_deployed_harmful": sum(r["new_deployed_harmful"] for r in records),
        "new_prevented_harm": sum(r["new_prevented_harm"] for r in records),
        "new_retained_benefit": sum(r["new_retained_benefit"] for r in records),
        "new_executed_beneficial": sum(r["new_shift_aware_action"] == "execute_candidate" and r["beneficial"] for r in records),
    }
    if summary != {
        "proposals": 16,
        "old_replacement_deployed_harmful": 4,
        "new_shift_aware_deployed_harmful": 0,
        "new_prevented_harm": 12,
        "new_retained_benefit": 0,
        "new_executed_beneficial": 4,
    }:
        raise AssertionError(f"unexpected synthetic summary: {summary}")
    return {
        "schema": "replacement-shift-aware-outcome-preflight-v0.1",
        "status": "passed_shift_outcome_preflight",
        "source_preflight": str(preflight_path.relative_to(ROOT)).replace("\\", "/"),
        "source_preflight_sha256": hashlib.sha256(preflight_path.read_bytes()).hexdigest(),
        "model_requests": 0,
        "real_candidate_executions": 0,
        "official_test_read": False,
        "official_test_ood_read": False,
        "synthetic_fixture": True,
        "summary": summary,
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", type=Path, default=ROOT / "docs/environment/2026-10-26-shift-aware-preflight.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.preflight)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "summary": result["summary"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

