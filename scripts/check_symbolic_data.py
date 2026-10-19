#!/usr/bin/env python3
"""Audit pinned public LLM-SR CSV files, without running a model or scoring one.

Only file identities, schemas, counts and overlap counts enter the JSON report.
Numeric observations remain in memory; no fitted equation or test score is made.
"""
import argparse
import csv
import hashlib
import itertools
import json
import math
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
TASKS = {"oscillator1", "oscillator2", "bactgrow", "stressstrain"}
SPLITS = {"train", "test_id", "test_ood"}
HEADERS = {
    "oscillator1": ["x", "v", "a"],
    "oscillator2": ["t", "x", "v", "a"],
    "bactgrow": ["b", "s", "temp", "pH", "db"],
    "stressstrain": ["strain", "temp", "stress"],
}


def safe_path(root, relative):
    """Reject path traversal and links before any read or report write."""
    if not isinstance(relative, str) or len(relative) > 512 or "\\" in relative:
        raise ValueError("invalid_relative_path")
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute():
        raise ValueError("invalid_relative_path")
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", p)
           or p in {".", ".."} for p in parts):
        raise ValueError("invalid_relative_path")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink_refused")
    current.resolve().relative_to(root.resolve())
    return current


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_csv(path, spec):
    result = {"status": "invalid", "errors": []}
    rows, inputs = set(), set()
    if path.is_symlink():
        result["errors"].append("symlink_refused")
        return result, rows, inputs
    if not path.is_file():
        result.update(status="missing", errors=["file_missing"])
        return result, rows, inputs
    result.update(bytes=path.stat().st_size, sha256=sha256_file(path))
    if result["sha256"] != spec["sha256"]:
        result["errors"].append("sha256_mismatch")
        return result, rows, inputs
    count = invalid_width = nonnumeric = nonfinite = 0
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.reader(stream, strict=True)
        header = next(reader, None)
        result["columns_match"] = header == spec["columns"]
        if not result["columns_match"]:
            result["errors"].append("column_names_or_order_mismatch")
        for raw in reader:
            count += 1
            if len(raw) != len(spec["columns"]):
                invalid_width += 1
                continue
            try:
                values = tuple(float(value) for value in raw)
            except (ValueError, OverflowError):
                nonnumeric += 1
                continue
            if not all(math.isfinite(value) for value in values):
                nonfinite += 1
                continue
            rows.add(values)
            # main.py at the pinned upstream version takes X[:, :-1], y[:, -1].
            inputs.add(values[:-1])
    valid_count = count - invalid_width - nonnumeric - nonfinite
    result.update(
        rows=count, expected_rows=spec["rows"], columns=len(spec["columns"]),
        finite_rows=valid_count, invalid_width_rows=invalid_width,
        nonnumeric_rows=nonnumeric, nonfinite_rows=nonfinite,
        duplicate_rows=valid_count - len(rows),
        duplicate_input_rows=valid_count - len(inputs),
        unique_rows=len(rows), unique_inputs=len(inputs),
        output_column_index=len(spec["columns"]) - 1,
    )
    if count != spec["rows"]:
        result["errors"].append("row_count_mismatch")
    if invalid_width:
        result["errors"].append("row_width_mismatch")
    if nonnumeric:
        result["errors"].append("nonnumeric_values")
    if nonfinite:
        result["errors"].append("nonfinite_values")
    result["status"] = "ok" if not result["errors"] else "invalid"
    return result, rows, inputs


