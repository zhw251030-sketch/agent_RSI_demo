#!/usr/bin/env python3
"""One-time descriptive SRSD test replay after val actions are frozen."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.replacement_evidence.external_dummy_i144_v02_task_config import DUMMY_I144_V02_TASK_DEFINITIONS
from analysis.replacement_evidence.round_runner import load_frozen_tasks
from extensions.symbolic_basis_v01.executor import check_runtime, sandbox_call
from scripts.run_srsd_dummy_i144_v02_val_replay import _basis_compiler, _fit_attempt, _score


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _download(url: str) -> bytes:
    with urlopen(url, timeout=120) as response:  # noqa: S310 - URL is in frozen source report
        return response.read()


def _convert(raw: bytes, path: Path) -> tuple[int, str]:
    lines = [line for line in raw.decode("utf-8").splitlines() if line.strip()]
    parsed = [line.split() for line in lines]
    if not parsed or len(parsed[0]) < 2 or any(len(row) != len(parsed[0]) for row in parsed):
        raise ValueError(f"invalid test source: {path}")
    headers = [f"x{i}" for i in range(len(parsed[0]) - 1)] + ["y"]
    csv_path = path.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(parsed)
    return len(parsed), _sha(csv_path.read_bytes())


def run(*, output: Path, round_path: Path, dev_path: Path, source_path: Path,
        val_replay_path: Path, basis_compiler=_basis_compiler) -> dict:
    check_runtime()
    source = json.loads(source_path.read_text(encoding="utf-8"))
    round_obj = json.loads(round_path.read_text(encoding="utf-8"))
    val_replay = json.loads(val_replay_path.read_text(encoding="utf-8"))
    if source.get("official_test_read") or source.get("official_test_ood_read"):
        raise ValueError("source report already claims test access; no second release")
    if round_obj.get("official_test_read") or val_replay.get("official_test_read"):
        raise ValueError("upstream development report claims holdout access")
    tasks = load_frozen_tasks(ROOT, dev_path, task_definitions=DUMMY_I144_V02_TASK_DEFINITIONS)
    action_by_slot = {row["slot_id"]: row["dual_gate_action"] for row in val_replay["rows"]}
    allow_count = sum(action.startswith("allow") for action in action_by_slot.values())
    if allow_count > 1:
        raise ValueError("v02 protocol permits at most one frozen val allow action")

    holdout_root = ROOT / "data/external/srsd-feynman-easy-dummy-i144-v02"
    test_files = {}
    for task_id in tasks:
        record = source["tasks"][task_id]
        url = record["files"]["test"]["url"]
        raw_path = holdout_root / task_id / "test.txt"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw = _download(url)
        raw_path.write_bytes(raw)
        row_count, csv_sha = _convert(raw, raw_path)
        with raw_path.with_suffix(".csv").open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            headers = tuple(reader.fieldnames or ())
            rows = list(reader)
        definition = next(item for item in DUMMY_I144_V02_TASK_DEFINITIONS if item.task_id == task_id)
        if headers != definition.headers:
            raise ValueError(f"{task_id} test headers mismatch")
        test_files[task_id] = {
            "url": url, "raw_sha256": _sha(raw), "raw_bytes": len(raw),
            "csv_sha256": csv_sha, "csv_path": str(raw_path.with_suffix(".csv").relative_to(ROOT)).replace("\\", "/"),
            "row_count": row_count, "rows": rows,
        }

    fit_cache = {}
    rows = []
    for record in sorted(round_obj["records"], key=lambda item: item["slot_id"]):
        task = tasks[record["task_id"]]
        parent = basis_compiler(task.definition, record["parent_feature_ids"])
        candidate = basis_compiler(task.definition, record["candidate_feature_ids"])
        for compiled in (parent, candidate):
            fit_cache.setdefault(compiled["source_sha256"], _fit_attempt(compiled, task, task.splits["fit_dev"]))
        parent_fit = fit_cache[parent["source_sha256"]]
        candidate_fit = fit_cache[candidate["source_sha256"]]
        parent_params = parent_fit.get("params")
        candidate_params = candidate_fit.get("params")
        test = test_files[record["task_id"]]
        names = list(task.definition.input_names)
        X = [[float(row[name]) for name in names] for row in test["rows"]]
        y = [float(row[task.definition.target]) for row in test["rows"]]
        split_sha = test["csv_sha256"]
        parent_nmse = (_score(parent["source"], task, "srsd_test_holdout", split_sha, X, y, parent_params)
                       if parent_params is not None else None)
        candidate_nmse = (_score(candidate["source"], task, "srsd_test_holdout", split_sha, X, y, candidate_params)
                          if candidate_params is not None else None)
        action = action_by_slot[record["slot_id"]]
        deployed_nmse = (candidate_nmse if action.startswith("allow") and record["edit_mode"] == "swap_one"
                         and candidate_nmse is not None else parent_nmse)
        candidate_delta = (candidate_nmse - parent_nmse
                           if candidate_nmse is not None and parent_nmse is not None else None)
        rows.append({
            "slot_id": record["slot_id"], "task_id": record["task_id"],
            "edit_mode": record["edit_mode"], "val_action": action,
            "parent_nmse": parent_nmse, "candidate_nmse": candidate_nmse,
            "candidate_delta": candidate_delta,
            "deployed_nmse": deployed_nmse,
            "deployed_harmful": (deployed_nmse > parent_nmse + 1e-5
                                  if deployed_nmse is not None and parent_nmse is not None else None),
            "parent_fit": parent_fit, "candidate_fit": candidate_fit,
        })
    result = {
        "schema": "replacement-srsd-feynman-easy-dummy-i144-v02-test-holdout-v05",
        "status": "passed_descriptive_holdout",
        "official_test_read": True, "official_test_ood_read": False,
        "one_time_read": True, "rules_frozen_before_read": True,
        "round_summary_sha256": _sha(round_path.read_bytes()),
        "development_report_sha256": _sha(dev_path.read_bytes()),
        "source_report_sha256": _sha(source_path.read_bytes()),
        "val_replay_sha256": _sha(val_replay_path.read_bytes()),
        "test_files": {task: {k: v for k, v in value.items() if k != "rows"} for task, value in test_files.items()},
        "rows": rows,
        "deployed_harmful_count": sum(row["deployed_harmful"] is True for row in rows),
        "candidate_harmful_count": sum(row["candidate_delta"] is not None and row["candidate_delta"] > 1e-5
                                        for row in rows if row["edit_mode"] == "swap_one"),
    }
    result["report_sha256"] = _sha(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"], "proposal_count": len(rows),
        "deployed_harmful_count": result["deployed_harmful_count"],
        "candidate_harmful_count": result["candidate_harmful_count"],
        "official_test_read": result["official_test_read"],
    }, ensure_ascii=False, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--round", type=Path, required=True)
    parser.add_argument("--dev-report", type=Path, required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--val-replay", type=Path, required=True)
    args = parser.parse_args()
    run(output=args.output, round_path=args.round, dev_path=args.dev_report,
        source_path=args.source_report, val_replay_path=args.val_replay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

