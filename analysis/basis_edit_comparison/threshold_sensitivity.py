"""Offline sensitivity analysis for coefficient-only edit checks."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable


HARM_TOLERANCE = 1e-5


def _finite_number(value: Any, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _validate_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    if type(rows) is not list or not rows:
        raise ValueError("rows must be a nonempty list")
    required = {
        "proposal_id", "parent_id", "removed_feature_id",
        "removed_coefficient_abs", "delta_nmse",
    }
    validated = []
    for row in rows:
        if type(row) is not dict or not required.issubset(row):
            raise ValueError("each row must contain the required edit outcome fields")
        for key in ("proposal_id", "parent_id", "removed_feature_id"):
            if type(row[key]) is not str or not row[key]:
                raise ValueError(f"{key} must be a nonempty string")
        coefficient = _finite_number(row["removed_coefficient_abs"], "removed_coefficient_abs")
        delta = _finite_number(row["delta_nmse"], "delta_nmse")
        if coefficient < 0:
            raise ValueError("removed_coefficient_abs must be nonnegative")
        validated.append({
            "proposal_id": row["proposal_id"],
            "parent_id": row["parent_id"],
            "removed_feature_id": row["removed_feature_id"],
            "removed_coefficient_abs": coefficient,
            "delta_nmse": delta,
            "harmful": bool(delta > HARM_TOLERANCE),
        })
    return validated


def scan_thresholds(rows: list[dict[str, Any]], thresholds: list[float]) -> dict[str, Any]:
    """Evaluate strict ``coefficient < threshold`` policies offline.

    This function never changes a gate or re-runs a candidate. It only asks
    what the frozen candidate outcomes would imply under alternative scalar
    thresholds.
    """

    validated = _validate_rows(rows)
    if type(thresholds) is not list or not thresholds:
        raise ValueError("thresholds must be a nonempty list")
    checked_thresholds = []
    for threshold in thresholds:
        value = _finite_number(threshold, "threshold")
        if value < 0:
            raise ValueError("threshold must be nonnegative")
        checked_thresholds.append(value)

    groups: dict[tuple[str, str, float], list[dict[str, Any]]] = {}
    for row in validated:
        key = (row["parent_id"], row["removed_feature_id"], row["removed_coefficient_abs"])
        groups.setdefault(key, []).append(row)
    ambiguous_groups = []
    for (parent_id, removed_feature_id, coefficient), group in sorted(groups.items()):
        harmful = [row for row in group if row["harmful"]]
        if harmful and len(harmful) < len(group):
            ambiguous_groups.append({
                "parent_id": parent_id,
                "removed_feature_id": removed_feature_id,
                "removed_coefficient_abs": coefficient,
                "proposal_ids": [row["proposal_id"] for row in group],
                "harmful_proposal_ids": [row["proposal_id"] for row in harmful],
            })

    results = []
    for threshold in checked_thresholds:
        executed = [row for row in validated if row["removed_coefficient_abs"] < threshold]
        harmful = [row for row in validated if row["harmful"]]
        results.append({
            "threshold": threshold,
            "candidate_executions": len(executed),
            "parent_retention": len(validated) - len(executed),
            "harmful_candidates": len(harmful),
            "harmful_deployments": sum(row["harmful"] for row in executed),
            "prevented_harm": sum(
                row["harmful"] and row["removed_coefficient_abs"] >= threshold
                for row in validated
            ),
            "beneficial_deployments": sum(
                row["delta_nmse"] < -HARM_TOLERANCE for row in executed
            ),
        })
    return {
        "version": "basis-edit-threshold-sensitivity-v0.1",
        "harm_tolerance": HARM_TOLERANCE,
        "policy": "execute iff removed_coefficient_abs < threshold",
        "row_count": len(validated),
        "ambiguous_groups": ambiguous_groups,
        "thresholds": results,
    }


def rows_from_measured_run(run_dir: Path) -> list[dict[str, Any]]:
    """Extract one row per proposal from a frozen measured runner directory."""

    candidates = json.loads((run_dir / "candidates.json").read_text(encoding="utf-8"))
    shadow = json.loads((run_dir / "shadow-outcomes.json").read_text(encoding="utf-8"))
    metrics = {
        row["proposal_id"]: row for row in shadow.get("metrics", [])
        if row.get("condition") == "no_check"
    }
    rows = []
    for candidate in candidates:
        slot = candidate["slot"]
        proposal_id = slot["slot_id"]
        edit = candidate["edit"]["edit"]
        raw_result = candidate["raw_check"]["raw_result"]
        metric = metrics[proposal_id]
        removed = edit.get("removed_feature_ids", [])
        if len(removed) != 1:
            continue
        rows.append({
            "proposal_id": proposal_id,
            "parent_id": slot["parent_id"],
            "removed_feature_id": removed[0],
            "removed_coefficient_abs": raw_result["actual"],
            "delta_nmse": metric["delta_nmse"],
        })
    return rows


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = rows_from_measured_run(args.run_dir)
    coefficients = sorted({row["removed_coefficient_abs"] for row in rows})
    thresholds = sorted({
        0.0,
        0.05,
        *coefficients,
        *(value + 1e-12 for value in coefficients),
    })
    report = scan_thresholds(rows, thresholds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
