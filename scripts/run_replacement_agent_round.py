#!/usr/bin/env python3
"""Run the frozen replacement-sufficiency Agent round.

``--mode fake`` uses the real OpenHands SDK and locked symbolic sandbox but a
synthetic provider.  ``--mode real`` is deliberately guarded by the fake
12-slot certificate and reads the existing MiniMax key only in memory.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("DO_NOT_TRACK", "1")

from analysis.replacement_evidence.round_runner import (
    TASK_DEFINITIONS,
    compile_basis,
    load_frozen_tasks,
    run_round,
)
from extensions.basis_trial_v02 import sdk_controller
from extensions.symbolic_basis_v01.executor import sandbox_call, check_runtime
from rsi_eval.pilot_budget import BudgetLedger


PROTOCOL_VERSION = "replacement-agent-round-v0.1"
PREFLIGHT_CERTIFICATE = ROOT / "docs/environment/2026-10-24-replacement-agent-round-preflight.json"


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _slot_ids() -> list[str]:
    return [f"{parent.parent_id}-r{repeat}"
            for task in TASK_DEFINITIONS for parent in task.parents for repeat in (1, 2)]


def _fake_responses() -> list[dict]:
    responses = []
    for definition in TASK_DEFINITIONS:
        spec = None
        for parent in definition.parents:
            parent_ids = list(parent.feature_ids)
            if spec is None:
                spec = sdk_controller.make_spec(len(definition.input_names), len(parent_ids))
            alternatives = [feature for feature in spec["feature_ids"] if feature not in parent_ids]
            if not alternatives:
                raise RuntimeError(f"no replacement feature available for {parent.parent_id}")
            responses.append({"tool": "submit_basis", "arguments": {"feature_ids": parent_ids}})
            candidate = list(parent_ids)
            candidate[-1] = alternatives[0]
            responses.append({"tool": "submit_basis", "arguments": {"feature_ids": candidate}})
    return responses


def _validate_certificate() -> dict:
    if not PREFLIGHT_CERTIFICATE.is_file():
        raise RuntimeError("12-slot fake-provider certificate is required before real mode")
    certificate = json.loads(PREFLIGHT_CERTIFICATE.read_text(encoding="utf-8"))
    required = {
        "schema": "replacement-agent-round-preflight-v0.1",
        "status": "passed", "mode": "fake", "model_requests": 12,
        "accepted_slots": 12, "gate_records": 36, "real_model_calls": 0,
        "outcome_dev_read": True,
    }
    if any(certificate.get(key) != value for key, value in required.items()):
        raise RuntimeError("fake-provider certificate is incomplete or not passed")
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    certificate_commit = certificate.get("code_commit")
    if not isinstance(certificate_commit, str) or not certificate_commit:
        raise RuntimeError("fake-provider certificate has no code commit")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", certificate_commit, current_commit],
        cwd=ROOT, capture_output=True,
    )
    if ancestor.returncode != 0:
        raise RuntimeError("fake-provider certificate commit is not an ancestor")
    protected_paths = [
        "analysis/replacement_evidence/round_runner.py",
        "analysis/replacement_evidence/outcome_prediction.py",
        "rsi_eval/replacement_condition_gate.py",
        "rsi_eval/replacement_shadow_outcome.py",
        "scripts/run_replacement_agent_round.py",
        "extensions/symbolic_basis_v01/contract.py",
        "extensions/symbolic_basis_v01/executor.py",
        "extensions/symbolic_basis_v01/runtime-lock.json",
    ]
    changed = subprocess.run(
        ["git", "diff", "--quiet", certificate_commit, current_commit, "--", *protected_paths],
        cwd=ROOT, capture_output=True,
    )
    if changed.returncode != 0:
        raise RuntimeError("protected runner code changed after fake preflight")
    split_report = ROOT / "docs/environment/2026-10-24-replacement-dev-splits.json"
    runtime_lock = ROOT / "extensions/symbolic_basis_v01/runtime-lock.json"
    if certificate.get("split_report_sha256") != _sha_file(split_report):
        raise RuntimeError("fake-provider certificate does not match split report")
    if certificate.get("runtime_lock_sha256") != _sha_file(runtime_lock):
        raise RuntimeError("fake-provider certificate does not match symbolic runtime lock")
    run_id = certificate.get("run_id")
    if not isinstance(run_id, str):
        raise RuntimeError("fake-provider certificate has no run id")
    summary = ROOT / "runs/replacement-agent-round" / run_id / "round/round-summary.json"
    if not summary.is_file() or certificate.get("round_summary_sha256") != _sha_file(summary):
        raise RuntimeError("fake-provider round summary is missing or changed")
    return certificate


def _make_ledger(output: Path) -> BudgetLedger:
    # sdk_controller currently rejects max_cost_cny > 4.  Four CNY is still
    # far below the user's 300 CNY authorization and covers the twelve slots.
    return BudgetLedger(
        output / "budget-ledger.json", max_requests=12,
        max_requests_per_session=1, max_output_tokens=8192,
        max_input_bytes=98304, max_reserved_tokens=400000,
        max_cost_cny=4, session_ids=_slot_ids(),
    )


def run(mode: str, run_id: str, auth_file: str | None = None,
        report_path: Path | None = None) -> dict:
    if mode not in {"fake", "real"}:
        raise ValueError("mode must be fake or real")
    output = ROOT / "runs/replacement-agent-round" / run_id
    if output.exists():
        raise FileExistsError("replacement round output already exists; no resume")
    if mode == "real":
        _validate_certificate()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": PROTOCOL_VERSION, "run_id": run_id, "mode": mode,
        "status": "error", "model_requests": 0, "accepted_slots": 0,
        "gate_records": 0, "official_test_read": False,
        "official_test_ood_read": False, "outcome_dev_read": False,
        "sdk_version": importlib.metadata.version("openhands-sdk"),
    }
    ledger = None
    provider = None
    try:
        check_runtime()
        tasks = load_frozen_tasks(ROOT, report_path)
        output.mkdir(parents=False, exist_ok=False)
        ledger = _make_ledger(output)
        settings = sdk_controller.public_settings()
        if mode == "fake":
            settings["api_key"] = "synthetic-no-network-key"
            provider = sdk_controller.FakeProvider(_fake_responses())
        else:
            from scripts.configure_minimax import auth_path, read_key
            settings["api_key"] = read_key(auth_path(auth_file))

        def actor_runner(*, slot_id, packet, spec, output_dir):
            return sdk_controller.run_session(
                ROOT, output_dir, slot_id, packet, ledger, settings,
                stage="actor", spec=spec,
            )

        context = (patch("openhands.sdk.llm.llm.litellm_completion", provider)
                   if provider is not None else contextlib.nullcontext())
        with context:
            summary = run_round(
                tasks=tasks, actor_runner=actor_runner,
                fit_executor=sandbox_call, predict_executor=sandbox_call,
                output_dir=output / "round", synthetic_outcome=(mode == "fake"),
            )
        report.update({
            "status": "passed", "model_requests": summary["model_requests"],
            "accepted_slots": summary["accepted_slots"],
            "gate_records": summary["gate_records"],
            "outcome_dev_read": summary["outcome_dev_read"],
            "round_summary_sha256": _sha_file(output / "round/round-summary.json"),
            "provider_calls": None if provider is None else provider.calls,
            "real_model_calls": 0 if mode == "fake" else summary["model_requests"],
            "split_report": str((report_path or ROOT / "docs/environment/2026-10-24-replacement-dev-splits.json").relative_to(ROOT)),
            "split_report_sha256": _sha_file(report_path or ROOT / "docs/environment/2026-10-24-replacement-dev-splits.json"),
            "runtime_lock_sha256": _sha_file(ROOT / "extensions/symbolic_basis_v01/runtime-lock.json"),
            "code_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                           check=True, capture_output=True, text=True).stdout.strip(),
        })
        if mode == "fake":
            certificate = {
                "schema": "replacement-agent-round-preflight-v0.1", "status": "passed",
                "mode": "fake", "sdk_version": report["sdk_version"],
                "run_id": run_id, "code_commit": report["code_commit"],
                "split_report_sha256": report["split_report_sha256"],
                "runtime_lock_sha256": report["runtime_lock_sha256"],
                "model_requests": report["model_requests"],
                "accepted_slots": report["accepted_slots"],
                "gate_records": report["gate_records"],
                "real_model_calls": 0, "outcome_dev_read": True,
                "round_summary_sha256": report["round_summary_sha256"],
                "provider_calls": report["provider_calls"],
                "budget": ledger.summary(),
            }
            PREFLIGHT_CERTIFICATE.parent.mkdir(parents=True, exist_ok=True)
            PREFLIGHT_CERTIFICATE.write_text(json.dumps(certificate, ensure_ascii=False,
                                                         allow_nan=False, indent=2) + "\n", encoding="utf-8")
            report["preflight_certificate"] = str(PREFLIGHT_CERTIFICATE.relative_to(ROOT))
    except Exception as exc:
        report.update({"error_type": type(exc).__name__, "error_stage": "round_or_preflight"})
    if ledger is not None:
        report["budget"] = ledger.summary()
        report["model_requests"] = report.get("model_requests", 0) or report["budget"]["request_count"]
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False,
                                                     allow_nan=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "run_id": run_id,
                      "summary_file": str(output / "summary.json"),
                      "model_requests": report.get("model_requests"),
                      "accepted_slots": report.get("accepted_slots"),
                      "gate_records": report.get("gate_records"),
                      "error_type": report.get("error_type"),
                      "budget": report.get("budget")}, ensure_ascii=False, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fake", "real"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--auth-file")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = run(args.mode, args.run_id, args.auth_file, args.report)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

