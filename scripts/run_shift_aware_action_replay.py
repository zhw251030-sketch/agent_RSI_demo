#!/usr/bin/env python3
"""Replay old and shift-aware actions on a frozen train-only v02 round."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _new_action(evidence_status: str, shift_status: str, edit_mode: str) -> str:
    if edit_mode == "keep":
        return "retain_parent"
    return "execute_candidate" if evidence_status == "supported" and shift_status == "covered" else "retain_parent"


def run(round_summary_path: Path, shift_report_path: Path) -> dict:
    summary = json.loads(round_summary_path.read_text(encoding="utf-8"))
    shift = json.loads(shift_report_path.read_text(encoding="utf-8"))
    if summary.get("status") != "passed" or summary.get("official_test_read") or summary.get("official_test_ood_read"):
        raise ValueError("round summary is incomplete or claims official holdout access")
    if shift.get("status") != "frozen_train_only_shift_design":
        raise ValueError("shift report is not a frozen train-only design")
    if shift.get("official_test_read") or shift.get("official_test_ood_read") or shift.get("target_values_read_for_shift"):
        raise ValueError("shift report is not target-free/train-only")
    frozen_rows = summary["frozen_gates"]["frozen"]["rows"]
    replacement_actions = {
        row["proposal_id"]: row["final_action"]
        for row in frozen_rows if row["condition"] == "replacement_check"
    }
    records = {row["slot_id"]: row for row in summary["records"]}
    if set(records) != set(replacement_actions):
        raise ValueError("proposal set mismatch between records and frozen gates")
    rows = []
    for task_id, task in sorted(shift["tasks"].items()):
        # The v02 manifest establishes covered check_dev and shifted fixture
        # statuses before any proposal is replayed.
        covered = task["synthetic_shift_dev"]["baseline_check_score"]["status"]
        shifted = task["synthetic_shift_dev"]["shifted_input_score"]["status"]
        if covered != "covered" or shifted != "shifted":
            raise ValueError(f"fixture status mismatch for {task_id}")
        for proposal_id, record in sorted(records.items()):
            if record["task_id"] != task_id:
                continue
            evidence_status = record["evidence"].get("status", "unknown")
            old_action = replacement_actions[proposal_id]
            covered_action = _new_action(evidence_status, covered, record["edit_mode"])
            shifted_action = _new_action(evidence_status, shifted, record["edit_mode"])
            rows.append({
                "proposal_id": proposal_id,
                "task_id": task_id,
                "edit_mode": record["edit_mode"],
                "evidence_status": evidence_status,
                "old_replacement_action": old_action,
                "covered_action": covered_action,
                "shifted_action": shifted_action,
                "action_changed_on_shift": covered_action != shifted_action,
            })
    if len(rows) != len(records):
        raise ValueError("replay did not cover every proposal")
    return {
        "schema": "replacement-shift-aware-action-replay-v0.1",
        "status": "passed_shift_action_replay",
        "round_summary": str(round_summary_path.relative_to(ROOT)).replace("\\", "/"),
        "round_summary_sha256": _sha(round_summary_path),
        "shift_report": str(shift_report_path.relative_to(ROOT)).replace("\\", "/"),
        "shift_report_sha256": _sha(shift_report_path),
        "model_requests": 0,
        "candidate_executions": 0,
        "official_test_read": False,
        "official_test_ood_read": False,
        "proposal_count": len(rows),
        "covered_execute": sum(row["covered_action"] == "execute_candidate" for row in rows),
        "covered_retain": sum(row["covered_action"] == "retain_parent" for row in rows),
        "shifted_execute": sum(row["shifted_action"] == "execute_candidate" for row in rows),
        "shifted_retain": sum(row["shifted_action"] == "retain_parent" for row in rows),
        "changed_on_shift": sum(row["action_changed_on_shift"] for row in rows),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round-summary", type=Path, required=True)
    parser.add_argument("--shift-report", type=Path, default=ROOT / "docs/environment/2026-10-26-shift-aware-dev-v02.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.round_summary, args.shift_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "proposal_count", "covered_execute", "shifted_execute", "changed_on_shift")}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