def validate_config(symbolic):
    if symbolic.get("source_name") != "LLM-SR":
        raise ValueError("unsupported_symbolic_source")
    entries = symbolic.get("files")
    if not isinstance(entries, list) or len(entries) != 12:
        raise ValueError("expected_twelve_official_csv_files")
    expected = {f"{task}/{split}.csv" for task in TASKS for split in SPLITS}
    seen = set()
    for spec in entries:
        relative = spec["relative_path"]
        if relative not in expected or relative in seen:
            raise ValueError("unexpected_or_duplicate_file")
        seen.add(relative)
        task = relative.split("/")[0]
        if spec["upstream_path"] != "data/" + relative:
            raise ValueError("unexpected_upstream_path")
        if spec["columns"] != HEADERS[task]:
            raise ValueError("unexpected_column_contract")
        if type(spec["rows"]) is not int or not 0 < spec["rows"] <= 1_000_000:
            raise ValueError("invalid_expected_row_count")
        if not isinstance(spec["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", spec["sha256"]):
            raise ValueError("invalid_sha256")


def audit_dataset(root, symbolic):
    validate_config(symbolic)
    data_dir = safe_path(root, symbolic["data_dir"])
    report = {
        "source_name": "LLM-SR", "data_dir": symbolic["data_dir"],
        "status": "ok", "files": [], "cross_split_overlap": {},
        "output_column": "last", "model_calls": 0, "formal_experiments": 0,
        "report_scope": "Schema, integrity and exact numeric overlap; no formulas, rows or scores.",
        "overlap_semantics": "Exact finite float tuples; counts are distinct shared rows/inputs, not pair counts.",
        "independence_limit": "Zero exact overlap does not prove statistical independence; oscillator observations come from trajectories.",
    }
    tables = {task: {} for task in TASKS}
    for spec in symbolic["files"]:
        relative = spec["relative_path"]
        path = safe_path(data_dir, relative)
        try:
            item, rows, inputs = audit_csv(path, spec)
        except (OSError, UnicodeError, csv.Error, ValueError):
            item, rows, inputs = {"status": "invalid", "errors": ["csv_read_error"]}, set(), set()
        item["relative_path"] = relative
        report["files"].append(item)
        task, filename = relative.split("/")
        if item["status"] == "ok":
            tables[task][Path(filename).stem] = (rows, inputs)
    for task in sorted(TASKS):
        overlaps = []
        for left, right in itertools.combinations(sorted(SPLITS), 2):
            if left not in tables[task] or right not in tables[task]:
                overlaps.append({"left": left, "right": right, "status": "not_checked"})
                continue
            left_rows, left_inputs = tables[task][left]
            right_rows, right_inputs = tables[task][right]
            overlaps.append({
                "left": left, "right": right, "status": "checked",
                "shared_rows": len(left_rows & right_rows),
                "shared_inputs": len(left_inputs & right_inputs),
            })
        report["cross_split_overlap"][task] = overlaps
    statuses = [item["status"] for item in report["files"]]
    report["files_checked"] = statuses.count("ok")
    if "invalid" in statuses:
        report["status"] = "invalid"
    elif "missing" in statuses:
        report["status"] = "incomplete"
    report["total_rows"] = sum(item.get("rows", 0) for item in report["files"])
    return report


def self_check():
    with tempfile.TemporaryDirectory(prefix="llmsr-schema-check-") as folder:
        path = Path(folder) / "fixture.csv"
        path.write_text("x,v,a\n1,2,3\n1,2,3\n2,3,4\n", encoding="utf-8")
        spec = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "rows": 3, "columns": ["x", "v", "a"]}
        result, rows, inputs = audit_csv(path, spec)
        assert result["status"] == "ok"
        assert result["duplicate_rows"] == 1
        assert result["duplicate_input_rows"] == 1
        assert len(rows) == len(inputs) == 2
        cases = [
            ("x,v,a\n1,2,nan\n", "nonfinite_values"),
            ("x,v,a\n1,2,inf\n", "nonfinite_values"),
            ("x,v,a\n1,2,no\n", "nonnumeric_values"),
            ("x,v,a\n1,2\n", "row_width_mismatch"),
            ("a,x,v\n1,2,3\n", "column_names_or_order_mismatch"),
        ]
        for content, expected in cases:
            path.write_text(content, encoding="utf-8")
            spec.update(sha256=sha256_file(path), rows=1)
            result, _, _ = audit_csv(path, spec)
            assert result["status"] == "invalid" and expected in result["errors"]
        path.write_text("x,v,a\n1,2,999\n", encoding="utf-8")
        spec.update(sha256=sha256_file(path), rows=1)
        result, changed_rows, changed_inputs = audit_csv(path, spec)
        assert result["status"] == "ok"
        assert len(rows & changed_rows) == 0 and len(inputs & changed_inputs) == 1
        spec["sha256"] = "0" * 64
        result, _, _ = audit_csv(path, spec)
        assert "sha256_mismatch" in result["errors"]
        for invalid in ["../outside", "/outside", "x/../../outside", "x\\outside"]:
            try:
                safe_path(Path(folder), invalid)
            except ValueError:
                pass
            else:
                raise AssertionError("path_traversal_not_rejected")
    return {"status": "ok", "scope": "Synthetic schema fixtures only; no benchmark result.",
            "cases": ["duplicate_rows", "duplicate_inputs", "nan", "infinity", "nonnumeric",
                      "row_width", "column_order", "input_only_overlap", "hash_mismatch", "path_traversal"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/tasks/downloads-v0.1.json")
    parser.add_argument("--report", default="runs/data-preparation/symbolic.json")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        print(json.dumps(self_check(), ensure_ascii=False))
        return 0
    try:
        config_path = safe_path(ROOT, args.config)
        report_path = safe_path(ROOT, args.report)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        report = audit_dataset(ROOT, config["symbolic"])
        report["checked_at_utc"] = datetime.now(timezone.utc).isoformat()
        report["config_sha256"] = sha256_file(config_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, TypeError, KeyError):
        # Do not echo arbitrary file contents, host paths, numeric rows or secrets.
        print(json.dumps({"status": "error", "reason": "invalid_config_path_or_io"}))
        return 2
    print(json.dumps({"status": report["status"], "files_checked": report["files_checked"],
                      "total_rows": report["total_rows"], "report": args.report,
                      "model_calls": 0}, ensure_ascii=False))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
