#!/usr/bin/env python3
"""Audit the frozen p04 round and its v03/v04 replay ledgers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


def audit_p04_records(
    *,
    round_records: Sequence[Mapping[str, Any]],
    v03_rows: Sequence[Mapping[str, Any]],
    v04_rows: Sequence[Mapping[str, Any]],
    official_test_read: bool,
    official_test_ood_read: bool,
) -> dict[str, Any]:
    if official_test_read or official_test_ood_read:
        raise ValueError("official holdout access flag is true")
    round_ids = [row.get("slot_id") for row in round_records]
    v03_ids = [row.get("proposal_id") for row in v03_rows]
    v04_ids = [row.get("proposal_id") for row in v04_rows]
    if any(not isinstance(value, str) or not value for value in round_ids + v03_ids + v04_ids):
        raise ValueError("proposal IDs must be nonempty strings")
    if len(set(round_ids)) != len(round_ids):
        raise ValueError("round proposal IDs are not unique")
    if set(v03_ids) != set(round_ids) or set(v04_ids) != set(round_ids):
        raise ValueError("replay proposal IDs do not match round proposal IDs")

    round_by_id = {row["slot_id"]: row for row in round_records}
    v03_by_id = {row["proposal_id"]: row for row in v03_rows}
    v04_by_id = {row["proposal_id"]: row for row in v04_rows}
    for proposal_id, record in round_by_id.items():
        evidence = record.get("evidence")
        status = evidence.get("status") if isinstance(evidence, Mapping) else None
        if status != v03_by_id[proposal_id].get("evidence_status"):
            raise ValueError(f"evidence status mismatch for {proposal_id}")
        if status != v04_by_id[proposal_id].get("evidence_status"):
            raise ValueError(f"v04 evidence status mismatch for {proposal_id}")
        v04 = v04_by_id[proposal_id]
        decision = v04.get("decision")
        if not isinstance(decision, Mapping) or decision.get("final_action") != v04.get("v04_action"):
            raise ValueError(f"v04 action mismatch for {proposal_id}")
        if record.get("edit_mode") == "keep" and decision.get("reason") != "no_candidate_edit":
            raise ValueError(f"keep proposal has an outcome decision for {proposal_id}")

    checks = {
        "no_official_holdout": True,
        "round_ids_unique": True,
        "replay_ids_match": True,
        "evidence_binding": True,
        "v04_action_consistency": True,
    }
    return {
        "status": "passed",
        "checks": checks,
        "checks_passed": sum(checks.values()),
        "proposal_count": len(round_records),
        "v03_row_count": len(v03_rows),
        "v04_row_count": len(v04_rows),
        "official_test_read": False,
        "official_test_ood_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round-summary", type=Path, required=True)
    parser.add_argument("--v03-replay", type=Path, required=True)
    parser.add_argument("--v04-replay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    round_summary = json.loads(args.round_summary.read_text(encoding="utf-8"))
    v03 = json.loads(args.v03_replay.read_text(encoding="utf-8"))
    v04 = json.loads(args.v04_replay.read_text(encoding="utf-8"))
    result = audit_p04_records(
        round_records=round_summary["records"],
        v03_rows=v03["rows"],
        v04_rows=v04["rows"],
        official_test_read=bool(round_summary.get("official_test_read") or v03.get("official_test_read") or v04.get("official_test_read")),
        official_test_ood_read=bool(round_summary.get("official_test_ood_read") or v03.get("official_test_ood_read") or v04.get("official_test_ood_read")),
    )
    result["round_summary"] = str(args.round_summary)
    result["v03_replay"] = str(args.v03_replay)
    result["v04_replay"] = str(args.v04_replay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
