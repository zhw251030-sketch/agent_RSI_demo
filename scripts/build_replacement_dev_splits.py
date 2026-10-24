#!/usr/bin/env python3
"""Build the train-only replacement-protocol split manifest.

This command reads exactly the two public ``train.csv`` files.  It never opens
test, OOD, or sealed paths and stores row indices/statistics rather than raw
data in the report.
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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis.replacement_evidence.dev_splits import build_split_manifest


TASK_FILES = {
    "bactgrow": Path("data/symbolic/llm-sr/bactgrow/train.csv"),
    "stressstrain": Path("data/symbolic/llm-sr/stressstrain/train.csv"),
}
TARGETS = {"bactgrow": "db", "stressstrain": "stress"}


def _quantiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)

    def nearest_rank(probability: float) -> float:
        index = min(len(ordered) - 1, max(0, math.ceil(probability * len(ordered)) - 1))
        return ordered[index]

    return {f"p{int(probability * 100)}": nearest_rank(probability) for probability in (0, 0.25, 0.5, 0.75, 1)}


def _audit(task_id: str, rows: list[dict[str, str]], manifest: dict) -> dict:
    target = TARGETS[task_id]
    result: dict[str, object] = {}
    for split in manifest["split_order"]:
        indices = manifest["splits"][split]["row_indices"]
        split_rows = [rows[index] for index in indices]
        numeric: dict[str, dict[str, object]] = {}
        for name in rows[0]:
            values = [float(row[name]) for row in split_rows]
            numeric[name] = {
                "min": min(values),
                "max": max(values),
                "mean": fmean(values),
                "quantiles": _quantiles(values),
            }
        split_audit: dict[str, object] = {
            "n": len(indices),
            "numeric": numeric,
            "target": target,
        }
        if task_id == "stressstrain":
            counts: dict[str, int] = {}
            for row in split_rows:
                counts[row["temp"]] = counts.get(row["temp"], 0) + 1
            split_audit["temp_counts"] = dict(sorted(counts.items()))
        result[split] = split_audit
    return result


def build_report(repo_root: Path) -> dict:
    tasks: dict[str, object] = {}
    for task_id, relative_path in TASK_FILES.items():
        path = repo_root / relative_path
        raw = path.read_bytes()
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            headers = reader.fieldnames
        if headers is None:
            raise ValueError(f"missing CSV headers: {path}")
        manifest = build_split_manifest(
            task_id=task_id,
            headers=headers,
            rows=rows,
            data_sha256=hashlib.sha256(raw).hexdigest(),
        )
        tasks[task_id] = {
            "source_path": str(relative_path).replace("\\", "/"),
            "source_bytes": len(raw),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "row_count": len(rows),
            "manifest": manifest,
            "audit": _audit(task_id, rows, manifest),
        }
    report = {
        "schema": "replacement-dev-split-report-v0.1",
        "status": "frozen_train_only_split_manifest",
        "official_test_read": False,
        "official_test_ood_read": False,
        "tasks": tasks,
    }
    report["report_sha256"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report_sha256": report["report_sha256"], "tasks": {
        task: {
            "rows": item["row_count"],
            "source_sha256": item["source_sha256"],
            "split_counts": item["manifest"]["split_counts"],
            "manifest_sha256": item["manifest"]["manifest_sha256"],
        } for task, item in report["tasks"].items()
    }}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
