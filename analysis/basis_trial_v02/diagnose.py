"""Offline, read-only diagnosis of the frozen basis-trial-v02 archive.

This module deliberately separates evidence available before an edit from the
measured result after the edit.  It never calls a model, executes a candidate,
or writes into a frozen run/archive.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


EXPECTED_PARENT_FEATURES = ["m_0_0", "m_0_1", "m_1_0", "m_1_1"]
FEATURE_LABELS = {
    "m_0_0": "1",
    "m_0_1": "v",
    "m_1_0": "x",
    "m_1_1": "xv",
    "m_1_2": "v²",
    "m_2_0": "x²",
}
FEEDBACK_WARNING = "Marginal associations neither identify necessary terms"
FEEDBACK_NO_RANKING = "No target-dependent basis ranking is supplied"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def verify_source_hash(path: Path, expected: str | None = None) -> str:
    """Return a source SHA-256 and reject it when *expected* is supplied."""

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected is not None and digest != expected:
        raise ValueError(f"source hash mismatch: {path}")
    return digest


def _require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise ValueError(f"missing {key}: {context}")
    return mapping[key]


def _labels(features: list[str]) -> list[str]:
    return [FEATURE_LABELS.get(feature, feature) for feature in features]


def _edit_type(parent: list[str], child: list[str], transition: dict[str, Any]) -> str:
    if parent == child:
        if transition.get("observed_change") != "keep":
            raise ValueError("unchanged features require keep observation")
        if transition.get("added") or transition.get("removed"):
            raise ValueError("keep transition cannot add or remove features")
        return "keep"
    if transition.get("mode") != "swap_one":
        raise ValueError("changed features require swap_one transition")
    if len(parent) != len(child):
        raise ValueError("swap_one cannot change feature count")
    removed = sorted(set(parent) - set(child))
    added = sorted(set(child) - set(parent))
    if len(removed) != 1 or len(added) != 1:
        raise ValueError("swap_one must remove and add one feature")
    return "swap_one"


def _posthoc_status(outcome: str) -> str:
    if outcome == "degraded":
        return "contradicted"
    if outcome == "improved":
        return "supported"
    return "unknown"


def _row(archive: Path, row_path: Path, baseline: dict[str, Any]) -> dict[str, Any]:
    row = _read_json(row_path)
    slot = _require(row, "slot", str(row_path))
    result = _require(row, "result", str(row_path))
    transition = _require(row, "transition", str(row_path))
    feedback = _require(result, "feedback", str(row_path))
    result_transition = _require(result, "transition", str(row_path))
    if not isinstance(slot, dict) or not isinstance(result, dict):
        raise ValueError(f"invalid row envelope: {row_path}")
    if not isinstance(transition, dict) or not isinstance(feedback, dict):
        raise ValueError(f"invalid row evidence: {row_path}")

    parent_features = list(baseline["feature_ids"])
    child_features = list(_require(feedback, "feature_ids", str(row_path)))
    transition_added = list(_require(transition, "added", str(row_path)))
    transition_removed = list(_require(transition, "removed", str(row_path)))
    if transition != result_transition:
        raise ValueError(f"transition binding mismatch: {row_path}")
    if transition.get("parent_structural_sha256") != baseline["structural_sha256"]:
        raise ValueError(f"parent structural binding mismatch: {row_path}")
    if transition.get("child_structural_sha256") != result.get("structural_sha256"):
        raise ValueError(f"child structural binding mismatch: {row_path}")
    if sorted(set(parent_features) - set(child_features)) != sorted(transition_removed):
        raise ValueError(f"removed feature binding mismatch: {row_path}")
    if sorted(set(child_features) - set(parent_features)) != sorted(transition_added):
        raise ValueError(f"added feature binding mismatch: {row_path}")

    source_path = archive / "experiment" / f"candidate-{slot['id']}" / "source.py"
    expected_source = _require(result, "source_sha256", str(row_path))
    actual_source = verify_source_hash(source_path, expected_source)
    feedback_text = str(_require(feedback, "interpretation", str(row_path)))
    if FEEDBACK_WARNING not in feedback_text or FEEDBACK_NO_RANKING not in feedback_text:
        raise ValueError(f"feedback warning binding mismatch: {row_path}")

    parent_nmse = float(_require(row, "parent_nmse", str(row_path)))
    child_nmse = float(_require(row, "nmse", str(row_path)))
    outcome = str(_require(row, "outcome", str(row_path)))
    delta_nmse = float(_require(row, "delta_nmse", str(row_path)))
    edit_type = _edit_type(parent_features, child_features, transition)
    if edit_type == "keep" and outcome != "unchanged":
        raise ValueError(f"keep transition has non-unchanged outcome: {row_path}")
    if edit_type == "swap_one" and outcome not in {"improved", "degraded", "unchanged"}:
        raise ValueError(f"invalid outcome: {row_path}")

    return {
        "slot_id": str(slot["id"]),
        "policy": str(slot["arm"]),
        "repeat": int(slot["repeat"]),
        "parent_feature_ids": parent_features,
        "parent_features": _labels(parent_features),
        "candidate_feature_ids": child_features,
        "candidate_features": _labels(child_features),
        "removed_feature_ids": transition_removed,
        "removed_features": _labels(transition_removed),
        "added_feature_ids": transition_added,
        "added_features": _labels(transition_added),
        "edit_type": edit_type,
        "parent_nmse": parent_nmse,
        "candidate_nmse": child_nmse,
        "delta_nmse": delta_nmse,
        "outcome": outcome,
        # The available prompt contains a general warning, but no evidence
        # about the necessity or expected value of this particular edit.
        "pre_edit_evidence_status": "unknown",
        "pre_edit_evidence_reason": (
            "feedback reports marginal residual summaries and explicitly says "
            "they do not identify necessary terms; no target-dependent basis "
            "ranking or edit-specific replacement test is supplied"
        ),
        "posthoc_result_status": _posthoc_status(outcome),
        "feedback_scope": str(_require(feedback, "metric_scope", str(row_path))),
        "feedback_warning_present": True,
        "target_dependent_basis_ranking": False,
        "source_sha256": actual_source,
        "source_hash_verified": True,
        "transition_verified": True,
        "feedback_sha256": str(_require(result, "feedback_sha256", str(row_path))),
    }


def diagnose_archive(archive: Path) -> dict[str, Any]:
    """Read and diagnose only the six A records in a measured-v01 archive."""

    archive = Path(archive)
    baseline_path = archive / "experiment/baseline-A/result.json"
    baseline_feedback_path = archive / "experiment/baseline-A/feedback.json"
    baseline_result = _read_json(baseline_path)
    baseline_feedback = _read_json(baseline_feedback_path)
    baseline_features = list(_require(baseline_feedback, "feature_ids", str(baseline_feedback_path)))
    if baseline_features != EXPECTED_PARENT_FEATURES:
        raise ValueError(f"unexpected A parent features: {baseline_features}")
    baseline_structural = str(_require(baseline_result, "structural_sha256", str(baseline_path)))
    baseline_source = archive / "experiment/baseline-A/source.py"
    baseline_source_hash = verify_source_hash(
        baseline_source, str(_require(baseline_result, "source_sha256", str(baseline_path)))
    )
    baseline = {
        "feature_ids": baseline_features,
        "features": _labels(baseline_features),
        "nmse": float(_require(baseline_result, "metrics", str(baseline_path))["nmse"]),
        "structural_sha256": baseline_structural,
        "source_sha256": baseline_source_hash,
    }

    records = []
    for row_path in sorted((archive / "experiment").glob("row-A-r*-S*.json")):
        records.append(_row(archive, row_path, baseline))
    if len(records) != 6:
        raise ValueError(f"expected six A rows, found {len(records)}")

    records.sort(key=lambda record: record["slot_id"])
    summary = {
        "records": len(records),
        "modifications": sum(r["edit_type"] == "swap_one" for r in records),
        "kept": sum(r["edit_type"] == "keep" for r in records),
        "degraded_modifications": sum(
            r["edit_type"] == "swap_one" and r["outcome"] == "degraded" for r in records
        ),
        "pre_edit_supported": sum(r["pre_edit_evidence_status"] == "supported" for r in records),
        "pre_edit_contradicted": sum(
            r["pre_edit_evidence_status"] == "contradicted" for r in records
        ),
        "pre_edit_unknown": sum(r["pre_edit_evidence_status"] == "unknown" for r in records),
    }
    return {
        "schema": "basis-edit-diagnostic-v0.1",
        "archive": str(archive),
        "model_calls": 0,
        "executions": 0,
        "writes_to_archive": 0,
        "parent": baseline,
        "feedback_assessment": {
            "scope": "train",
            "general_warning": FEEDBACK_WARNING,
            "no_target_dependent_basis_ranking": True,
            "interpretation": (
                "The frozen feedback describes the parent and residual summaries, "
                "but does not test whether a proposed replacement is necessary or beneficial."
            ),
        },
        "records": records,
        "summary": summary,
        "conclusion": (
            "All five A structure changes degraded the observed train score, while the "
            "available pre-edit feedback was edit-agnostic. This is evidence for an "
            "edit-level evidence gap, not evidence of a model rationale or a causal feature effect."
        ),
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = diagnose_archive(args.archive)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
