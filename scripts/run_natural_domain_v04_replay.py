#!/usr/bin/env python3
"""Replay frozen proposals through the v04 natural-domain outcome gate.

The replay is train-only and model-free.  It reuses the accepted proposals
from the real v03 round, fits parent/candidate programs on ``fit_dev_v2``,
scores them on the ordinary outcome rows and on every natural domain block,
then applies the pure v04 dual-outcome gate.
"""

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
from analysis.replacement_evidence.shift_outcome_gate import decide_dual_outcome
from extensions.symbolic_basis_v01.executor import check_runtime, sandbox_call
from scripts.build_shift_aware_dev_v02 import TASK_FILES


ALL_TASK_DEFINITIONS = tuple(
    TaskDefinition(item.task_id, item.input_names, item.headers, item.target, item.parents[:1])
    for item in (TASK_DEFINITIONS + CROSS_TASK_DEFINITIONS)
)
SHIFT_REPORT = ROOT / "docs/environment/2026-10-26-shift-aware-dev-v02.json"
NATURAL_REPORT = ROOT / "docs/environment/2026-10-26-natural-domain-v04.json"
REAL_ROUND = ROOT / "runs/replacement-shift-aware-v02/2026-10-26-v03-real-v01/round/round-summary.json"
V03_PROXY = ROOT / "docs/environment/2026-10-26-shift-aware-v03-real-proxy.json"
TOLERANCE = 1e-5


def _resolve_repo_path(path: Path) -> Path:
    candidate = path if path.is_absolute() else ROOT / path
    resolved = candidate.resolve()
    resolved.relative_to(ROOT)
    return resolved


def _repo_relative(path: Path) -> str:
    return _resolve_repo_path(path).relative_to(ROOT).as_posix()


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
        "X": [list(row) for row in split.X], "y": list(split.y),
        "n_params": n_params,
    })
    result = response.get("result", {})
    params = result.get("params") if response.get("status") == "completed" else None
    if result.get("status") != "success" or not isinstance(params, list) or len(params) != n_params:
        raise RuntimeError(f"fit failed for {task.definition.task_id}")
    return [float(value) for value in params], 1


def _predict(
    source: str,
    params: list[float],
    task: Any,
    *,
    split_name: str,
    split_sha256: str,
    X: list[list[float]],
    y: list[float],
) -> tuple[float, int]:
    response = sandbox_call(source, {
        "family": "symbolic", "task_id": task.definition.task_id,
        "input_names": list(task.definition.input_names), "phase": "predict",
        "split_name": split_name, "split_sha256": split_sha256,
        "X": X, "params": params,
    })
    result = response.get("result", {})
    predictions = result.get("predictions") if response.get("status") == "completed" else None
    if result.get("status") != "success" or not isinstance(predictions, list):
        raise RuntimeError(f"prediction failed for {task.definition.task_id}")
    if len(predictions) != len(y) or not y:
        raise RuntimeError(f"prediction length mismatch for {task.definition.task_id}")
    mean = math.fsum(float(value) for value in y) / len(y)
    variance = math.fsum((float(value) - mean) ** 2 for value in y) / len(y)
    if variance <= 0.0:
        raise RuntimeError(f"outcome target variance unavailable for {task.definition.task_id}")
    mse = math.fsum(
        (float(prediction) - float(truth)) ** 2
        for prediction, truth in zip(predictions, y)
    ) / len(y)
    return mse / variance, 1


def _source_sha(compiled: dict[str, Any]) -> str:
    value = compiled.get("source_sha256")
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("compiled source is missing source_sha256")
    return value


