"""Run one fixed-parameter prediction on ``check_dev``.

The fit step is intentionally absent.  Callers must provide parameters already
produced by a fit on ``fit_dev`` and a runner that executes only the prediction
phase in the locked candidate runtime.  The trusted host scores predictions and
records the split binding.
"""

from __future__ import annotations

import hashlib
import json
import math
from numbers import Real
from typing import Any, Callable, Mapping

from rsi_eval.symbolic import score_predictions


VERSION = "replacement-fixed-prediction-v0.1"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _sha256(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _check_hash(value: Any, name: str) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in value)):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return value.lower()


def run_fixed_prediction(
    *,
    source: str,
    params: list[Any],
    X: list[list[Any]],
    y: list[Any],
    task_id: str,
    input_names: list[str],
    split_name: str,
    split_sha256: str,
    runner: Callable[[str, dict[str, Any]], Mapping[str, Any]],
) -> dict[str, Any]:
    """Execute and score a prediction with parameters fixed before the call."""

    if split_name != "check_dev":
        raise ValueError("fixed replacement evidence may only score check_dev")
    split_digest = _check_hash(split_sha256, "split_sha256")
    if not isinstance(source, str) or not source:
        raise ValueError("source must be nonempty text")
    if not isinstance(params, list) or not params:
        raise ValueError("params must be a nonempty finite list")
    clean_params = [_finite_number(value, "params") for value in params]
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("task_id must be nonempty text")
    if (not isinstance(input_names, list) or not input_names
            or any(not isinstance(name, str) or not name for name in input_names)
            or len(set(input_names)) != len(input_names)):
        raise ValueError("input_names must be unique nonempty names")
    if not isinstance(X, list) or not isinstance(y, list) or not X or len(X) != len(y):
        raise ValueError("X and y must be nonempty lists with equal length")
    clean_X: list[list[float]] = []
    for row in X:
        if not isinstance(row, list) or len(row) != len(input_names):
            raise ValueError("X row dimension mismatch")
        clean_X.append([_finite_number(value, "X") for value in row])
    clean_y = [_finite_number(value, "y") for value in y]
    if not callable(runner):
        raise ValueError("runner must be callable")

    request = {
        "family": "symbolic",
        "X": clean_X,
        "task_id": task_id,
        "input_names": list(input_names),
        "phase": "predict",
        "params": clean_params,
    }
    request_sha256 = _sha256(_canonical(request))
    metadata = {
        "schema": VERSION,
        "split_name": split_name,
        "split_sha256": split_digest,
        "target_present": False,
        "request_sha256": request_sha256,
        "n_rows": len(clean_X),
        "n_params": len(params),
        "request": {
            "phase": "predict",
            "task_id": task_id,
            "target_present": False,
            "n_rows": len(clean_X),
            "n_params": len(params),
        },
    }
    try:
        response = runner(source, request)
    except BaseException as exc:
        return {**metadata, "status": "prediction_failed",
                "error": f"runner_exception:{type(exc).__name__}"}
    if not isinstance(response, Mapping):
        return {**metadata, "status": "prediction_failed", "error": "invalid_runner_response"}
    if response.get("status") != "completed":
        return {**metadata, "status": "prediction_failed",
                "error": f"runner_status:{response.get('status')}"}
    result = response.get("result")
    if not isinstance(result, Mapping) or result.get("status") != "success":
        return {**metadata, "status": "prediction_failed", "error": "invalid_prediction_result"}
    predictions = result.get("predictions")
    scored = score_predictions(clean_y, predictions)
    if scored.get("status") != "success":
        return {**metadata, "status": "metric_unavailable", "score": scored}
    return {**metadata, "status": "success", "metrics": scored["metrics"]}
