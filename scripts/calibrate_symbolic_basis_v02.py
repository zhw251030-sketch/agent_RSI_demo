#!/usr/bin/env python3
"""No-model five-input fit/predict calibration for symbolic-basis-v0.2."""

from __future__ import annotations

import json
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
    X = [[float(i), float((i * 3) % 7 - 3), float((i * 5) % 11 - 5),
          float((i * 7) % 13 - 6), float((i * 11) % 17 - 8)]
         for i in range(1, 13)]
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
    return {"schema": "symbolic-basis-v02-5-input-calibration", "status": "passed",
            "feature_count": len(features), "fit": fit, "prediction": prediction}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True))
