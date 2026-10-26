#!/usr/bin/env python3
"""Run the frozen p04 independent development batch.

The batch uses four new task-specific parent structures, two one-shot actor
requests per parent, and a fresh fake certificate before real mode is allowed.
It generates proposals only; v03/v04 outcome replays are separate, model-free
steps after the round summary is frozen.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("DO_NOT_TRACK", "1")

from analysis.replacement_evidence.independent_round_config import (
    P04_TASK_DEFINITIONS, assert_records_novelty, assert_source_novelty,
    historical_source_hashes, slot_ids,
)
from analysis.replacement_evidence.round_runner import compile_basis, load_frozen_tasks, run_round
from extensions.basis_trial_v02 import sdk_controller
from extensions.symbolic_basis_v01.executor import check_runtime, sandbox_call
from rsi_eval.pilot_budget import BudgetLedger


SHIFT_REPORT = ROOT / "docs/environment/2026-10-26-shift-aware-dev-v02.json"
NATURAL_REPORT = ROOT / "docs/environment/2026-10-26-natural-domain-v04.json"
RUNTIME_LOCK = ROOT / "extensions/symbolic_basis_v01/runtime-lock.json"
FAKE_CERTIFICATE = ROOT / "docs/environment/2026-10-27-natural-domain-v04-p04-fake-verification.json"
RUN_ROOT = ROOT / "runs/replacement-natural-domain-v04-p04"
PROTOCOL = "replacement-natural-domain-v04-p04"


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _current_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def include_historical_summary(summary_path: Path, active_root: Path = RUN_ROOT) -> bool:
    """Return whether a round summary belongs to a prior protocol run."""

    try:
        summary_path.resolve().relative_to(active_root.resolve())
    except ValueError:
        return True
    return False


def build_fake_responses(task_definitions=P04_TASK_DEFINITIONS) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    for definition in task_definitions:
        parent_ids = list(definition.parents[0].feature_ids)
        spec = sdk_controller.make_spec(len(definition.input_names), len(parent_ids))
        alternatives = [feature for feature in spec["feature_ids"] if feature not in parent_ids]
        if not alternatives:
            raise RuntimeError(f"no replacement feature available for {definition.task_id}")
        candidate = list(parent_ids)
        candidate[-1] = alternatives[0]
        responses.extend([
            {"tool": "submit_basis", "arguments": {"feature_ids": parent_ids}},
            {"tool": "submit_basis", "arguments": {"feature_ids": candidate}},
        ])
    return responses


def _historical_by_task() -> tuple[dict[str, set[str]], int]:
    merged: dict[str, set[str]] = {}
    count = 0
    for summary_path in sorted((ROOT / "runs").glob("**/round/round-summary.json")):
        if not include_historical_summary(summary_path):
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            extracted = historical_source_hashes(summary)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            continue
        count += 1
        for task_id, hashes in extracted.items():
            merged.setdefault(task_id, set()).update(hashes)
    return merged, count


def _validate_parent_novelty(tasks: dict[str, Any], historical: dict[str, set[str]]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for definition in P04_TASK_DEFINITIONS:
        task = tasks[definition.task_id]
        parent = compile_basis(definition, definition.parents[0].feature_ids)
        parent_hash = parent["source_sha256"]
        assert_source_novelty(
            proposed_parent_hashes={parent_hash},
            proposed_candidate_hashes=set(),
            historical_hashes=historical.get(definition.task_id, set()),
        )
        hashes[definition.task_id] = parent_hash
    return hashes


def _make_ledger(output: Path) -> BudgetLedger:
    return BudgetLedger(
        output / "budget-ledger.json", max_requests=8,
        max_requests_per_session=1, max_output_tokens=8192,
        max_input_bytes=98304, max_reserved_tokens=400000,
        max_cost_cny=4, session_ids=slot_ids(),
    )


def _validate_fake_certificate() -> dict[str, Any]:
    certificate = json.loads(FAKE_CERTIFICATE.read_text(encoding="utf-8"))
    required = {
        "schema": PROTOCOL + "-verification",
        "status": "passed",
        "mode": "fake",
        "model_requests": 8,
        "accepted_slots": 8,
        "gate_records": 24,
        "real_model_calls": 0,
        "official_test_read": False,
        "official_test_ood_read": False,
        "natural_report_read": False,
    }
    if any(certificate.get(key) != value for key, value in required.items()):
        raise RuntimeError("p04 fake certificate is incomplete")
    if certificate.get("split_report_sha256") != _sha_file(SHIFT_REPORT):
        raise RuntimeError("p04 fake certificate split report changed")
    if certificate.get("natural_report_sha256") != _sha_file(NATURAL_REPORT):
        raise RuntimeError("p04 fake certificate natural report changed")
    if certificate.get("runtime_lock_sha256") != _sha_file(RUNTIME_LOCK):
        raise RuntimeError("p04 fake certificate runtime lock changed")
    certificate_commit = certificate.get("code_commit")
    if not isinstance(certificate_commit, str) or not certificate_commit:
        raise RuntimeError("p04 fake certificate has no code commit")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", certificate_commit, _current_commit()],
        cwd=ROOT, capture_output=True,
    )
    if ancestor.returncode != 0:
        raise RuntimeError("p04 fake certificate code commit is not an ancestor")
    return certificate


def run(mode: str, run_id: str, auth_file: str | None = None) -> dict[str, Any]:
    if mode not in {"fake", "real"}:
        raise ValueError("mode must be fake or real")
    if mode == "real":
        _validate_fake_certificate()
    output = RUN_ROOT / run_id
    if output.exists():
        raise FileExistsError("p04 output already exists; no resume")
    check_runtime()
    tasks = load_frozen_tasks(ROOT, SHIFT_REPORT, task_definitions=P04_TASK_DEFINITIONS)
    historical, historical_round_count = _historical_by_task()
    parent_hashes = _validate_parent_novelty(tasks, historical)
    output.mkdir(parents=True, exist_ok=False)
    ledger = _make_ledger(output)
    settings = sdk_controller.public_settings()
    provider = None
    if mode == "fake":
        settings["api_key"] = "synthetic-no-network-key"
        provider = sdk_controller.FakeProvider(build_fake_responses())
    else:
        from scripts.configure_minimax import auth_path, read_key
        settings["api_key"] = read_key(auth_path(auth_file))

    def actor_runner(*, slot_id, packet, spec, output_dir):
        return sdk_controller.run_session(
            ROOT, output_dir, slot_id, packet, ledger, settings,
            stage="actor", spec=spec,
        )

    context = (
        patch("openhands.sdk.llm.llm.litellm_completion", provider)
        if provider is not None else contextlib.nullcontext()
    )
    report: dict[str, Any] = {
        "schema": PROTOCOL, "run_id": run_id, "mode": mode,
        "status": "error", "model_requests": 0, "accepted_slots": 0,
        "gate_records": 0, "official_test_read": False,
        "official_test_ood_read": False, "natural_report_read": False,
        "sdk_version": importlib.metadata.version("openhands-sdk"),
        "parent_source_hashes": parent_hashes,
        "historical_round_count": historical_round_count,
    }
    try:
        with context:
            summary = run_round(
                tasks=tasks, actor_runner=actor_runner,
                fit_executor=sandbox_call, predict_executor=sandbox_call,
                output_dir=output / "round", synthetic_outcome=(mode == "fake"),
                task_definitions=P04_TASK_DEFINITIONS,
            )
        assert_records_novelty(summary["records"], historical)
        report.update({
            "status": "passed", "model_requests": summary["model_requests"],
            "accepted_slots": summary["accepted_slots"],
            "gate_records": summary["gate_records"],
            "outcome_dev_read": summary["outcome_dev_read"],
            "round_summary_sha256": _sha_file(output / "round/round-summary.json"),
            "provider_calls": None if provider is None else provider.calls,
            "real_model_calls": 0 if mode == "fake" else summary["model_requests"],
            "split_report": str(SHIFT_REPORT.relative_to(ROOT)).replace("\\", "/"),
            "split_report_sha256": _sha_file(SHIFT_REPORT),
            "natural_report": str(NATURAL_REPORT.relative_to(ROOT)).replace("\\", "/"),
            "natural_report_sha256": _sha_file(NATURAL_REPORT),
            "runtime_lock_sha256": _sha_file(RUNTIME_LOCK),
            "code_commit": _current_commit(),
        })
        if mode == "fake":
            certificate = {
                "schema": PROTOCOL + "-verification", "status": "passed", "mode": "fake",
                "sdk_version": report["sdk_version"], "run_id": run_id,
                "code_commit": report["code_commit"],
                "split_report_sha256": report["split_report_sha256"],
                "natural_report_sha256": report["natural_report_sha256"],
                "runtime_lock_sha256": report["runtime_lock_sha256"],
                "parent_source_hashes": parent_hashes,
                "historical_round_count": historical_round_count,
                "model_requests": report["model_requests"],
                "accepted_slots": report["accepted_slots"],
                "gate_records": report["gate_records"],
                "real_model_calls": 0, "official_test_read": False,
                "official_test_ood_read": False, "natural_report_read": False,
                "outcome_dev_read": True,
                "round_summary_sha256": report["round_summary_sha256"],
                "provider_calls": report["provider_calls"],
                "budget": ledger.summary(),
            }
            FAKE_CERTIFICATE.parent.mkdir(parents=True, exist_ok=True)
            FAKE_CERTIFICATE.write_text(
                json.dumps(certificate, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
                encoding="utf-8",
            )
            report["preflight_certificate"] = str(FAKE_CERTIFICATE.relative_to(ROOT)).replace("\\", "/")
    except Exception as exc:
        report.update({"error_type": type(exc).__name__, "error_stage": "round_or_novelty"})
        stop_path = output / "round" / "round-stop.json"
        if stop_path.is_file():
            try:
                stop = json.loads(stop_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                stop = None
            if isinstance(stop, dict):
                report.update({
                    "stop_reason": stop.get("reason"),
                    "stop_slot_id": stop.get("slot_id"),
                    "accepted_slots": stop.get("accepted_slots", 0),
                    "gate_records": stop.get("gate_records", 0),
                    "round_stop_sha256": _sha_file(stop_path),
                })
    report["budget"] = ledger.summary()
    if report.get("status") != "passed":
        report["model_requests"] = max(report.get("model_requests", 0), report["budget"]["request_count"])
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"], "run_id": run_id,
        "model_requests": report.get("model_requests"),
        "accepted_slots": report.get("accepted_slots"),
        "gate_records": report.get("gate_records"),
        "real_model_calls": report.get("real_model_calls"),
        "error_type": report.get("error_type"),
    }, ensure_ascii=False, sort_keys=True))
    return report


def main() -> int:
    parser = __import__("argparse").ArgumentParser()
    parser.add_argument("--mode", choices=("fake", "real"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--auth-file")
    args = parser.parse_args()
    result = run(args.mode, args.run_id, args.auth_file)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
