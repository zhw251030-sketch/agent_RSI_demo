#!/usr/bin/env python3
"""Evaluate the two frozen development rounds on official holdout files.

The command refuses to open ``test_id``/``test_ood`` unless the explicit
``--release-holdout`` switch is supplied.  It never calls an LLM.  Parameters
are fitted on the already frozen fit_dev split and then held fixed for test
prediction; frozen gate actions are read from the two development summaries.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.replacement_evidence.cross_task_config import CROSS_TASK_DEFINITIONS, SPLIT_REPORT as CROSS_SPLIT_REPORT
from analysis.replacement_evidence.round_runner import (
    TASK_DEFINITIONS, FrozenTask, compile_basis, load_frozen_tasks,
)
from extensions.symbolic_basis_v01.executor import check_runtime, sandbox_call


DEV_REPORT = "docs/environment/2026-10-24-replacement-dev-splits.json"
HOLDOUT_FILES = {
    "bactgrow": {"test_id": "data/symbolic/llm-sr/bactgrow/test_id.csv",
                 "test_ood": "data/symbolic/llm-sr/bactgrow/test_ood.csv"},
    "stressstrain": {"test_id": "data/symbolic/llm-sr/stressstrain/test_id.csv",
                     "test_ood": "data/symbolic/llm-sr/stressstrain/test_ood.csv"},
    "oscillator1": {"test_id": "data/symbolic/llm-sr/oscillator1/test_id.csv",
                    "test_ood": "data/symbolic/llm-sr/oscillator1/test_ood.csv"},
    "oscillator2": {"test_id": "data/symbolic/llm-sr/oscillator2/test_id.csv",
                    "test_ood": "data/symbolic/llm-sr/oscillator2/test_ood.csv"},
}
TOLERANCE = 1e-5


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_holdout(path: Path, task: FrozenTask) -> tuple[list[list[float]], list[float], str, int, tuple[str, ...]]:
    raw = path.read_bytes()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = tuple(reader.fieldnames or ())
        if headers != task.definition.headers:
            raise ValueError(f"{task.definition.task_id} holdout headers mismatch")
        X: list[list[float]] = []
        y: list[float] = []
        for row in reader:
            try:
                values = [float(row[name]) for name in headers]
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{task.definition.task_id} holdout contains nonnumeric value") from exc
            if not all(math.isfinite(value) for value in values):
                raise ValueError(f"{task.definition.task_id} holdout contains nonfinite value")
            X.append(values[:-1])
            y.append(values[-1])
    if not X:
        raise ValueError(f"{task.definition.task_id} holdout is empty")
    return X, y, hashlib.sha256(raw).hexdigest(), len(raw), headers


def _fit_source(source: str, n_params: int, task: FrozenTask) -> list[float]:
    split = task.splits["fit_dev"]
    request = {
        "family": "symbolic", "task_id": task.definition.task_id,
        "input_names": list(task.definition.input_names), "phase": "fit",
        "split_name": "fit_dev", "split_sha256": split.split_sha256,
        "X": [list(row) for row in split.X], "y": list(split.y),
        "n_params": n_params,
    }
    response = sandbox_call(source, request)
    result = response.get("result", {}) if isinstance(response, dict) else {}
    params = result.get("params") if response.get("status") == "completed" else None
    if (result.get("status") != "success" or result.get("converged") is not True
            or not isinstance(params, list) or len(params) != n_params
            or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in params)):
        raise RuntimeError(f"fit_dev fit failed for {task.definition.task_id}")
    return [float(value) for value in params]


def _predict(source: str, params: list[float], task: FrozenTask, split_name: str,
             X: list[list[float]], y: list[float], split_sha256: str) -> float:
    request = {
        "family": "symbolic", "task_id": task.definition.task_id,
        "input_names": list(task.definition.input_names), "phase": "predict",
        "split_name": split_name, "split_sha256": split_sha256,
        "X": X, "params": params,
    }
    response = sandbox_call(source, request)
    result = response.get("result", {}) if isinstance(response, dict) else {}
    predictions = result.get("predictions") if response.get("status") == "completed" else None
    if result.get("status") != "success" or not isinstance(predictions, list) or len(predictions) != len(y):
        raise RuntimeError(f"{task.definition.task_id}/{split_name} prediction failed")
    mean = math.fsum(y) / len(y)
    variance = math.fsum((value - mean) ** 2 for value in y) / len(y)
    if variance == 0:
        raise RuntimeError(f"{task.definition.task_id}/{split_name} target variance is zero")
    mse = math.fsum((truth - float(pred) if math.isfinite(float(pred)) else math.inf) ** 2
                    for truth, pred in zip(y, predictions)) / len(y)
    nmse = mse / variance
    if not math.isfinite(nmse):
        raise RuntimeError(f"{task.definition.task_id}/{split_name} NMSE is nonfinite")
    return nmse


def _load_development_records() -> tuple[dict[str, FrozenTask], list[dict[str, Any]], dict[str, Any]]:
    base = load_frozen_tasks(ROOT, ROOT / DEV_REPORT, TASK_DEFINITIONS)
    cross = load_frozen_tasks(ROOT, ROOT / CROSS_SPLIT_REPORT, CROSS_TASK_DEFINITIONS)
    tasks = {**base, **cross}
    runs = [
        ROOT / "runs/replacement-agent-round/2026-10-25-real-v04/round/round-summary.json",
        ROOT / "runs/replacement-cross-task-round/2026-10-25-cross-real-v01/round/round-summary.json",
    ]
    records: list[dict[str, Any]] = []
    frozen: dict[str, Any] = {}
    for path in runs:
        summary = json.loads(path.read_text(encoding="utf-8"))
        if summary.get("status") != "passed" or summary.get("outcome_dev_read") is not True:
            raise RuntimeError(f"development summary is incomplete: {path}")
        for row in summary["records"]:
            records.append({"record": row, "source_summary": str(path.relative_to(ROOT))})
        frozen[str(path.relative_to(ROOT))] = summary["frozen_gates"]
    if len(records) != 24:
        raise RuntimeError("expected exactly 24 frozen development proposals")
    return tasks, records, frozen


def _gate_action(frozen: dict[str, Any], proposal_id: str, condition: str) -> str:
    rows = frozen["frozen"]["rows"]
    matches = [row for row in rows if row.get("proposal_id") == proposal_id and row.get("condition") == condition]
    if len(matches) != 1:
        raise RuntimeError(f"missing unique frozen gate for {proposal_id}/{condition}")
    return matches[0]["final_action"]


def run(*, output_dir: Path, release_holdout: bool) -> dict[str, Any]:
    check_runtime()
    tasks, records, frozen_by_summary = _load_development_records()
    if not release_holdout:
        return {
            "schema": "replacement-holdout-v0.1", "status": "ready_without_holdout_read",
            "proposal_count": len(records), "tasks": sorted(tasks),
            "holdout_paths": HOLDOUT_FILES,
            "note": "No test_id/test_ood file was opened. Re-run with --release-holdout to unseal once.",
        }

    holdout: dict[str, dict[str, tuple[list[list[float]], list[float], str, int, tuple[str, ...]]]] = {}
    for task_id, paths in HOLDOUT_FILES.items():
        holdout[task_id] = {}
        for split_name, relative in paths.items():
            holdout[task_id][split_name] = _read_holdout(ROOT / relative, tasks[task_id])

    # One fit per unique source.  Parameters are never fitted on holdout rows.
    params_by_source: dict[tuple[str, str], list[float]] = {}
    nmse_by_source: dict[tuple[str, str, str], float] = {}
    rows: list[dict[str, Any]] = []
    for item in records:
        record = item["record"]
        task = tasks[record["task_id"]]
        parent = compile_basis(task.definition, record["parent_feature_ids"])
        candidate = compile_basis(task.definition, record["candidate_feature_ids"])
        sources = {"parent": parent, "candidate": candidate}
        for role, compiled in sources.items():
            key = (record["task_id"], compiled["source_sha256"])
            if key not in params_by_source:
                params_by_source[key] = _fit_source(compiled["source"], compiled["n_params"], task)
            for split_name, (_, _, split_sha, _, _) in holdout[record["task_id"]].items():
                metric_key = (record["task_id"], compiled["source_sha256"], split_name)
                if metric_key not in nmse_by_source:
                    X, y, _, _, _ = holdout[record["task_id"]][split_name]
                    nmse_by_source[metric_key] = _predict(
                        compiled["source"], params_by_source[key], task, split_name,
                        X, y, split_sha,
                    )
        proposal_id = record["slot_id"]
        frozen = frozen_by_summary[item["source_summary"]]
        for split_name in ("test_id", "test_ood"):
            parent_nmse = nmse_by_source[(record["task_id"], parent["source_sha256"], split_name)]
            candidate_nmse = nmse_by_source[(record["task_id"], candidate["source_sha256"], split_name)]
            harmful = candidate_nmse > parent_nmse + TOLERANCE
            beneficial = candidate_nmse < parent_nmse - TOLERANCE
            actions = {
                "no_check": "execute_candidate" if record["edit_mode"] == "swap_one" else "retain_parent",
                "sham_check": "execute_candidate" if record["edit_mode"] == "swap_one" else "retain_parent",
                "replacement_check": _gate_action(frozen, proposal_id, "replacement_check"),
            }
            for condition, action in actions.items():
                rows.append({
                    "task_id": record["task_id"], "proposal_id": proposal_id,
                    "split_name": split_name, "condition": condition,
                    "final_action": action, "parent_nmse": parent_nmse,
                    "candidate_nmse": candidate_nmse, "delta_nmse": candidate_nmse - parent_nmse,
                    "harmful": harmful, "beneficial": beneficial,
                    "deployed_harmful": action == "execute_candidate" and harmful,
                    "prevented_harm": action == "retain_parent" and harmful,
                    "retained_benefit": action == "retain_parent" and beneficial,
                })

    summary: dict[str, Any] = {}
    for condition in ("no_check", "sham_check", "replacement_check"):
        for split_name in ("test_id", "test_ood"):
            selected = [row for row in rows if row["condition"] == condition and row["split_name"] == split_name]
            summary[f"{condition}/{split_name}"] = {
                "proposals": len(selected),
                "deployed_harmful": sum(row["deployed_harmful"] for row in selected),
                "prevented_harm": sum(row["prevented_harm"] for row in selected),
                "retained_benefit": sum(row["retained_benefit"] for row in selected),
                "candidate_executions": sum(row["final_action"] == "execute_candidate" for row in selected),
                "parent_retained": sum(row["final_action"] == "retain_parent" for row in selected),
            }
    return {
        "schema": "replacement-holdout-v0.1", "status": "passed_holdout_read",
        "proposal_count": len(records), "tolerance": TOLERANCE,
        "holdout_files": {
            task: {split: {"sha256": value[2], "bytes": value[3], "rows": len(value[1]), "headers": list(value[4])}
                   for split, value in splits.items()} for task, splits in holdout.items()
        },
        "summary": summary, "rows": rows,
        "interpretation": "Descriptive frozen-proposal holdout replay; no model calls or gate changes.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-holdout", action="store_true",
                        help="explicitly open official test_id/test_ood files once")
    args = parser.parse_args()
    result = run(output_dir=args.output, release_holdout=args.release_holdout)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "proposal_count", "summary") if key in result},
                     ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
