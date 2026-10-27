#!/usr/bin/env python3
"""Model-free replay of the fake SRSD-Dummy round on frozen validation domains."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.replacement_evidence.external_dummy_task_config import DUMMY_TASK_DEFINITIONS
from analysis.replacement_evidence.round_runner import compile_basis, load_frozen_tasks
from extensions.symbolic_basis_v01.executor import check_runtime, sandbox_call
from rsi_eval.symbolic import score_predictions


ROUND = ROOT / "runs/replacement-srsd-feynman-dummy-v05/2026-10-27-srsd-dummy-fake-v01/round/round-summary.json"
DEV_REPORT = ROOT / "docs/environment/2026-10-27-srsd-feynman-dummy-dev-v05.json"
VAL_REPORT = ROOT / "docs/environment/2026-10-27-srsd-feynman-dummy-val-domain-v05.json"
TOLERANCE = 1e-5


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _score(source: str, task, split_name: str, split_sha: str, X, y, params):
    response = sandbox_call(source, {
        "family": "symbolic", "task_id": task.definition.task_id,
        "input_names": list(task.definition.input_names), "phase": "predict",
        "split_name": split_name, "split_sha256": split_sha,
        "X": X, "params": params,
    })
    result = response.get("result", {})
    if response.get("status") != "completed" or result.get("status") != "success":
        raise RuntimeError(f"prediction failed for {task.definition.task_id}/{split_name}")
    scored = score_predictions(list(y), result.get("predictions"))
    if scored.get("status") != "success":
        raise RuntimeError(f"metric unavailable for {task.definition.task_id}/{split_name}")
    return float(scored["metrics"]["nmse"])


def _fit_compiled(compiled, task, fit):
    response = sandbox_call(compiled["source"], {
        "family": "symbolic", "task_id": task.definition.task_id,
        "input_names": list(task.definition.input_names), "phase": "fit",
        "split_name": "fit_dev", "split_sha256": fit.split_sha256,
        "X": [list(row) for row in fit.X], "y": list(fit.y),
        "n_params": compiled["n_params"],
    })
    result = response.get("result", {})
    params = result.get("params") if response.get("status") == "completed" else None
    if result.get("status") != "success" or not isinstance(params, list):
        raise RuntimeError(f"fit failed for {task.definition.task_id}")
    return [float(value) for value in params]


def run(output: Path, round_path: Path = ROUND, dev_path: Path = DEV_REPORT,
        val_path: Path = VAL_REPORT) -> dict:
    check_runtime()
    round_obj = json.loads(round_path.read_text(encoding="utf-8"))
    val_report = json.loads(val_path.read_text(encoding="utf-8"))
    if round_obj.get("official_test_read") or round_obj.get("official_test_ood_read"):
        raise ValueError("round claims official holdout access")
    if val_report.get("official_test_read") or val_report.get("official_test_ood_read"):
        raise ValueError("val report claims official holdout access")
    tasks = load_frozen_tasks(ROOT, dev_path, task_definitions=DUMMY_TASK_DEFINITIONS)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError("replay output already exists")
    fit_cache = {}
    rows = []
    for record in sorted(round_obj["records"], key=lambda item: item["slot_id"]):
        task = tasks[record["task_id"]]
        parent = compile_basis(task.definition, record["parent_feature_ids"])
        candidate = compile_basis(task.definition, record["candidate_feature_ids"])
        for compiled in (parent, candidate):
            fit_cache.setdefault(compiled["source_sha256"], _fit_compiled(compiled, task, task.splits["fit_dev"]))
        parent_params = fit_cache[parent["source_sha256"]]
        candidate_params = fit_cache[candidate["source_sha256"]]
        val_task = val_report["tasks"][record["task_id"]]
        ordinary = val_task["ordinary"]
        parent_nmse = _score(parent["source"], task, "val_external_ordinary", ordinary["ordinary_sha256"], ordinary["X"], ordinary["y"], parent_params)
        candidate_nmse = _score(candidate["source"], task, "val_external_ordinary", ordinary["ordinary_sha256"], ordinary["X"], ordinary["y"], candidate_params)
        blocks = []
        for index, block in enumerate(val_task["blocks"]):
            if not block["valid"]:
                continue
            p = _score(parent["source"], task, f"val_external_block_{index}", block["block_sha256"], block["X"], block["y"], parent_params)
            c = _score(candidate["source"], task, f"val_external_block_{index}", block["block_sha256"], block["X"], block["y"], candidate_params)
            blocks.append({"feature": block["feature"], "region": block["region"], "n_rows": block["n_rows"], "parent_nmse": p, "candidate_nmse": c, "delta": c - p, "improved": c < p - TOLERANCE})
        improved = sum(item["improved"] for item in blocks)
        ordinary_delta = candidate_nmse - parent_nmse
        rows.append({
            "slot_id": record["slot_id"], "task_id": record["task_id"],
            "edit_mode": record["edit_mode"], "evidence_status": record["evidence"]["status"],
            "parent_source_sha256": parent["source_sha256"], "candidate_source_sha256": candidate["source_sha256"],
            "parent_nmse": parent_nmse, "candidate_nmse": candidate_nmse,
            "ordinary_delta": ordinary_delta, "blocks": blocks,
            "valid_block_count": len(blocks), "improved_block_count": improved,
            "all_valid_blocks_improved": bool(blocks) and improved == len(blocks),
            "dual_gate_action": "allow_after_val_dual_validation"
                if record["edit_mode"] == "swap_one" and record["evidence"]["status"] == "supported"
                and ordinary_delta <= -TOLERANCE and blocks and improved == len(blocks)
                else "retain_parent",
        })
    result = {
        "schema": "replacement-srsd-feynman-dummy-val-replay-v05",
        "status": "passed", "official_test_read": False, "official_test_ood_read": False,
        "not_benchmark": True, "round_summary_sha256": _sha(round_path.read_bytes()),
        "development_report_sha256": _sha(dev_path.read_bytes()),
        "val_report_sha256": _sha(val_path.read_bytes()), "tolerance": TOLERANCE,
        "rows": rows,
    }
    result["report_sha256"] = _sha(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"], "proposal_count": len(rows),
        "swap_count": sum(row["edit_mode"] == "swap_one" for row in rows),
        "allow_count": sum(row["dual_gate_action"].startswith("allow") for row in rows),
        "official_test_read": False,
    }, ensure_ascii=False, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--round", type=Path, default=ROUND)
    parser.add_argument("--dev-report", type=Path, default=DEV_REPORT)
    parser.add_argument("--val-report", type=Path, default=VAL_REPORT)
    args = parser.parse_args()
    run(args.output, args.round, args.dev_report, args.val_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

