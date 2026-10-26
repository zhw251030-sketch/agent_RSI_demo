#!/usr/bin/env python3
"""Build train-only natural domain blocks for v04 outcome validation."""

from __future__ import annotations

import argparse
import bisect
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

from scripts.build_shift_aware_dev_v02 import TASK_FILES, _read


MIN_BLOCK_ROWS = 32
QUANTILE_BINS = 5
QUANTILES = tuple(index / QUANTILE_BINS for index in range(1, QUANTILE_BINS))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("value must be finite")
    return number


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def build_feature_rule(values: list[float], *, max_exact_levels: int = 16) -> dict[str, Any]:
    if not values:
        raise ValueError("feature values must be nonempty")
    levels = sorted(set(float(value) for value in values))
    if len(levels) <= max_exact_levels:
        return {"kind": "exact_level", "levels": levels, "n_fit": len(values)}
    edges = [_quantile(values, q) for q in QUANTILES]
    return {
        "kind": "quantile_bins", "bins": QUANTILE_BINS,
        "quantiles": list(QUANTILES), "edges": edges, "n_fit": len(values),
    }


def assign_region(value: float, rule: dict[str, Any]) -> str:
    value = float(value)
    if rule["kind"] == "exact_level":
        return f"level:{value}" if value in rule["levels"] else "unseen"
    if rule["kind"] == "quantile_bins":
        return f"bin:{bisect.bisect_right(rule['edges'], value)}"
    raise ValueError("unknown feature rule")


def _inputs(rows: list[dict[str, str]], headers: list[str], indices: list[int]) -> list[list[float]]:
    return [[_finite(rows[index][name]) for name in headers[:-1]] for index in indices]


def _targets(rows: list[dict[str, str]], headers: list[str], indices: list[int]) -> list[float]:
    return [_finite(rows[index][headers[-1]]) for index in indices]


def build_feature_blocks(
    *,
    task_id: str,
    headers: list[str],
    rows: list[dict[str, str]],
    fit_indices: list[int],
    outcome_indices: list[int],
    source_data_sha256: str,
    min_rows: int = MIN_BLOCK_ROWS,
) -> dict[str, Any]:
    if not task_id or len(headers) < 2 or not fit_indices or not outcome_indices:
        raise ValueError("task, headers and split indices are required")
    if len(source_data_sha256) != 64:
        raise ValueError("source_data_sha256 must be a SHA-256 digest")
    if isinstance(min_rows, bool) or not isinstance(min_rows, int) or min_rows < 1:
        raise ValueError("min_rows must be positive")
    names = headers[:-1]
    rules = {
        name: build_feature_rule(
            [_finite(rows[index][name]) for index in fit_indices]
        )
        for name in names
    }
    ordinary_X = _inputs(rows, headers, outcome_indices)
    ordinary_y = _targets(rows, headers, outcome_indices)
    blocks: list[dict[str, Any]] = []
    for column, name in enumerate(names):
        groups: dict[str, list[int]] = {}
        for index in outcome_indices:
            region = assign_region(_finite(rows[index][name]), rules[name])
            groups.setdefault(region, []).append(index)
        for region in sorted(groups):
            source_indices = sorted(groups[region])
            block_X = _inputs(rows, headers, source_indices)
            block_y = _targets(rows, headers, source_indices)
            mean = math.fsum(block_y) / len(block_y)
            variance = math.fsum((value - mean) ** 2 for value in block_y) / len(block_y)
            body = {
                "feature": name,
                "region": region,
                "valid": len(source_indices) >= min_rows,
                "n_rows": len(source_indices),
                "source_row_indices": source_indices,
                "source_row_indices_sha256": _sha256(_canonical(source_indices)),
                "X": block_X,
                "y": block_y,
                "target_variance": variance,
                "source_split": "outcome_dev_v2",
                "not_benchmark": True,
            }
            body["block_sha256"] = _sha256(_canonical(body))
            blocks.append(body)
    ordinary = {
        "source_split": "outcome_dev_v2",
        "n_rows": len(outcome_indices),
        "source_row_indices": sorted(outcome_indices),
        "source_row_indices_sha256": _sha256(_canonical(sorted(outcome_indices))),
        "X": ordinary_X,
        "y": ordinary_y,
        "target_source": "outcome_dev_v2 target rows",
        "not_benchmark": True,
    }
    ordinary["ordinary_sha256"] = _sha256(_canonical(ordinary))
    return {
        "task_id": task_id,
        "feature_names": names,
        "source_data_sha256": source_data_sha256,
        "fit_row_count": len(fit_indices),
        "outcome_row_count": len(outcome_indices),
        "rules": rules,
        "ordinary": ordinary,
        "blocks": blocks,
        "min_block_rows": min_rows,
        "not_benchmark": True,
    }


def build_report(repo_root: Path, shift_report_path: Path, *, min_rows: int = MIN_BLOCK_ROWS) -> dict[str, Any]:
    shift_report = json.loads(shift_report_path.read_text(encoding="utf-8"))
    if shift_report.get("official_test_read") or shift_report.get("official_test_ood_read"):
        raise ValueError("shift report claims official holdout access")
    tasks: dict[str, Any] = {}
    for task_id, relative in TASK_FILES.items():
        if "test" in str(relative).lower():
            raise ValueError("official test path is forbidden")
        headers, rows, source_sha, source_bytes = _read(repo_root / relative)
        manifest = shift_report["tasks"][task_id]["manifest"]
        fit_indices = manifest["splits"]["fit_dev"]["row_indices"]
        outcome_indices = manifest["splits"]["outcome_dev"]["row_indices"]
        report = build_feature_blocks(
            task_id=task_id, headers=headers, rows=rows,
            fit_indices=fit_indices, outcome_indices=outcome_indices,
            source_data_sha256=source_sha, min_rows=min_rows,
        )
        report["source_path"] = str(relative).replace("\\", "/")
        report["source_bytes"] = source_bytes
        report["manifest_sha256"] = manifest["manifest_sha256"]
        tasks[task_id] = report
    result = {
        "schema": "replacement-natural-domain-outcome-v04",
        "status": "frozen_train_only_natural_domain_blocks",
        "source_split": "outcome_dev_v2",
        "official_test_read": False,
        "official_test_ood_read": False,
        "not_benchmark": True,
        "min_block_rows": min_rows,
        "tasks": tasks,
    }
    result["report_sha256"] = _sha256(_canonical(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--shift-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-block-rows", type=int, default=MIN_BLOCK_ROWS)
    args = parser.parse_args()
    report = build_report(args.repo_root, args.shift_report, min_rows=args.min_block_rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "report_sha256": report["report_sha256"],
        "official_test_read": report["official_test_read"],
        "tasks": {task: {
            "ordinary_rows": value["ordinary"]["n_rows"],
            "total_blocks": len(value["blocks"]),
            "valid_blocks": sum(block["valid"] for block in value["blocks"]),
            "min_block_rows": value["min_block_rows"],
        } for task, value in report["tasks"].items()},
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
