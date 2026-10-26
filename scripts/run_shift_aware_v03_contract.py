#!/usr/bin/env python3
"""Check the v03 evidence/shift/outcome action contract without model calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.replacement_evidence.shift_outcome_gate import decide_shift_outcome


def build_contract_cases() -> list[dict[str, Any]]:
    definitions = [
        ("supported_covered", "supported", "covered", 1.0, 0.0, 0),
        ("supported_shifted_pass", "supported", "shifted", 1.0, 0.8, 64),
        ("supported_shifted_fail", "supported", "shifted", 1.0, 1.2, 64),
        ("supported_shifted_unavailable", "supported", "shifted", None, 0.8, 64),
        ("contradicted_covered", "contradicted", "covered", 1.0, 0.8, 64),
        ("contradicted_shifted", "contradicted", "shifted", 1.0, 0.8, 64),
        ("unknown_shifted", "unknown", "shifted", 1.0, 0.8, 64),
    ]
    cases = []
    for name, evidence, shift, parent, candidate, n_rows in definitions:
        result = decide_shift_outcome(
            evidence_status=evidence,
            shift_status=shift,
            parent_nmse=parent,
            candidate_nmse=candidate,
            n_rows=n_rows,
        )
        cases.append({"name": name, **result})
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = build_contract_cases()
    result = {
        "schema": "replacement-shift-aware-outcome-gate-v03-contract-v0.1",
        "status": "passed_shift_outcome_gate_v03_contract",
        "model_requests": 0,
        "official_test_read": False,
        "official_test_ood_read": False,
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "case_count": len(cases),
        "model_requests": result["model_requests"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