def _score_source(
    *,
    compiled: dict[str, Any],
    task: Any,
    dataset: dict[str, Any],
    split_name: str,
    fit_cache: dict[str, list[float]],
    score_cache: dict[tuple[str, str], float],
) -> tuple[float, int]:
    source_sha = _source_sha(compiled)
    if source_sha not in fit_cache:
        params, _ = _fit(compiled["source"], task, compiled["n_params"])
        fit_cache[source_sha] = params
    score_key = (source_sha, str(dataset["ordinary_sha256"] if "ordinary_sha256" in dataset else dataset["block_sha256"]))
    if score_key in score_cache:
        return score_cache[score_key], 0
    score, calls = _predict(
        compiled["source"], fit_cache[source_sha], task,
        split_name=split_name,
        split_sha256=score_key[1],
        X=dataset["X"], y=[float(value) for value in dataset["y"]],
    )
    score_cache[score_key] = score
    return score, calls


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = Counter(row["decision"] for row in rows if row.get("decision"))
    swap_rows = [row for row in rows if row.get("edit_mode") == "swap_one"]
    harmful = [row for row in swap_rows if row.get("natural_ordinary_harmful")]
    return {
        "proposal_count": len(rows),
        "swap_proposal_count": len(swap_rows),
        "natural_ordinary_harmful": len(harmful),
        "old_deployed_natural_harmful": sum(
            row["natural_ordinary_harmful"] and row["old_action"] == "execute_candidate"
            for row in swap_rows
        ),
        "v02_deployed_natural_harmful": sum(
            row["natural_ordinary_harmful"] and row["v02_shift_action"] == "execute_candidate"
            for row in swap_rows
        ),
        "v03_deployed_natural_harmful": sum(
            row["natural_ordinary_harmful"] and row["v03_action"] == "execute_candidate"
            for row in swap_rows
        ),
        "v04_deployed_natural_harmful": sum(
            row["natural_ordinary_harmful"] and row["v04_action"] == "execute_candidate"
            for row in swap_rows
        ),
        "v04_prevented_vs_old": sum(
            row["natural_ordinary_harmful"]
            and row["old_action"] == "execute_candidate"
            and row["v04_action"] == "retain_parent"
            for row in swap_rows
        ),
        "v04_prevented_vs_v03": sum(
            row["natural_ordinary_harmful"]
            and row["v03_action"] == "execute_candidate"
            and row["v04_action"] == "retain_parent"
            for row in swap_rows
        ),
        "v04_action_changes_from_v03": sum(
            row["v03_action"] != row["v04_action"] for row in rows
        ),
        "decision_counts": dict(sorted(decisions.items())),
    }


