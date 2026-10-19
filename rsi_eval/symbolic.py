"""Trusted host data loading and scoring for the original LLM-SR pilot.

Only official training files are exposed here. No fit/dev/strategy partition or
formal test protocol is implied by this plumbing interface. Candidate Python
must run through the sandbox worker, never in this module's host process.
"""
import csv
import hashlib
import io
import json
import math
from numbers import Real
from pathlib import Path


HEADERS = {"oscillator1": ["x", "v", "a"],
           "oscillator2": ["t", "x", "v", "a"]}
DATA_DIRECTORY = "data/symbolic/llm-sr"


def _inside(root: Path, relative: str) -> Path:
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("symlink_refused")
    path.resolve().relative_to(root.resolve())
    return path


def prepare_task(task_id: str, root: Path) -> dict:
    """Load a pinned oscillator training table; the last column is the target."""
    if task_id not in HEADERS:
        raise ValueError("unsupported_task")
    root = Path(root)
    config_path = _inside(root, "configs/tasks/downloads-v0.1.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))["symbolic"]
    if config.get("source_name") != "LLM-SR" or config.get("data_dir") != DATA_DIRECTORY:
        raise ValueError("unsupported_data_source")
    relative = f"{task_id}/train.csv"
    entries = [entry for entry in config["files"] if entry.get("relative_path") == relative]
    if len(entries) != 1:
        raise ValueError("missing_or_duplicate_training_manifest")
    spec = entries[0]
    if spec.get("columns") != HEADERS[task_id]:
        raise ValueError("manifest_column_mismatch")
    path = _inside(root, f"{DATA_DIRECTORY}/{relative}")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
        raise ValueError("training_hash_mismatch")
    if len(raw) != spec["size"]:
        raise ValueError("training_size_mismatch")
    reader = csv.reader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True)
    if next(reader, None) != HEADERS[task_id]:
        raise ValueError("training_column_mismatch")
    X, y = [], []
    for row in reader:
        if len(row) != len(HEADERS[task_id]):
            raise ValueError("training_row_width_mismatch")
        try:
            values = [float(value) for value in row]
        except (ValueError, OverflowError) as exc:
            raise ValueError("training_nonnumeric_values") from exc
        if not all(math.isfinite(value) for value in values):
            raise ValueError("training_nonfinite_values")
        X.append(values[:-1])
        y.append(values[-1])
    if not X or len(X) != spec["rows"]:
        raise ValueError("training_row_count_mismatch")
    return {"family": "symbolic", "task_id": task_id, "X": X, "y": y,
            "input_names": HEADERS[task_id][:-1]}


def score_predictions(y, predictions) -> dict:
    """Recompute all metrics in the trusted host; never accept candidate scores.

NMSE uses population target variance. Nonfinite values, zero variance, overflow,
and wrong shape/dtype are explicit failures rather than dropped observations.
"""
    def invalid(reason):
        return {"status": "invalid_output", "error": reason}

    if not isinstance(y, (list, tuple)) or not y:
        return invalid("invalid_target_shape")
    if not isinstance(predictions, (list, tuple)) or len(predictions) != len(y):
        return invalid("invalid_shape")
    if any(isinstance(value, bool) or not isinstance(value, Real) for value in predictions):
        return invalid("invalid_dtype")
    if any(isinstance(value, bool) or not isinstance(value, Real) for value in y):
        return invalid("invalid_target_dtype")
    try:
        actual = [float(value) for value in y]
        predicted = [float(value) for value in predictions]
    except (ValueError, OverflowError):
        return invalid("numeric_overflow")
    if not all(math.isfinite(value) for value in actual):
        return invalid("nonfinite_target")
    if not all(math.isfinite(value) for value in predicted):
        return invalid("nonfinite_output")
    try:
        count = len(actual)
        mean = math.fsum(value / count for value in actual)
        variance = math.fsum((value - mean) ** 2 / count for value in actual)
        if variance == 0:
            return invalid("zero_target_variance")
        mse = math.fsum((truth - pred) ** 2 / count for truth, pred in zip(actual, predicted))
        nmse = mse / variance
    except (OverflowError, ValueError, ZeroDivisionError):
        return invalid("numeric_overflow")
    if not all(math.isfinite(value) for value in (variance, mse, nmse)):
        return invalid("nonfinite_metrics")
    return {"status": "success", "metrics": {"mse": mse, "nmse": nmse}}
