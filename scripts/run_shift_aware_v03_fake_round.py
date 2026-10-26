#!/usr/bin/env python3
"""Run the v02 FakeProvider round, then apply the v03 gate wrapper."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_shift_aware_v02_round import run as run_v02
from scripts.run_shift_aware_v03_replay import run as run_v03


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize_fake_round(fake_summary: dict[str, Any], v03_summary: dict[str, Any]) -> dict[str, Any]:
    if (
        fake_summary.get("official_test_read")
        or fake_summary.get("official_test_ood_read")
        or v03_summary.get("official_test_read")
        or v03_summary.get("official_test_ood_read")
    ):
        raise ValueError("official holdout access is forbidden in fake v03 round")
    if fake_summary.get("real_model_calls") != 0:
        raise ValueError("fake round reported real model calls")
    if v03_summary.get("model_requests") != 0:
        raise ValueError("v03 wrapper unexpectedly made model requests")
    v03_aggregate = v03_summary.get("summary", {})
    if not isinstance(v03_aggregate, dict):
        raise ValueError("v03 summary aggregate is invalid")
    proposal_count = v03_aggregate.get("proposal_count", v03_summary.get("proposal_count"))
    supported_proposals = sum(
        row.get("evidence_status") == "supported"
        for row in v03_summary.get("rows", [])
        if isinstance(row, dict)
    )
    return {
        "status": "passed_shift_aware_v03_fake_round",
        "provider_calls": fake_summary.get("provider_calls"),
        "fake_model_requests": fake_summary.get("model_requests"),
        "real_model_calls": fake_summary.get("real_model_calls"),
        "accepted_slots": fake_summary.get("accepted_slots"),
        "gate_records": fake_summary.get("gate_records"),
        "fake_actual_tokens": fake_summary.get("budget", {}).get("actual_tokens"),
        "proposal_count": proposal_count,
        "supported_proposals": supported_proposals,
        "v03_model_requests": v03_summary.get("model_requests"),
        "v03_sandbox_calls": v03_summary.get("sandbox_calls"),
        "v03_summary": v03_aggregate,
        "official_test_read": False,
        "official_test_ood_read": False,
    }


def run(*, run_id: str, output: Path) -> dict[str, Any]:
    fake = run_v02("fake", run_id)
    round_summary_path = ROOT / "runs/replacement-shift-aware-v02" / run_id / "round/round-summary.json"
    proxy_output = ROOT / "runs/replacement-shift-aware-v03" / f"{run_id}-proxy.json"
    v03 = run_v03(output=proxy_output, round_summary_path=round_summary_path)
    result = summarize_fake_round(fake, v03)
    result.update({
        "schema": "replacement-shift-aware-v03-fake-round-v0.1",
        "run_id": run_id,
        "fake_summary_sha256": _sha256(ROOT / "runs/replacement-shift-aware-v02" / run_id / "summary.json"),
        "round_summary_sha256": _sha256(round_summary_path),
        "v03_proxy_sha256": _sha256(proxy_output),
    })
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(run_id=args.run_id, output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
