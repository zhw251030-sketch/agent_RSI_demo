#!/usr/bin/env python3
"""Replay frozen v02 proposals through the v03 outcome validation gate."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.replacement_evidence.cross_task_config import CROSS_TASK_DEFINITIONS
from analysis.replacement_evidence.round_runner import (
    TASK_DEFINITIONS, TaskDefinition, compile_basis, load_frozen_tasks,
)
from analysis.replacement_evidence.shift_outcome_gate import decide_shift_outcome
from extensions.symbolic_basis_v01.executor import check_runtime, sandbox_call
from scripts.build_shift_aware_dev_v02 import TASK_FILES, _read
from scripts.build_shift_aware_outcome_proxy_v03 import build_report as build_proxy_report


ALL_TASK_DEFINITIONS = tuple(
    TaskDefinition(item.task_id, item.input_names, item.headers, item.target, item.parents[:1])
    for item in (TASK_DEFINITIONS + CROSS_TASK_DEFINITIONS)
)
SHIFT_REPORT = ROOT / "docs/environment/2026-10-26-shift-aware-dev-v02.json"
REAL_ROUND = ROOT / "runs/replacement-shift-aware-v02/2026-10-26-v02-real-v01/round/round-summary.json"
TOLERANCE = 1e-5


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _fit(source: str, task: Any, n_params: int) -> tuple[list[float], int]:
    split = task.splits["fit_dev"]
    response = sandbox_call(source, {
        "family": "symbolic", "task_id": task.definition.task_id,
        "input_names": list(task.definition.input_names), "phase": "fit",
        "split_name": "fit_dev_v2", "split_sha256": split.split_sha256,
        "X": [list(row) for row in split.X], "y": list(split.y), "n_params": n_params,
    })
    result = response.get("result", {})
    params = result.get("params") if response.get("status") == "completed" else None
    if result.get("status") != "success" or not isinstance(params, list) or len(params) != n_params:
        raise RuntimeError(f"fit failed for {task.definition.task_id}")
    return [float(value) for value in params], 1


def _predict(source: str, params: list[float], task: Any, fixture: dict[str, Any]) -> tuple[float, int]:
    response = sandbox_call(source, {
        "family": "symbolic", "task_id": task.definition.task_id,
        "input_names": list(task.definition.input_names), "phase": "predict",
        "split_name": "synthetic_shift_outcome_dev_v3",
        "split_sha256": fixture["fixture_sha256"],
        "X": fixture["X"], "params": params,
    })
    result = response.get("result", {})
    predictions = result.get("predictions") if response.get("status") == "completed" else None
    if result.get("status") != "success" or not isinstance(predictions, list):
        raise RuntimeError(f"prediction failed for {task.definition.task_id}")
    y = [float(value) for value in fixture["y"]]
    if len(predictions) != len(y) or not y:
        raise RuntimeError(f"prediction length mismatch for {task.definition.task_id}")
    mean = math.fsum(y) / len(y)
    variance = math.fsum((value - mean) ** 2 for value in y) / len(y)
    if variance <= 0.0:
        raise RuntimeError(f"proxy target variance unavailable for {task.definition.task_id}")
    mse = math.fsum((float(pred) - truth) ** 2 for pred, truth in zip(predictions, y)) / len(y)
    return mse / variance, 1


def summarize_proxy_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = Counter(row["decision"] for row in rows if "decision" in row)
    return {
        "proposal_count": len(rows),
        "proxy_harmful": sum(bool(row.get("proxy_harmful")) for row in rows),
        "old_deployed_proxy_harmful": sum(
            bool(row.get("proxy_harmful")) and row.get("old_action") == "execute_candidate"
            for row in rows
        ),
        "v02_shift_deployed_proxy_harmful": sum(
            bool(row.get("proxy_harmful")) and row.get("v02_shift_action") == "execute_candidate"
            for row in rows
        ),
        "v03_deployed_proxy_harmful": sum(
            bool(row.get("proxy_harmful")) and row.get("v03_action") == "execute_candidate"
            for row in rows
        ),
        "v02_prevented_vs_old": sum(
            bool(row.get("proxy_harmful"))
            and row.get("old_action") == "execute_candidate"
            and row.get("v02_shift_action") == "retain_parent"
            for row in rows
        ),
        "v03_new_prevented_vs_old": sum(
            bool(row.get("proxy_harmful"))
            and row.get("old_action") == "execute_candidate"
            and row.get("v03_action") == "retain_parent"
            for row in rows
        ),
        "v03_new_prevented_vs_v02": sum(
            bool(row.get("proxy_harmful"))
            and row.get("v02_shift_action") == "execute_candidate"
            and row.get("v03_action") == "retain_parent"
            for row in rows
        ),
        "v03_action_changes_from_v02": sum(bool(row.get("changed_from_v02")) for row in rows),
        "decision_counts": dict(sorted(decisions.items())),
    }


def run(
    *,
    output: Path,
    round_summary_path: Path = REAL_ROUND,
    shift_report_path: Path = SHIFT_REPORT,
) -> dict[str, Any]:
    check_runtime()
    shift_report = json.loads(shift_report_path.read_text(encoding="utf-8"))
    round_summary = json.loads(round_summary_path.read_text(encoding="utf-8"))
    if shift_report.get("official_test_read") or shift_report.get("official_test_ood_read"):
        raise ValueError("shift report claims official holdout access")
    if round_summary.get("official_test_read") or round_summary.get("official_test_ood_read"):
        raise ValueError("real round claims official holdout access")
    proxy_report = build_proxy_report(ROOT, shift_report_path)
    if proxy_report["official_test_read"] or proxy_report["official_test_ood_read"]:
        raise ValueError("proxy report claims official holdout access")
    tasks = load_frozen_tasks(ROOT, shift_report_path, task_definitions=ALL_TASK_DEFINITIONS)
    frozen = {
        row["proposal_id"]: row["final_action"]
        for row in round_summary["frozen_gates"]["frozen"]["rows"]
        if row["condition"] == "replacement_check"
    }
    records = {row["slot_id"]: row for row in round_summary["records"]}
    proxy_tasks = proxy_report["tasks"]
    rows: list[dict[str, Any]] = []
    sandbox_calls = 0
    for task_id, relative in TASK_FILES.items():
        headers, source_rows, _, _ = _read(ROOT / relative)
        task = tasks[task_id]
        fixture = proxy_tasks[task_id]
        for proposal_id, record in sorted(records.items()):
            if record["task_id"] != task_id:
                continue
            parent = compile_basis(task.definition, record["parent_feature_ids"])
            parent_params, calls = _fit(parent["source"], task, parent["n_params"])
            sandbox_calls += calls
            parent_nmse, calls = _predict(parent["source"], parent_params, task, fixture)
            sandbox_calls += calls
            candidate_nmse = parent_nmse
            if record["edit_mode"] == "swap_one":
                candidate = compile_basis(task.definition, record["candidate_feature_ids"])
                candidate_params, calls = _fit(candidate["source"], task, candidate["n_params"])
                sandbox_calls += calls
                candidate_nmse, calls = _predict(candidate["source"], candidate_params, task, fixture)
                sandbox_calls += calls
            evidence_status = record["evidence"].get("status", "unknown")
            shift_status = shift_report["tasks"][task_id]["synthetic_shift_dev"]["shifted_input_score"]["status"]
            decision = decide_shift_outcome(
                evidence_status=evidence_status,
                shift_status=shift_status,
                parent_nmse=parent_nmse,
                candidate_nmse=candidate_nmse,
                n_rows=len(fixture["y"]),
            )
            old_action = frozen[proposal_id]
            v02_shift_action = (
                old_action
                if shift_status == "covered" or evidence_status != "supported"
                else "retain_parent"
            )
            delta = candidate_nmse - parent_nmse
            rows.append({
                "proposal_id": proposal_id,
                "task_id": task_id,
                "fixture_id": fixture["fixture_id"],
                "evidence_status": evidence_status,
                "shift_status": shift_status,
                "parent_nmse": parent_nmse,
                "candidate_nmse": candidate_nmse,
                "delta_nmse": delta,
                "proxy_harmful": bool(record["edit_mode"] == "swap_one" and delta > TOLERANCE),
                "old_action": old_action,
                "v02_shift_action": v02_shift_action,
                "v03_action": decision["final_action"],
                "changed_from_old": old_action != decision["final_action"],
                "changed_from_v02": v02_shift_action != decision["final_action"],
                "decision": decision["decision"],
                "validation_status": decision["validation_status"],
                "decision_reason": decision["reason"],
                "threshold": decision["threshold"],
                "min_rows": decision["min_rows"],
                "target_source": fixture["target_source"],
                "not_benchmark": fixture["not_benchmark"],
            })
    result = {
        "schema": "replacement-shift-aware-outcome-gate-v03-replay",
        "status": "passed_shift_outcome_gate_v03_replay",
        "real_round": str(round_summary_path.relative_to(ROOT)).replace("\\", "/"),
        "real_round_sha256": _sha256(round_summary_path.read_bytes()),
        "shift_report": str(shift_report_path.relative_to(ROOT)).replace("\\", "/"),
        "shift_report_sha256": _sha256(shift_report_path.read_bytes()),
        "proxy_report": "in_memory:build_shift_aware_outcome_proxy_v03",
        "model_requests": 0,
        "sandbox_calls": sandbox_calls,
        "official_test_read": False,
        "official_test_ood_read": False,
        "not_benchmark": True,
        "summary": summarize_proxy_rows(rows),
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "model_requests": result["model_requests"],
        "sandbox_calls": result["sandbox_calls"],
        **result["summary"],
    }, ensure_ascii=False, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--round-summary", type=Path, default=REAL_ROUND)
    parser.add_argument("--shift-report", type=Path, default=SHIFT_REPORT)
    args = parser.parse_args()
    run(output=args.output, round_summary_path=args.round_summary, shift_report_path=args.shift_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
