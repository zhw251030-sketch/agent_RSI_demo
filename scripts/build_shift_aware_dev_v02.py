#!/usr/bin/env python3
"""Build train-only split and synthetic input-shift metadata for v02.

The synthetic shift fixtures transform inputs only.  Targets are deliberately
excluded because this artifact calibrates a host-side coverage diagnostic, not
task performance on a fabricated benchmark.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from statistics import fmean

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.replacement_evidence.dev_splits import build_split_manifest
from analysis.replacement_evidence.shift_gate import build_profile, score_batch


TASK_FILES = {
    "bactgrow": Path("data/symbolic/llm-sr/bactgrow/train.csv"),
    "stressstrain": Path("data/symbolic/llm-sr/stressstrain/train.csv"),
    "oscillator1": Path("data/symbolic/llm-sr/oscillator1/train.csv"),
    "oscillator2": Path("data/symbolic/llm-sr/oscillator2/train.csv"),
}
SPLIT_VERSION = "replacement-shift-aware-v02"
FIXTURE_ROWS = 256


def _sha(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _read(path: Path) -> tuple[list[str], list[dict[str, str]], str, int]:
    raw = path.read_bytes()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or ())
        rows = list(reader)
    if not headers or not rows:
        raise ValueError(f"empty or headerless CSV: {path}")
    for index, row in enumerate(rows):
        if set(row) != set(headers):
            raise ValueError(f"row {index} headers mismatch in {path}")
        for name in headers:
            value = float(row[name])
            if not math.isfinite(value):
                raise ValueError(f"nonfinite value in {path} row {index} column {name}")
    return headers, rows, _sha(raw), len(raw)


def _input_rows(rows: list[dict[str, str]], headers: list[str], indices: list[int]) -> list[list[float]]:
    return [[float(rows[index][name]) for name in headers[:-1]] for index in indices]


def _fixture_rows(task_id: str, rows: list[dict[str, str]], headers: list[str], indices: list[int], profile: dict) -> tuple[str, list[list[float]], dict]:
    names = headers[:-1]
    base = _input_rows(rows, headers, indices)
    means = {name: profile["stats"][name]["mean"] for name in names}
    transformed = [list(row) for row in base]
    if task_id == "bactgrow":
        # Expand the continuous input support around fit_dev_v2 means.
        transformed = [[means[name] + 1.8 * (value - means[name])
                        for name, value in zip(names, row)] for row in base]
        rule = {"kind": "range_expand", "factor": 1.8, "features": names}
        fixture_id = "bactgrow-range-expand-v01"
    elif task_id == "stressstrain":
        # Collapse the condition variable to its fit median while retaining
        # the observed strain values; this models a single-condition domain.
        temp_index = names.index("temp")
        temp_value = profile["stats"]["temp"]["mean"]
        for row in transformed:
            row[temp_index] = temp_value
        rule = {"kind": "condition_collapse", "feature": "temp", "value": temp_value}
        fixture_id = "stressstrain-condition-collapse-v01"
    elif task_id == "oscillator1":
        transformed = [[means[name] + 1.8 * (value - means[name])
                        for name, value in zip(names, row)] for row in base]
        rule = {"kind": "range_expand", "factor": 1.8, "features": names}
        fixture_id = "oscillator1-range-expand-v01"
    elif task_id == "oscillator2":
        time_index = names.index("t")
        for row in transformed:
            row[time_index] = row[time_index] - 30.0
        rule = {"kind": "time_window_shift", "feature": "t", "offset": -30.0}
        fixture_id = "oscillator2-time-shift-v01"
    else:
        raise ValueError(f"unknown task: {task_id}")
    return fixture_id, transformed, rule


def build_report(repo_root: Path) -> dict:
    tasks: dict[str, dict] = {}
    for task_id, relative in TASK_FILES.items():
        path = repo_root / relative
        headers, rows, source_sha, source_bytes = _read(path)
        manifest = build_split_manifest(
            task_id=task_id, headers=headers, rows=rows,
            data_sha256=source_sha, version=SPLIT_VERSION,
        )
        fit_indices = manifest["splits"]["fit_dev"]["row_indices"]
        check_indices = manifest["splits"]["check_dev"]["row_indices"]
        selected = fit_indices[: min(FIXTURE_ROWS, len(fit_indices))]
        input_names = headers[:-1]
        fit_inputs = _input_rows(rows, headers, fit_indices)
        check_inputs = _input_rows(rows, headers, check_indices)
        profile = build_profile(fit_inputs, input_names)
        fixture_id, shifted_inputs, rule = _fixture_rows(task_id, rows, headers, selected, profile)
        baseline_score = score_batch(profile, check_inputs)
        shifted_score = score_batch(profile, shifted_inputs)
        tasks[task_id] = {
            "source_path": str(relative).replace("\\", "/"),
            "source_sha256": source_sha,
            "source_bytes": source_bytes,
            "row_count": len(rows),
            "headers": headers,
            "input_names": input_names,
            "manifest": manifest,
            "profile": profile,
            "synthetic_shift_dev": {
                "fixture_id": fixture_id,
                "source_split": "fit_dev",
                "source_row_indices": selected,
                "source_row_indices_sha256": _sha(json.dumps(selected, separators=(",", ":"))),
                "target_included": False,
                "rule": rule,
                "baseline_check_score": baseline_score,
                "shifted_input_score": shifted_score,
                "shifted_input_sha256": _sha(json.dumps(shifted_inputs, separators=(",", ":"))),
            },
        }
    report = {
        "schema": "replacement-shift-aware-dev-report-v0.1",
        "status": "frozen_train_only_shift_design",
        "split_version": SPLIT_VERSION,
        "official_test_read": False,
        "official_test_ood_read": False,
        "target_values_read_for_shift": False,
        "tasks": tasks,
        "protocol": {
            "fit_split": "fit_dev_v2",
            "check_split": "check_dev_v2",
            "synthetic_split": "synthetic_shift_dev",
            "outcome_split": "outcome_dev_v2",
            "fixture_rows_per_task": FIXTURE_ROWS,
            "purpose": "host-only input coverage preflight; not benchmark performance",
        },
    }
    report["report_sha256"] = _sha(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "report_sha256": report["report_sha256"],
        "official_test_read": report["official_test_read"],
        "official_test_ood_read": report["official_test_ood_read"],
        "tasks": {task: {
            "rows": value["row_count"],
            "manifest_sha256": value["manifest"]["manifest_sha256"],
            "fixture_id": value["synthetic_shift_dev"]["fixture_id"],
            "baseline_status": value["synthetic_shift_dev"]["baseline_check_score"]["status"],
            "shifted_status": value["synthetic_shift_dev"]["shifted_input_score"]["status"],
        } for task, value in report["tasks"].items()},
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