def run(
    *,
    output: Path,
    round_summary_path: Path = REAL_ROUND,
    shift_report_path: Path = SHIFT_REPORT,
    natural_report_path: Path = NATURAL_REPORT,
    v03_proxy_path: Path = V03_PROXY,
) -> dict[str, Any]:
    check_runtime()
    round_summary_path = _resolve_repo_path(round_summary_path)
    shift_report_path = _resolve_repo_path(shift_report_path)
    natural_report_path = _resolve_repo_path(natural_report_path)
    v03_proxy_path = _resolve_repo_path(v03_proxy_path)
    output = _resolve_repo_path(output)

    round_summary = json.loads(round_summary_path.read_text(encoding="utf-8"))
    shift_report = json.loads(shift_report_path.read_text(encoding="utf-8"))
    natural_report = json.loads(natural_report_path.read_text(encoding="utf-8"))
    v03_proxy = json.loads(v03_proxy_path.read_text(encoding="utf-8"))
    for name, report in (("round", round_summary), ("shift", shift_report), ("natural", natural_report), ("v03", v03_proxy)):
        if report.get("official_test_read") or report.get("official_test_ood_read"):
            raise ValueError(f"{name} report claims official holdout access")
    if natural_report.get("schema") != "replacement-natural-domain-outcome-v04":
        raise ValueError("unexpected natural-domain report schema")

    tasks = load_frozen_tasks(ROOT, shift_report_path, task_definitions=ALL_TASK_DEFINITIONS)
    frozen = {
        row["proposal_id"]: row["final_action"]
        for row in round_summary["frozen_gates"]["frozen"]["rows"]
        if row["condition"] == "replacement_check"
    }
    v03_rows = {row["proposal_id"]: row for row in v03_proxy["rows"]}
    records = round_summary["records"]
    rows: list[dict[str, Any]] = []
    fit_cache: dict[str, list[float]] = {}
    score_cache: dict[tuple[str, str], float] = {}
    sandbox_calls = 0

    for record in sorted(records, key=lambda item: item["slot_id"]):
        proposal_id = record["slot_id"]
        task_id = record["task_id"]
        task = tasks[task_id]
        natural_task = natural_report["tasks"][task_id]
        parent = compile_basis(task.definition, record["parent_feature_ids"])
        candidate = compile_basis(task.definition, record["candidate_feature_ids"])
        ordinary = natural_task["ordinary"]
        parent_ordinary, calls = _score_source(
            compiled=parent, task=task, dataset=ordinary,
            split_name="outcome_dev_v4_ordinary",
            fit_cache=fit_cache, score_cache=score_cache,
        )
        sandbox_calls += calls
        candidate_ordinary, calls = _score_source(
            compiled=candidate, task=task, dataset=ordinary,
            split_name="outcome_dev_v4_ordinary",
            fit_cache=fit_cache, score_cache=score_cache,
        )
        sandbox_calls += calls

        block_results: list[dict[str, Any]] = []
        for index, block in enumerate(natural_task["blocks"]):
            parent_block, calls = _score_source(
                compiled=parent, task=task, dataset=block,
                split_name=f"outcome_dev_v4_block_{index}",
                fit_cache=fit_cache, score_cache=score_cache,
            )
            sandbox_calls += calls
            candidate_block, calls = _score_source(
                compiled=candidate, task=task, dataset=block,
                split_name=f"outcome_dev_v4_block_{index}",
                fit_cache=fit_cache, score_cache=score_cache,
            )
            sandbox_calls += calls
            block_results.append({
                "block_id": f"{block['feature']}::{block['region']}",
                "feature": block["feature"],
                "region": block["region"],
                "valid": bool(block["valid"]),
                "n_rows": int(block["n_rows"]),
                "block_sha256": block["block_sha256"],
                "parent_nmse": parent_block,
                "candidate_nmse": candidate_block,
            })

        evidence_status = record["evidence"].get("status", "unknown")
        shift_status = shift_report["tasks"][task_id]["synthetic_shift_dev"]["shifted_input_score"]["status"]
        decision = decide_dual_outcome(
            evidence_status=evidence_status,
            shift_status=shift_status,
            ordinary_parent_nmse=parent_ordinary,
            ordinary_candidate_nmse=candidate_ordinary,
            ordinary_n_rows=int(ordinary["n_rows"]),
            domain_blocks=block_results,
        )
        if record["edit_mode"] != "swap_one":
            decision = {
                **decision,
                "decision": "retain",
                "final_action": "retain_parent",
                "validation_status": "not_required",
                "reason": "no_candidate_edit",
            }
        old_action = frozen[proposal_id]
        v02_shift_action = (
            old_action
            if shift_status == "covered" or evidence_status != "supported"
            else "retain_parent"
        )
        v03_action = v03_rows[proposal_id]["v03_action"]
        ordinary_delta = candidate_ordinary - parent_ordinary
        block_deltas = [item["candidate_nmse"] - item["parent_nmse"] for item in block_results]
        rows.append({
            "proposal_id": proposal_id,
            "task_id": task_id,
            "edit_mode": record["edit_mode"],
            "evidence_status": evidence_status,
            "shift_status": shift_status,
            "parent_nmse_ordinary": parent_ordinary,
            "candidate_nmse_ordinary": candidate_ordinary,
            "delta_nmse_ordinary": ordinary_delta,
            "natural_ordinary_harmful": bool(
                record["edit_mode"] == "swap_one" and ordinary_delta > TOLERANCE
            ),
            "max_natural_block_delta_nmse": max(block_deltas) if block_deltas else None,
            "natural_block_harmful": bool(
                record["edit_mode"] == "swap_one"
                and any(delta > TOLERANCE for delta in block_deltas)
            ),
            "old_action": old_action,
            "v02_shift_action": v02_shift_action,
            "v03_action": v03_action,
            "v04_action": decision["final_action"],
            "changed_from_v03": v03_action != decision["final_action"],
            "decision": decision,
            "ordinary_source": {
                "source_split": ordinary["source_split"],
                "n_rows": ordinary["n_rows"],
                "ordinary_sha256": ordinary["ordinary_sha256"],
            },
            "natural_block_count": len(block_results),
            "not_benchmark": True,
        })

    result = {
        "schema": "replacement-natural-domain-outcome-gate-v04-replay",
        "status": "passed_train_only_natural_domain_v04_replay",
        "real_round": _repo_relative(round_summary_path),
        "real_round_sha256": _sha256(round_summary_path.read_bytes()),
        "shift_report": _repo_relative(shift_report_path),
        "shift_report_sha256": _sha256(shift_report_path.read_bytes()),
        "natural_report": _repo_relative(natural_report_path),
        "natural_report_sha256": _sha256(natural_report_path.read_bytes()),
        "v03_proxy": _repo_relative(v03_proxy_path),
        "v03_proxy_sha256": _sha256(v03_proxy_path.read_bytes()),
        "model_requests": 0,
        "sandbox_calls": sandbox_calls,
        "official_test_read": False,
        "official_test_ood_read": False,
        "not_benchmark": True,
        "threshold": TOLERANCE,
        "summary": summarize_rows(rows),
        "rows": rows,
    }
    payload = dict(result)
    result["report_sha256"] = _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
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
    parser.add_argument("--natural-report", type=Path, default=NATURAL_REPORT)
    parser.add_argument("--v03-proxy", type=Path, default=V03_PROXY)
    args = parser.parse_args()
    run(
        output=args.output,
        round_summary_path=args.round_summary,
        shift_report_path=args.shift_report,
        natural_report_path=args.natural_report,
        v03_proxy_path=args.v03_proxy,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
