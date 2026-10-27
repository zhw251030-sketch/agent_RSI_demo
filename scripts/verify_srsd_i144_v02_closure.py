#!/usr/bin/env python3
"""Read-only end-to-end verifier for the frozen SRSD i.14.4 v02 round."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import py_compile
import subprocess
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "replacement-srsd-feynman-dummy-i144-v02-v05"
DEFAULT_CERTIFICATE = ROOT / "docs/environment/2026-10-27-srsd-feynman-dummy-i144-v02-v05-preflight.json"
DEFAULT_SOURCE = ROOT / "docs/environment/2026-10-27-srsd-feynman-dummy-i144-v02-source.json"
DEFAULT_DEV = ROOT / "docs/environment/2026-10-27-srsd-feynman-dummy-i144-v02-dev-v05.json"
DEFAULT_VAL = ROOT / "docs/environment/2026-10-27-srsd-feynman-dummy-i144-v02-val-replay-real-v03.json"
DEFAULT_HOLDOUT = ROOT / "docs/environment/2026-10-27-srsd-feynman-dummy-i144-v02-test-holdout-real-v01.json"
DEFAULT_RUNTIME = ROOT / "extensions/symbolic_basis_v01/runtime-lock.json"
DEFAULT_REAL_RUN = ROOT / "runs/replacement-srsd-feynman-dummy-i144-v02-v05/2026-10-27-srsd-dummy-i144-v02-real-v01/round/round-summary.json"

V02_CODE = (
    "extensions/symbolic_basis_v02/contract.py",
    "extensions/symbolic_basis_v02/sdk_adapter.py",
    "extensions/basis_trial_v02/sdk_controller_v02.py",
    "scripts/run_srsd_dummy_i144_v02_preflight.py",
    "scripts/run_srsd_dummy_i144_v02_val_replay.py",
    "scripts/run_srsd_dummy_i144_v02_test_holdout.py",
)


class ClosureError(RuntimeError):
    """Raised when a frozen artifact is missing or inconsistent."""


def _fail(message: str) -> None:
    raise ClosureError(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def validate_metadata(reports: Mapping[str, Mapping[str, Any]]) -> None:
    """Validate report-local schemas and the test-access boundary."""
    certificate = reports["certificate"]
    round_report = reports["round"]
    val = reports["val"]
    holdout = reports["holdout"]

    _require(certificate.get("schema") == PROTOCOL + "-verification", "certificate schema mismatch")
    _require(certificate.get("status") == "passed", "certificate status is not passed")
    _require(certificate.get("mode") == "fake", "certificate is not a fake preflight certificate")
    _require((certificate.get("model_requests"), certificate.get("accepted_slots"), certificate.get("gate_records"), certificate.get("real_model_calls")) == (2, 2, 6, 0), "certificate counts mismatch")

    _require(round_report.get("schema") == "replacement-agent-round-runner-v0.1", "real round schema mismatch")
    _require(round_report.get("status") == "passed", "real round status is not passed")
    _require((round_report.get("model_requests"), round_report.get("accepted_slots"), round_report.get("gate_records")) == (2, 2, 6), "real round counts mismatch")

    _require(val.get("schema") == "replacement-srsd-feynman-dummy-i144-v02-val-replay-v05", "val replay schema mismatch")
    _require(val.get("status") == "passed", "val replay status is not passed")
    _require(isinstance(val.get("rows"), list) and len(val["rows"]) == 2, "val replay rows mismatch")
    allow_count = sum(str(row.get("dual_gate_action", "")).startswith("allow") for row in val["rows"])
    _require(allow_count <= 1, "at most one frozen val allow action is permitted")

    _require(holdout.get("schema") == "replacement-srsd-feynman-dummy-i144-v02-test-holdout-v05", "holdout schema mismatch")
    _require(holdout.get("status") == "passed_descriptive_holdout", "holdout status mismatch")
    _require(holdout.get("one_time_read") is True and holdout.get("rules_frozen_before_read") is True, "holdout freeze boundary missing")
    _require(isinstance(holdout.get("rows"), list) and len(holdout["rows"]) == 2, "holdout rows mismatch")

    for name in ("certificate", "round", "val"):
        report = reports[name]
        _require(report.get("official_test_read") is False, f"{name} report must not read official test")
        _require(report.get("official_test_ood_read") is False, f"{name} report must not read official test_ood")
    _require(holdout.get("official_test_read") is True, "holdout must record official test read")
    _require(holdout.get("official_test_ood_read") is False, "holdout must not read official test_ood")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    _require(path.is_file(), f"missing required artifact: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        _fail(f"invalid JSON artifact {path}: {error}")
    _require(isinstance(value, dict), f"JSON artifact is not an object: {path}")
    return value


def _check_hash(report: Mapping[str, Any], field: str, path: Path, label: str) -> None:
    _require(report.get(field) == sha256_file(path), f"{label} hash mismatch")


def _is_ancestor(root: Path, commit: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=root, capture_output=True, check=False,
    ).returncode == 0


def _tracked_worktree_clean(root: Path) -> bool:
    return subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout == ""


def verify_closure(
    root: Path = ROOT,
    *,
    certificate_path: Path | None = None,
    source_path: Path | None = None,
    dev_path: Path | None = None,
    real_round_path: Path | None = None,
    val_path: Path | None = None,
    holdout_path: Path | None = None,
    runtime_path: Path | None = None,
) -> dict[str, Any]:
    """Run all checks without model calls, downloads, or writes to inputs."""
    certificate_path = certificate_path or root / DEFAULT_CERTIFICATE.relative_to(ROOT)
    source_path = source_path or root / DEFAULT_SOURCE.relative_to(ROOT)
    dev_path = dev_path or root / DEFAULT_DEV.relative_to(ROOT)
    val_path = val_path or root / DEFAULT_VAL.relative_to(ROOT)
    holdout_path = holdout_path or root / DEFAULT_HOLDOUT.relative_to(ROOT)
    runtime_path = runtime_path or root / DEFAULT_RUNTIME.relative_to(ROOT)
    real_round_path = real_round_path or root / DEFAULT_REAL_RUN.relative_to(ROOT)

    certificate = load_json(certificate_path)
    source = load_json(source_path)
    dev = load_json(dev_path)
    real_round = load_json(real_round_path)
    val = load_json(val_path)
    holdout = load_json(holdout_path)
    reports = {"certificate": certificate, "round": real_round, "val": val, "holdout": holdout}
    validate_metadata(reports)

    _require(source.get("official_test_read") is False, "source report must not read official test")
    _require(source.get("official_test_ood_read") is False, "source report must not read official test_ood")
    _require(dev.get("official_test_read") is False, "dev report must not read official test")
    _require(dev.get("official_test_ood_read") is False, "dev report must not read official test_ood")
    _require(dev.get("source_report_sha256") == sha256_file(source_path), "dev/source hash mismatch")
    _check_hash(certificate, "split_report_sha256", dev_path, "certificate/dev")
    _check_hash(certificate, "source_report_sha256", source_path, "certificate/source")
    _check_hash(certificate, "runtime_lock_sha256", runtime_path, "certificate/runtime")

    fake_run_id = certificate.get("run_id")
    _require(isinstance(fake_run_id, str) and fake_run_id, "fake certificate run_id missing")
    fake_round_path = root / "runs" / PROTOCOL / fake_run_id / "round" / "round-summary.json"
    fake_round = load_json(fake_round_path)
    _check_hash(certificate, "round_summary_sha256", fake_round_path, "certificate/fake round")
    _require(fake_round.get("official_test_read") is False and fake_round.get("official_test_ood_read") is False, "fake round crossed test boundary")

    _check_hash(val, "round_summary_sha256", real_round_path, "val/real round")
    _check_hash(val, "development_report_sha256", dev_path, "val/dev")
    _check_hash(val, "val_report_sha256", root / "docs/environment/2026-10-27-srsd-feynman-dummy-i144-v02-val-domain-v05.json", "val/domain")
    _check_hash(holdout, "round_summary_sha256", real_round_path, "holdout/real round")
    _check_hash(holdout, "development_report_sha256", dev_path, "holdout/dev")
    _check_hash(holdout, "source_report_sha256", source_path, "holdout/source")
    _check_hash(holdout, "val_replay_sha256", val_path, "holdout/val replay")

    code_commit = certificate.get("code_commit")
    _require(isinstance(code_commit, str) and _is_ancestor(root, code_commit), "certificate code commit is not an ancestor of HEAD")
    _require(_tracked_worktree_clean(root), "tracked worktree has uncommitted changes")
    compiled = []
    for relative in V02_CODE:
        path = root / relative
        _require(path.is_file(), f"missing v02 code file: {relative}")
        py_compile.compile(str(path), doraise=True)
        compiled.append(relative)

    current_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                                    capture_output=True, text=True, check=True).stdout.strip()
    return {
        "schema": "replacement-srsd-feynman-dummy-i144-v02-engineering-closure-v01",
        "status": "passed",
        "code_commit": current_commit,
        "certificate_code_commit": code_commit,
        "real_round_summary_sha256": sha256_file(real_round_path),
        "val_replay_sha256": sha256_file(val_path),
        "holdout_sha256": sha256_file(holdout_path),
        "fake_round_summary_sha256": sha256_file(fake_round_path),
        "official_test_read": True,
        "official_test_ood_read": False,
        "model_calls": 0,
        "downloads": 0,
        "writes_to_inputs": 0,
        "compiled_v02_files": compiled,
        "val_allow_count": sum(str(row.get("dual_gate_action", "")).startswith("allow") for row in val["rows"]),
        "deployed_harmful_count": sum(row.get("deployed_harmful") is True for row in holdout["rows"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify_closure(ROOT)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
