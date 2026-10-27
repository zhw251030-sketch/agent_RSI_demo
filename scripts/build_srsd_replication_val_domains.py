#!/usr/bin/env python3
"""Freeze train-referenced validation domains for the independent replication round."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.replacement_evidence.external_replication_task_config import REPLICATION_TASK_DEFINITIONS
from scripts.build_srsd_easy_val_domains import build_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--dev-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-block-rows", type=int, default=32)
    args = parser.parse_args()
    report = build_report(args.repo_root, args.dev_report, min_rows=args.min_block_rows,
                          definitions=REPLICATION_TASK_DEFINITIONS,
                          schema="replacement-srsd-feynman-replication-val-domain-v05")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report_sha256": report["report_sha256"],
                      "tasks": {task: {"val_rows": value["val_row_count"],
                                        "valid_blocks": sum(bool(block["valid"]) for block in value["blocks"]),
                                        "total_blocks": len(value["blocks"])}
                                for task, value in report["tasks"].items()}},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
