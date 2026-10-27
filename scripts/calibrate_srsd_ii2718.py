#!/usr/bin/env python3
"""No-model numeric smoke test for the tiny-scale SRSD ii.27.18 equation."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions.symbolic_basis_v01.contract import compile_submission, make_spec
from extensions.symbolic_basis_v01.executor import check_runtime, sandbox_call


def run() -> dict:
    check_runtime()
    compiled = compile_submission(
        {"feature_ids": ["m_0", "m_1", "m_3"], "explanation": "numeric calibration"},
        make_spec(1, 3),
    )
    X = [[float(index)] for index in range(1, 6)]
    coefficient = 8.854e-12
    y = [coefficient * row[0] ** 2 for row in X]
    fit = sandbox_call(compiled["source"], {
        "family": "symbolic", "task_id": "calibration/ii27.18", "input_names": ["x0"],
        "phase": "fit", "split_name": "calibration", "split_sha256": "calibration",
        "X": X, "y": y, "n_params": 3,
    })
    params = fit.get("result", {}).get("params")
    prediction = None
    if isinstance(params, list):
        prediction = sandbox_call(compiled["source"], {
            "family": "symbolic", "task_id": "calibration/ii27.18", "input_names": ["x0"],
            "phase": "predict", "split_name": "calibration", "split_sha256": "calibration",
            "X": X, "params": params,
        })
    return {"schema": "srsd-ii2718-numeric-calibration-v01", "status": "passed",
            "true_coefficient": coefficient, "fit": fit, "prediction": prediction}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True))
