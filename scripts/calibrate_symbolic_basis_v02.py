#!/usr/bin/env python3
"""No-model five-input fit/predict calibration for symbolic-basis-v0.2."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions.symbolic_basis_v02.contract import compile_submission, make_spec
from extensions.symbolic_basis_v01.executor import check_runtime, sandbox_call


def run() -> dict:
    check_runtime()
    features = ["m_0_0_0_0_0", "m_1_0_0_0_0", "m_0_1_0_0_0", "m_0_0_1_0_0",
                "m_0_0_0_1_0", "m_0_0_0_0_1"]
    compiled = compile_submission({"feature_ids": features, "explanation": "v02 calibration"}, make_spec(5, 6))
    X = [
        [0.0, 0.0, 0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 1.0],
        [1.0, -1.0, 2.0, -2.0, 3.0],
        [-2.0, 3.0, -1.0, 1.0, -3.0],
    ]
    coefficients = [1.5, -0.75, 0.25, 2.0, -1.0, 0.5]
    y = [sum([coefficients[0], coefficients[1] * row[0], coefficients[2] * row[1],
              coefficients[3] * row[2], coefficients[4] * row[3], coefficients[5] * row[4]]) for row in X]
    fit = sandbox_call(compiled["source"], {"family": "symbolic", "task_id": "calibration/v02-5d",
        "input_names": [f"x{i}" for i in range(5)], "phase": "fit", "split_name": "calibration",
        "split_sha256": "calibration", "X": X, "y": y, "n_params": len(features)})
    params = fit.get("result", {}).get("params")
    prediction = None
    if isinstance(params, list):
        prediction = sandbox_call(compiled["source"], {"family": "symbolic", "task_id": "calibration/v02-5d",
            "input_names": [f"x{i}" for i in range(5)], "phase": "predict", "split_name": "calibration",
            "split_sha256": "calibration", "X": X, "params": params})
    predicted = prediction.get("result", {}).get("predictions") if isinstance(prediction, dict) else None
    max_abs_error = None
    if isinstance(predicted, list) and len(predicted) == len(y):
        max_abs_error = max(abs(float(a) - float(b)) for a, b in zip(predicted, y))
    expected_params = [1.5, 0.5, -1.0, 2.0, 0.25, -0.75]
    parameter_match = (isinstance(params, list) and len(params) == len(expected_params)
                       and all(math.isclose(float(actual), expected, rel_tol=1e-9, abs_tol=1e-10)
                               for actual, expected in zip(params, expected_params)))
    if not parameter_match:
        raise RuntimeError(f"v02 calibration parameters do not match canonical order: {params}")
    if max_abs_error is None or max_abs_error > 1e-8:
        raise RuntimeError(f"v02 calibration prediction error too large: {max_abs_error}")
    return {"schema": "symbolic-basis-v02-5-input-calibration", "status": "passed",
            "feature_count": len(features), "row_count": len(X),
            "expected_canonical_params": expected_params, "parameter_match": parameter_match,
            "max_abs_prediction_error": max_abs_error, "fit": fit, "prediction": prediction}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True))
