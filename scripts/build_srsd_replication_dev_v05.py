#!/usr/bin/env python3
"""Freeze train-only manifests for the independent SRSD Easy replication round."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.replacement_evidence.external_replication_task_config import REPLICATION_TASK_DEFINITIONS
from scripts.build_srsd_easy_dev_v05 import build_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.repo_root, args.source_report,
                          definitions=REPLICATION_TASK_DEFINITIONS,
                          schema="replacement-srsd-feynman-replication-dev-v05",
                          split_version="srsd-feynman-replication-v05")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report_sha256": report["report_sha256"],
                      "tasks": {task: value["row_count"] for task, value in report["tasks"].items()}},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
