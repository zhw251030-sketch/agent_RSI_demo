#!/usr/bin/env python3
"""Run a researcher-fixed, no-model triplet through the locked sandbox.

This is an execution-chain preflight only.  It reads public train rows through
the frozen split manifest, never opens test/OOD/sealed files, and does not
create a candidate or mechanism result.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.replacement_evidence.triplet_runner import evaluate_triplet
from extensions.symbolic_basis_v01.contract import compile_submission, make_spec
from extensions.symbolic_basis_v01.executor import sandbox_call


REPORT = ROOT / "docs/environment/2026-10-24-replacement-dev-splits.json"
TASKS = {
    "bactgrow": {
        "path": "data/symbolic/llm-sr/bactgrow/train.csv",
        "headers": ["b", "s", "temp", "pH", "db"],
        "parent": ["m_0_0_0_0", "m_1_0_0_0", "m_0_1_0_0", "m_0_0_1_0"],
        "removed": "m_0_0_1_0",
        "added": "m_0_0_0_1",
    },
    "stressstrain": {
        "path": "data/symbolic/llm-sr/stressstrain/train.csv",
        "headers": ["strain", "temp", "stress"],
        "parent": ["m_0_0", "m_1_0", "m_0_1", "m_1_1"],
        "removed": "m_1_1",
        "added": "m_2_0",
    },
}


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _load_task(task_id: str, config: dict, report: dict) -> tuple[dict, dict, dict]:
    path = ROOT / config["path"]
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != report["tasks"][task_id]["source_sha256"]:
        raise ValueError(f"source hash mismatch: {task_id}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        if reader.fieldnames != config["headers"]:
            raise ValueError(f"header mismatch: {task_id}")
    manifest = report["tasks"][task_id]["manifest"]
    splits = manifest["splits"]

    def data(split: str) -> dict:
        indices = splits[split]["row_indices"]
        selected = [[float(row[name]) for name in config["headers"]] for row in (rows[i] for i in indices)]
        return {
            "split_name": split,
            "split_sha256": splits[split]["data_sha256"],
            "X": [values[:-1] for values in selected],
            "y": [values[-1] for values in selected],
        }

    return data("fit_dev"), data("check_dev"), manifest


def _structure(task_id: str, features: list[str], n_inputs: int) -> dict:
    spec = make_spec(n_inputs, len(features))
    payload = {"feature_ids": features, "explanation": "Researcher-fixed preflight structure."}
    compiled = compile_submission(payload, spec)
    return {
        "source": compiled["source"],
        "source_sha256": compiled["source_sha256"],
        "n_params": compiled["n_params"],
        "feature_ids": compiled["feature_ids"],
    }


def run_task(task_id: str, config: dict, report: dict) -> dict:
    fit_data, check_data, manifest = _load_task(task_id, config, report)
    n_inputs = len(config["headers"]) - 1
    parent = _structure(task_id, config["parent"], n_inputs)
    common_features = [feature for feature in config["parent"] if feature != config["removed"]]
    common = _structure(task_id, common_features, n_inputs)
    added_features = common_features + [config["added"]]
    added = _structure(task_id, added_features, n_inputs)
    structures = {"parent": parent, "common": common, "added": added}
    binding = {
        "task_id": task_id,
        "split_id": manifest["allocation"]["version"],
        "fit_data_sha256": manifest["splits"]["fit_dev"]["data_sha256"],
        "check_data_sha256": manifest["splits"]["check_dev"]["data_sha256"],
        "parent_source_sha256": parent["source_sha256"],
        "common_source_sha256": common["source_sha256"],
        "added_source_sha256": added["source_sha256"],
        "removed_feature_id": config["removed"],
        "added_feature_id": config["added"],
        "parent_feature_ids": list(config["parent"]),
        "fit_protocol_sha256": _digest({"optimizer": "scipy.least_squares", "initial_params": "ones",
                                         "runtime": "symbolic-diagnostic-v01"}),
        "metric_scope": "check_dev_nmse_population_variance",
    }
    result = evaluate_triplet(
        structures=structures,
        fit_data=fit_data,
        check_data=check_data,
        task_id=task_id,
        input_names=config["headers"][:-1],
        binding=binding,
        fit_runner=sandbox_call,
        predict_runner=sandbox_call,
    )
    return {
        "task_id": task_id,
        "status": "preflight_only",
        "official_test_read": False,
        "official_test_ood_read": False,
        "fit_split_sha256": result["fit_split_sha256"],
        "check_split_sha256": result["check_split_sha256"],
        "fit_statuses": {key: value["status"] for key, value in result["fit_records"].items()},
        "predict_statuses": {key: value["status"] for key, value in result["predict_records"].items()},
        "phase_order": result["phase_order"],
        "evidence": {
            "status": result["evidence"]["status"],
            "decision_reason": result["evidence"]["decision_reason"],
            "ratio": result["evidence"]["ratio"],
        },
        "source_hashes": {key: value["source_sha256"] for key, value in structures.items()},
    }


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    results = [run_task(task_id, config, report) for task_id, config in TASKS.items()]
    output = {
        "schema": "replacement-triplet-preflight-v0.1",
        "status": "passed" if all(
            all(value == "success" for value in result["fit_statuses"].values())
            and all(value == "success" for value in result["predict_statuses"].values())
            for result in results
        ) else "incomplete",
        "model_requests": 0,
        "candidate_generation": 0,
        "outcome_dev_read": False,
        "tasks": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
