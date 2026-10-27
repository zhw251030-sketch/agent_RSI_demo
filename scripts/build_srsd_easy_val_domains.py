#!/usr/bin/env python3
"""Freeze train-referenced natural-domain blocks on SRSD validation rows."""

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

from analysis.replacement_evidence.external_task_config import EXTERNAL_TASK_DEFINITIONS
from scripts.build_natural_domain_v04 import assign_region, build_feature_rule


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _read(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]], str]:
    raw = path.read_bytes()
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = tuple(reader.fieldnames or ())
        rows = list(reader)
    if not rows or len(headers) < 2:
        raise ValueError(f"invalid CSV: {path}")
    return headers, rows, _sha(raw)


def _float(value: str) -> float:
    result = float(value)
    if not (result == result and abs(result) != float("inf")):
        raise ValueError("non-finite value")
    return result


def build_task_report(*, task_id: str, definition, train_path: Path, val_path: Path,
                      fit_indices: list[int], min_rows: int = 32) -> dict:
    train_headers, train_rows, train_sha = _read(train_path)
    val_headers, val_rows, val_sha = _read(val_path)
    if train_headers != definition.headers or val_headers != definition.headers:
        raise ValueError(f"{task_id} headers mismatch")
    if not fit_indices or max(fit_indices) >= len(train_rows):
        raise ValueError(f"{task_id} fit indices invalid")
    names = list(definition.input_names)
    rules = {
        name: build_feature_rule([_float(train_rows[index][name]) for index in fit_indices])
        for name in names
    }
    ordinary_indices = list(range(len(val_rows)))
    blocks = []
    for name in names:
        grouped: dict[str, list[int]] = {}
        for index in ordinary_indices:
            region = assign_region(_float(val_rows[index][name]), rules[name])
            grouped.setdefault(region, []).append(index)
        for region, indices in sorted(grouped.items()):
            X = [[_float(val_rows[index][column]) for column in names] for index in indices]
            y = [_float(val_rows[index][definition.target]) for index in indices]
            mean = sum(y) / len(y)
            variance = sum((value - mean) ** 2 for value in y) / len(y)
            body = {
                "feature": name, "region": region,
                "valid": len(indices) >= min_rows and variance > 0.0,
                "n_rows": len(indices), "source_row_indices": indices,
                "source_row_indices_sha256": _sha(_canonical(indices)),
                "X": X, "y": y, "target_variance": variance,
                "source_split": "val_external", "not_benchmark": True,
            }
            body["block_sha256"] = _sha(_canonical(body))
            blocks.append(body)
    ordinary = {
        "source_split": "val_external", "n_rows": len(ordinary_indices),
        "source_row_indices": ordinary_indices,
        "source_row_indices_sha256": _sha(_canonical(ordinary_indices)),
        "X": [[_float(row[column]) for column in names] for row in val_rows],
        "y": [_float(row[definition.target]) for row in val_rows],
        "not_benchmark": True,
    }
    ordinary["ordinary_sha256"] = _sha(_canonical(ordinary))
    return {
        "task_id": task_id, "feature_names": names,
        "train_source_sha256": train_sha, "val_source_sha256": val_sha,
        "fit_row_count": len(fit_indices), "val_row_count": len(val_rows),
        "rules": rules, "ordinary": ordinary, "blocks": blocks,
        "min_block_rows": min_rows, "not_benchmark": True,
    }


def build_report(repo_root: Path, dev_report_path: Path, *, min_rows: int = 32,
                 definitions=EXTERNAL_TASK_DEFINITIONS,
                 schema: str = "replacement-srsd-feynman-easy-val-domain-v05") -> dict:
    dev = json.loads(dev_report_path.read_text(encoding="utf-8"))
    if dev.get("official_test_read") or dev.get("official_test_ood_read"):
        raise ValueError("development report claims official holdout access")
    definitions = {task.task_id: task for task in definitions}
    tasks = {}
    for task_id, definition in definitions.items():
        entry = dev["tasks"][task_id]
        manifest = entry["manifest"]
        train_path = repo_root / entry["source_path"]
        val_path = repo_root / entry["val_path"]
        task_report = build_task_report(
            task_id=task_id, definition=definition, train_path=train_path,
            val_path=val_path, fit_indices=manifest["splits"]["fit_dev"]["row_indices"],
            min_rows=min_rows,
        )
        if task_report["train_source_sha256"] != entry["source_sha256"]:
            raise ValueError(f"{task_id} train hash mismatch")
        if task_report["val_source_sha256"] != entry["val_sha256"]:
            raise ValueError(f"{task_id} val hash mismatch")
        task_report["manifest_sha256"] = manifest["manifest_sha256"]
        task_report["source_path"] = entry["source_path"]
        task_report["val_path"] = entry["val_path"]
        tasks[task_id] = task_report
    result = {
        "schema": schema,
        "status": "frozen_train_referenced_val_domains",
        "development_report_sha256": _sha(dev_report_path.read_bytes()),
        "source_split": "val_external",
        "official_test_read": False, "official_test_ood_read": False,
        "not_benchmark": True, "min_block_rows": min_rows, "tasks": tasks,
    }
    result["report_sha256"] = _sha(_canonical(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--dev-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-block-rows", type=int, default=32)
    args = parser.parse_args()
    report = build_report(args.repo_root, args.dev_report, min_rows=args.min_block_rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "report_sha256": report["report_sha256"],
        "official_test_read": report["official_test_read"],
        "tasks": {task: {
            "val_rows": value["val_row_count"],
            "valid_blocks": sum(bool(block["valid"]) for block in value["blocks"]),
            "total_blocks": len(value["blocks"]),
        } for task, value in report["tasks"].items()},
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
