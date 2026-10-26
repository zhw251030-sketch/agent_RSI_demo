#!/usr/bin/env python3
"""Preflight the host-side shift-aware action rule without model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _action(evidence_status: str, shift_status: str) -> str:
    if evidence_status == "supported" and shift_status == "covered":
        return "execute_candidate"
    return "retain_parent"


def run(report_path: Path) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("schema") != "replacement-shift-aware-dev-report-v0.1":
        raise ValueError("shift report schema mismatch")
    if report.get("official_test_read") or report.get("official_test_ood_read"):
        raise ValueError("preflight cannot run on released official holdout")
    if report.get("target_values_read_for_shift"):
        raise ValueError("shift preflight requires target-free diagnostics")
    states = (
        ("supported", "covered", "execute_candidate"),
        ("supported", "shifted", "retain_parent"),
        ("contradicted", "covered", "retain_parent"),
        ("unknown", "shifted", "retain_parent"),
    )
    rows = []
    for task_id, task in sorted(report["tasks"].items()):
        baseline = task["synthetic_shift_dev"]["baseline_check_score"]
        shifted = task["synthetic_shift_dev"]["shifted_input_score"]
        if baseline["status"] != "covered" or shifted["status"] != "shifted":
            raise ValueError(f"fixture status mismatch for {task_id}")
        for ordinal, (evidence_status, shift_status, expected) in enumerate(states, 1):
            action = _action(evidence_status, shift_status)
            rows.append({
                "proposal_id": f"{task_id}-shift-preflight-{ordinal:02d}",
                "task_id": task_id,
                "evidence_status": evidence_status,
                "shift_status": shift_status,
                "final_action": action,
                "expected_action": expected,
                "action_matches": action == expected,
                "replacement_gate_action": "execute_candidate" if evidence_status == "supported" else "retain_parent",
            })
    if not rows or not all(row["action_matches"] for row in rows):
        raise AssertionError("shift-aware action preflight failed")
    return {
        "schema": "replacement-shift-aware-preflight-v0.1",
        "status": "passed_shift_action_preflight",
        "source_report": str(report_path.relative_to(ROOT)).replace("\\", "/"),
        "source_report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "model_requests": 0,
        "candidate_executions": 0,
        "official_test_read": False,
        "official_test_ood_read": False,
        "target_values_read": False,
        "task_count": len(report["tasks"]),
        "case_count": len(rows),
        "expected_action_counts": {
            "execute_candidate": sum(row["expected_action"] == "execute_candidate" for row in rows),
            "retain_parent": sum(row["expected_action"] == "retain_parent" for row in rows),
        },
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=ROOT / "docs/environment/2026-10-26-shift-aware-dev-v02.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "task_count", "case_count", "expected_action_counts")}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

