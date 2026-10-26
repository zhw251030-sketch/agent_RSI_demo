#!/usr/bin/env python3
"""Score frozen real proposals on input-only synthetic shift fixtures.

The original fit_dev targets are reused only as a proxy diagnostic for the
transformed inputs.  This is explicitly not an OOD benchmark score.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.replacement_evidence.cross_task_config import CROSS_TASK_DEFINITIONS
from analysis.replacement_evidence.round_runner import (
    TASK_DEFINITIONS, compile_basis, load_frozen_tasks,
)
from extensions.symbolic_basis_v01.executor import check_runtime, sandbox_call
from scripts.build_shift_aware_dev_v02 import TASK_FILES, _fixture_rows, _read


ALL_TASK_DEFINITIONS = TASK_DEFINITIONS + CROSS_TASK_DEFINITIONS
SHIFT_REPORT = ROOT / "docs/environment/2026-10-26-shift-aware-dev-v02.json"
REAL_ROUND = ROOT / "runs/replacement-shift-aware-v02/2026-10-26-v02-real-v01/round/round-summary.json"
TOLERANCE = 1e-5


def _fit(source: str, task, n_params: int) -> list[float]:
    split = task.splits["fit_dev"]
    response = sandbox_call(source, {
        "family": "symbolic", "task_id": task.definition.task_id,
        "input_names": list(task.definition.input_names), "phase": "fit",
        "split_name": "fit_dev", "split_sha256": split.split_sha256,
        "X": [list(row) for row in split.X], "y": list(split.y), "n_params": n_params,
    })
    result = response.get("result", {})
    params = result.get("params") if response.get("status") == "completed" else None
    if result.get("status") != "success" or not isinstance(params, list) or len(params) != n_params:
        raise RuntimeError(f"fit failed for {task.definition.task_id}")
    return [float(value) for value in params]


def _predict(source: str, params: list[float], task, X, y, split_sha: str) -> float:
    response = sandbox_call(source, {
        "family": "symbolic", "task_id": task.definition.task_id,
        "input_names": list(task.definition.input_names), "phase": "predict",
        "split_name": "synthetic_shift_dev", "split_sha256": split_sha,
        "X": X, "params": params,
    })
    result = response.get("result", {})
    predictions = result.get("predictions") if response.get("status") == "completed" else None
    if result.get("status") != "success" or not isinstance(predictions, list) or len(predictions) != len(y):
        raise RuntimeError(f"proxy prediction failed for {task.definition.task_id}")
    mean = math.fsum(y) / len(y)
    variance = math.fsum((value - mean) ** 2 for value in y) / len(y)
    if variance <= 0:
        raise RuntimeError(f"proxy target variance unavailable for {task.definition.task_id}")
    mse = math.fsum((float(pred) - truth) ** 2 for pred, truth in zip(predictions, y)) / len(y)
    return mse / variance


def run(output: Path) -> dict:
    check_runtime()
    shift = json.loads(SHIFT_REPORT.read_text(encoding="utf-8"))
    round_summary = json.loads(REAL_ROUND.read_text(encoding="utf-8"))
    if shift.get("official_test_read") or shift.get("official_test_ood_read"):
        raise ValueError("shift report claims official holdout access")
    if round_summary.get("official_test_read") or round_summary.get("official_test_ood_read"):
        raise ValueError("real round claims official holdout access")
    tasks = load_frozen_tasks(ROOT, SHIFT_REPORT, task_definitions=ALL_TASK_DEFINITIONS)
    frozen = {row["proposal_id"]: row["final_action"]
              for row in round_summary["frozen_gates"]["frozen"]["rows"]
              if row["condition"] == "replacement_check"}
    records = {row["slot_id"]: row for row in round_summary["records"]}
    rows = []
    for task_id, relative in TASK_FILES.items():
        headers, source_rows, _, _ = _read(ROOT / relative)
        entry = shift["tasks"][task_id]
        indices = entry["synthetic_shift_dev"]["source_row_indices"]
        profile = entry["profile"]
        fixture_id, shifted_X, _ = _fixture_rows(task_id, source_rows, headers, indices, profile)
        target_name = headers[-1]
        shifted_y = [float(source_rows[index][target_name]) for index in indices]
        split_sha = hashlib.sha256(json.dumps({"fixture_id": fixture_id, "indices": indices}, sort_keys=True).encode()).hexdigest()
        task = tasks[task_id]
        for proposal_id, record in sorted(records.items()):
            if record["task_id"] != task_id:
                continue
            parent = compile_basis(task.definition, record["parent_feature_ids"])
            parent_params = _fit(parent["source"], task, parent["n_params"])
            parent_nmse = _predict(parent["source"], parent_params, task, shifted_X, shifted_y, split_sha)
            candidate_nmse = parent_nmse
            if record["edit_mode"] == "swap_one":
                candidate = compile_basis(task.definition, record["candidate_feature_ids"])
                candidate_params = _fit(candidate["source"], task, candidate["n_params"])
                candidate_nmse = _predict(candidate["source"], candidate_params, task, shifted_X, shifted_y, split_sha)
            delta = candidate_nmse - parent_nmse
            evidence_status = record["evidence"].get("status", "unknown")
            old_action = frozen[proposal_id]
            shift_action = "execute_candidate" if evidence_status == "supported" and entry["synthetic_shift_dev"]["shifted_input_score"]["status"] == "covered" else "retain_parent"
            rows.append({
                "proposal_id": proposal_id, "task_id": task_id, "fixture_id": fixture_id,
                "evidence_status": evidence_status, "old_action": old_action,
                "shift_action": shift_action, "parent_proxy_nmse": parent_nmse,
                "candidate_proxy_nmse": candidate_nmse, "delta_proxy_nmse": delta,
                "proxy_harmful": bool(record["edit_mode"] == "swap_one" and delta > TOLERANCE),
                "action_changed": old_action != shift_action,
            })
    result = {
        "schema": "replacement-shift-aware-proxy-outcome-v0.1",
        "status": "passed_shift_proxy_outcome",
        "real_round": str(REAL_ROUND.relative_to(ROOT)).replace("\\", "/"),
        "shift_report": str(SHIFT_REPORT.relative_to(ROOT)).replace("\\", "/"),
        "model_requests": 0, "candidate_executions": 0,
        "official_test_read": False, "official_test_ood_read": False,
        "target_source": "fit_dev target rows reused as synthetic proxy labels",
        "not_benchmark": True,
        "proposal_count": len(rows),
        "proxy_harmful": sum(row["proxy_harmful"] for row in rows),
        "old_deployed_proxy_harmful": sum(row["proxy_harmful"] and row["old_action"] == "execute_candidate" for row in rows),
        "shift_deployed_proxy_harmful": sum(row["proxy_harmful"] and row["shift_action"] == "execute_candidate" for row in rows),
        "shift_prevented_proxy_harm": sum(row["proxy_harmful"] and row["shift_action"] == "retain_parent" for row in rows),
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "proposal_count", "proxy_harmful", "old_deployed_proxy_harmful", "shift_deployed_proxy_harmful", "shift_prevented_proxy_harm")}, ensure_ascii=False, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

