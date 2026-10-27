#!/usr/bin/env python3
"""Freeze train-only fit/check/outcome manifests for SRSD-Feynman Easy."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.replacement_evidence.dev_splits import build_generic_split_manifest
from analysis.replacement_evidence.external_task_config import EXTERNAL_TASK_DEFINITIONS


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_report(repo_root: Path, source_report_path: Path, *, definitions=EXTERNAL_TASK_DEFINITIONS,
                 schema: str = "replacement-srsd-feynman-easy-dev-v05",
                 split_version: str = "srsd-feynman-easy-v05") -> dict:
    source_report = json.loads(source_report_path.read_text(encoding="utf-8"))
    if source_report.get("official_test_read") or source_report.get("official_test_ood_read"):
        raise ValueError("source report claims official holdout access")
    definitions = {item.task_id: item for item in definitions}
    if set(source_report.get("tasks", {})) != set(definitions):
        raise ValueError("source report task set differs from frozen external protocol")
    tasks = {}
    for task_id, definition in definitions.items():
        record = source_report["tasks"][task_id]
        if record["files"]["test"].get("read"):
            raise ValueError("external test file must remain unread during development freeze")
        train_record = record["files"]["train"]
        path = repo_root / train_record["csv_path"]
        raw = path.read_bytes()
        source_sha = _sha(raw)
        if source_sha != train_record["csv_sha256"]:
            raise ValueError(f"{task_id} train CSV hash mismatch")
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            headers = tuple(reader.fieldnames or ())
            rows = list(reader)
        if headers != definition.headers:
            raise ValueError(f"{task_id} train headers mismatch")
        manifest = build_generic_split_manifest(
            task_id=task_id,
            headers=headers,
            rows=rows,
            data_sha256=source_sha,
            target=definition.target,
            strata_names=("target_decile",),
            version=split_version,
        )
        tasks[task_id] = {
            "source_path": train_record["csv_path"],
            "source_sha256": source_sha,
            "row_count": len(rows),
            "headers": list(headers),
            "equation": record["equation"],
            "source_id": record["source_id"],
            "val_path": record["files"]["val"].get("csv_path"),
            "val_sha256": record["files"]["val"].get("csv_sha256"),
            "official_test_url": record["files"]["test"]["url"],
            "manifest": manifest,
        }
    result = {
        "schema": schema,
        "status": "frozen_train_only_external_development",
        "source_dataset": source_report["dataset"],
        "source_report_sha256": source_report["manifest_sha256"],
        "source_license": source_report["source_license"],
        "official_test_read": False,
        "official_test_ood_read": False,
        "not_benchmark": True,
        "tasks": tasks,
    }
    result["report_sha256"] = _sha(_canonical(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.repo_root, args.source_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "report_sha256": report["report_sha256"],
        "official_test_read": report["official_test_read"],
        "tasks": {task: value["row_count"] for task, value in report["tasks"].items()},
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
