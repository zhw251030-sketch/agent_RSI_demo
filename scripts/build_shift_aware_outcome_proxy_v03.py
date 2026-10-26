#!/usr/bin/env python3
"""Build labeled train-only proxy fixtures for shift outcome replay.

The fixture applies the frozen v02 input transformation to outcome_dev_v2
rows and carries their original targets for development diagnostics.  It is
explicitly not an OOD benchmark and rejects official-test sources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.replacement_evidence.shift_gate import _canonical, _sha256
from scripts.build_shift_aware_dev_v02 import TASK_FILES, _fixture_rows, _read


SOURCE_SPLIT = "outcome_dev_v2"


def build_task_proxy_fixture(
    task_id: str,
    headers: list[str],
    rows: list[dict[str, str]],
    source_row_indices: list[int],
    profile: dict[str, Any],
    *,
    source_split: str = SOURCE_SPLIT,
) -> dict[str, Any]:
    """Return one deterministic labeled proxy fixture for a train-only split."""

    if source_split != SOURCE_SPLIT:
        if source_split.startswith("official_test"):
            raise ValueError("official test sources are forbidden")
        raise ValueError("source_split must be outcome_dev_v2")
    if not source_row_indices:
        raise ValueError("source_row_indices must be nonempty")
    if any(index < 0 or index >= len(rows) for index in source_row_indices):
        raise ValueError("source row index is out of bounds")
    if len(headers) < 2 or any(set(row) != set(headers) for row in rows):
        raise ValueError("rows and headers do not match")
    target_name = headers[-1]
    fixture_id, shifted_inputs, rule = _fixture_rows(
        task_id, rows, headers, source_row_indices, profile,
    )
    targets = []
    for index in source_row_indices:
        value = float(rows[index][target_name])
        if not math.isfinite(value):
            raise ValueError("proxy target must be finite")
        targets.append(value)
    body = {
        "fixture_id": fixture_id,
        "source_split": SOURCE_SPLIT,
        "source_row_indices": list(source_row_indices),
        "source_row_indices_sha256": _sha256(_canonical(list(source_row_indices))),
        "input_names": list(headers[:-1]),
        "X": shifted_inputs,
        "y": targets,
        "rule": rule,
        "target_source": "outcome_dev_v2 target rows",
        "not_benchmark": True,
    }
    body["fixture_sha256"] = _sha256(_canonical(body))
    return body


def build_report(repo_root: Path, shift_report_path: Path) -> dict[str, Any]:
    shift_report = json.loads(shift_report_path.read_text(encoding="utf-8"))
    if shift_report.get("official_test_read") or shift_report.get("official_test_ood_read"):
        raise ValueError("shift report claims official holdout access")
    tasks: dict[str, dict[str, Any]] = {}
    for task_id, relative in TASK_FILES.items():
        if "test" in str(relative).lower():
            raise ValueError("official test path in proxy source")
        headers, rows, source_sha, _ = _read(repo_root / relative)
        entry = shift_report["tasks"][task_id]
        indices = entry["manifest"]["splits"]["outcome_dev"]["row_indices"]
        fixture = build_task_proxy_fixture(
            task_id, headers, rows, indices, entry["profile"],
        )
        fixture["profile_sha256"] = entry["profile"]["profile_sha256"]
        fixture["source_data_sha256"] = source_sha
        tasks[task_id] = fixture
    report: dict[str, Any] = {
        "schema": "replacement-shift-aware-outcome-proxy-v03",
        "status": "frozen_train_only_outcome_proxy",
        "source_split": SOURCE_SPLIT,
        "target_source": "outcome_dev_v2 target rows reused after input-only transform",
        "not_benchmark": True,
        "official_test_read": False,
        "official_test_ood_read": False,
        "tasks": tasks,
    }
    report["report_sha256"] = _sha256(_canonical(report))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--shift-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.repo_root, args.shift_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "source_split": report["source_split"],
        "not_benchmark": report["not_benchmark"],
        "report_sha256": report["report_sha256"],
        "tasks": {task: {"rows": len(value["y"]), "fixture_id": value["fixture_id"]}
                  for task, value in report["tasks"].items()},
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
