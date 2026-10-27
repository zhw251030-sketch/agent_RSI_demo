#!/usr/bin/env python3
"""Audit the SRSD-Feynman Easy-Dummy real round and its frozen val replay."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(run_root: Path, val_replay: Path, output: Path) -> dict:
    summary_path = run_root / "summary.json"
    round_path = run_root / "round/round-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    round_summary = json.loads(round_path.read_text(encoding="utf-8"))
    replay = json.loads(val_replay.read_text(encoding="utf-8"))
    required = {
        "status": "passed", "mode": "real", "model_requests": 4,
        "accepted_slots": 4, "gate_records": 12, "real_model_calls": 4,
        "official_test_read": False, "official_test_ood_read": False,
        "outcome_dev_read": True,
    }
    if any(summary.get(key) != value for key, value in required.items()):
        raise ValueError("real-round summary contract mismatch")
    budget = summary.get("budget", {})
    if budget.get("request_count") != 4 or budget.get("usage_unknown_count") != 0:
        raise ValueError("real-round budget is incomplete")
    if budget.get("failed_count") != 0:
        raise ValueError("real-round contains failed requests")
    if len(round_summary.get("records", [])) != 4 or len(round_summary.get("frozen_gates", {}).get("frozen", {}).get("rows", [])) != 12:
        raise ValueError("round ledger row count mismatch")
    if replay.get("official_test_read") or replay.get("official_test_ood_read"):
        raise ValueError("val replay claims official holdout access")
    rows = replay.get("rows", [])
    if len(rows) != 4:
        raise ValueError("val replay row count mismatch")
    result = {
        "schema": "replacement-srsd-feynman-dummy-real-v05-audit",
        "status": "passed",
        "run_summary_sha256": _sha(summary_path),
        "round_summary_sha256": _sha(round_path),
        "val_replay_sha256": _sha(val_replay),
        "official_test_read": False,
        "official_test_ood_read": False,
        "model_requests": summary["model_requests"],
        "accepted_slots": summary["accepted_slots"],
        "gate_records": summary["gate_records"],
        "real_model_calls": summary["real_model_calls"],
        "known_prompt_tokens": budget.get("known_prompt_tokens"),
        "known_completion_tokens": budget.get("known_completion_tokens"),
        "known_total_tokens": budget.get("known_total_tokens"),
        "estimated_cost_cny": budget.get("actual_estimated_cost_cny"),
        "usage_unknown_count": budget.get("usage_unknown_count"),
        "evidence_counts": dict(Counter(item["evidence"]["status"] for item in round_summary["records"])),
        "edit_mode_counts": dict(Counter(item["edit_mode"] for item in round_summary["records"])),
        "val_dual_gate_counts": dict(Counter(item["dual_gate_action"] for item in rows)),
        "val_swap_count": sum(item["edit_mode"] == "swap_one" for item in rows),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--val-replay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.run_root, args.val_replay, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

