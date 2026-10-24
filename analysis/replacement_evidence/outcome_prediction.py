"""Fixed-parameter prediction adapter for the post-freeze outcome split."""

from __future__ import annotations

from numbers import Real
from typing import Any, Callable, Mapping

from rsi_eval.symbolic import score_predictions


def run_outcome_prediction(*, source: str, params: list[Any], X: list[list[Any]], y: list[Any],
                           task_id: str, input_names: list[str], split_sha256: str,
                           runner: Callable[[str, dict[str, Any]], Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(source, str) or not source:
        raise ValueError("source must be nonempty")
    if not isinstance(params, list) or not params or any(isinstance(v, bool) or not isinstance(v, Real) for v in params):
        raise ValueError("params must be numeric")
    if not isinstance(split_sha256, str) or len(split_sha256) != 64:
        raise ValueError("split_sha256 must be a SHA-256 digest")
    if not callable(runner):
        raise ValueError("runner must be callable")
    request = {
        "family": "symbolic", "X": X, "task_id": task_id,
        "input_names": input_names, "phase": "predict",
        "split_name": "outcome_dev", "split_sha256": split_sha256,
        "params": list(params),
    }
    if "y" in request:
        raise AssertionError("outcome prediction request must omit targets")
    try:
        response = runner(source, request)
    except BaseException as exc:
        return {"status": "failed", "reason": f"runner_exception:{type(exc).__name__}"}
    if response.get("status") != "completed" or not isinstance(response.get("result"), Mapping):
        return {"status": "failed", "reason": "runner_status"}
    result = response["result"]
    if result.get("status") != "success":
        return {"status": "failed", "reason": "prediction_status"}
    score = score_predictions(y, result.get("predictions"))
    if score.get("status") != "success":
        return {"status": "failed", "reason": "metric_unavailable"}
    return {"status": "success", "metrics": score["metrics"]}

