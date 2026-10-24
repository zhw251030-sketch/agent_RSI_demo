"""Fit three related symbolic structures and produce bound check evidence."""

from __future__ import annotations

import copy
import math
from collections.abc import Callable, Mapping
from typing import Any

from .fixed_prediction import run_fixed_prediction
from ..basis_edit_comparison.replacement_evidence import compute_replacement_evidence


VERSION = "replacement-triplet-runner-v0.1"
STRUCTURE_ORDER = ("parent", "common", "added")


def _digest(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("split hash must be a SHA-256 hex digest")
    if any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError("split hash must be a SHA-256 hex digest")
    return value.lower()


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _validate_data(data: Mapping[str, Any], expected_split: str) -> dict[str, Any]:
    if not isinstance(data, Mapping) or data.get("split_name") != expected_split:
        raise ValueError(f"data must be bound to {expected_split}")
    split_sha256 = _digest(data.get("split_sha256"))
    X = data.get("X")
    y = data.get("y")
    if not isinstance(X, list) or not X or not isinstance(y, list) or len(X) != len(y):
        raise ValueError(f"{expected_split} data dimensions are invalid")
    clean_X = []
    for row in X:
        if not isinstance(row, list) or not row:
            raise ValueError(f"{expected_split} input row is invalid")
        clean_X.append([_number(value, f"{expected_split}.X") for value in row])
    clean_y = [_number(value, f"{expected_split}.y") for value in y]
    return {"split_name": expected_split, "split_sha256": split_sha256,
            "X": clean_X, "y": clean_y}


def _unknown(reason: str, *, binding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "replacement-evidence-v0.1",
        "status": "unknown",
        "decision_reason": reason,
        "binding": copy.deepcopy(dict(binding)),
        "metric_scope": "check_dev_nmse_population_variance",
        "common_nmse": None,
        "parent_nmse": None,
        "added_nmse": None,
        "deletion_loss": None,
        "restoration_gain": None,
        "ratio": None,
        "tolerance": 1e-5,
        "denominator_floor": 1e-8,
        "ratio_threshold": 1.0,
    }


def _fit_record(response: Mapping[str, Any], n_params: int) -> dict[str, Any]:
    if not isinstance(response, Mapping) or response.get("status") != "completed":
        return {"status": "failed", "reason": "fit_runner_status"}
    result = response.get("result")
    if not isinstance(result, Mapping) or result.get("status") != "success":
        return {"status": "failed", "reason": "fit_result_status"}
    params = result.get("params")
    if (not isinstance(params, list) or len(params) != n_params
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(float(value)) for value in params)):
        return {"status": "failed", "reason": "invalid_fit_params"}
    return {"status": "success", "params": [float(value) for value in params],
            "nfev": result.get("nfev"), "candidate_calls": result.get("candidate_calls")}


def evaluate_triplet(
    *,
    structures: Mapping[str, Mapping[str, Any]],
    fit_data: Mapping[str, Any],
    check_data: Mapping[str, Any],
    task_id: str,
    input_names: list[str],
    binding: Mapping[str, Any],
    fit_runner: Callable[[str, dict[str, Any]], Mapping[str, Any]],
    predict_runner: Callable[[str, dict[str, Any]], Mapping[str, Any]],
) -> dict[str, Any]:
    """Run the protocol's fit-then-fixed-predict order for one edit."""

    fit = _validate_data(fit_data, "fit_dev")
    check = _validate_data(check_data, "check_dev")
    if not isinstance(input_names, list) or not input_names:
        raise ValueError("input_names must be a nonempty list")
    if not callable(fit_runner) or not callable(predict_runner):
        raise ValueError("fit_runner and predict_runner must be callable")
    if not isinstance(structures, Mapping) or set(structures) != set(STRUCTURE_ORDER):
        raise ValueError("structures must contain parent, common and added")
    for label in STRUCTURE_ORDER:
        structure = structures[label]
        if (not isinstance(structure, Mapping) or not isinstance(structure.get("source"), str)
                or not structure["source"] or not isinstance(structure.get("source_sha256"), str)
                or not isinstance(structure.get("n_params"), int) or structure["n_params"] < 1):
            raise ValueError(f"invalid {label} structure")
        _digest(structure["source_sha256"])
    if fit["split_sha256"] != str(binding.get("fit_data_sha256", "")).lower():
        raise ValueError("fit_data_sha256 does not match fit_dev")
    if check["split_sha256"] != str(binding.get("check_data_sha256", "")).lower():
        raise ValueError("check_data_sha256 does not match check_dev")
    for label in STRUCTURE_ORDER:
        binding_field = f"{label}_source_sha256"
        if structures[label]["source_sha256"].lower() != binding.get(binding_field, "").lower():
            raise ValueError(f"binding source hash mismatch for {label}")

    fit_records: dict[str, dict[str, Any]] = {}
    # All three fit requests are completed before any check prediction begins.
    for label in STRUCTURE_ORDER:
        structure = structures[label]
        request = {
            "family": "symbolic", "task_id": task_id, "input_names": list(input_names),
            "phase": "fit", "split_name": "fit_dev", "split_sha256": fit["split_sha256"],
            "X": fit["X"], "y": fit["y"], "n_params": structure["n_params"],
        }
        try:
            response = fit_runner(structure["source"], request)
        except BaseException:
            fit_records[label] = {"status": "failed", "reason": "fit_runner_exception"}
            continue
        fit_records[label] = _fit_record(response, structure["n_params"])

    predict_records: dict[str, dict[str, Any]] = {}
    for label in STRUCTURE_ORDER:
        record = fit_records[label]
        if record["status"] != "success":
            predict_records[label] = {"status": "not_run", "reason": "fit_failure"}
            continue
        structure = structures[label]
        predict_records[label] = run_fixed_prediction(
            source=structure["source"], params=record["params"], X=check["X"], y=check["y"],
            task_id=task_id, input_names=list(input_names), split_name="check_dev",
            split_sha256=check["split_sha256"], runner=predict_runner,
        )

    fit_statuses = {label: fit_records[label]["status"] for label in STRUCTURE_ORDER}
    if any(status != "success" for status in fit_statuses.values()):
        evidence = _unknown("fit_failure", binding=binding)
    elif any(predict_records[label].get("status") != "success" for label in STRUCTURE_ORDER):
        evidence = _unknown("prediction_failure", binding=binding)
    else:
        evidence = compute_replacement_evidence(
            common_nmse=predict_records["common"]["metrics"]["nmse"],
            parent_nmse=predict_records["parent"]["metrics"]["nmse"],
            added_nmse=predict_records["added"]["metrics"]["nmse"],
            fit_statuses=fit_statuses, binding=binding,
        )
    return {
        "schema": VERSION,
        "phase_order": ["fit_dev", "check_dev"],
        "fit_split_sha256": fit["split_sha256"],
        "check_split_sha256": check["split_sha256"],
        "fit_records": fit_records,
        "predict_records": predict_records,
        "evidence": evidence,
    }
