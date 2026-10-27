#!/usr/bin/env python3
"""Fake/real preflight for the isolated five-input SRSD Dummy v02 task."""

from __future__ import annotations

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

from analysis.replacement_evidence.external_dummy_i144_v02_task_config import DUMMY_I144_V02_TASK_DEFINITIONS
from analysis.replacement_evidence.round_runner import load_frozen_tasks, run_round
from extensions.basis_trial_v02 import sdk_controller_v02 as sdk_controller
from extensions.symbolic_basis_v02.contract import compile_submission as v02_compile_submission
from extensions.symbolic_basis_v02.contract import make_spec as v02_make_spec
from extensions.symbolic_basis_v01.executor import check_runtime, sandbox_call
from rsi_eval.pilot_budget import BudgetLedger


PROTOCOL = "replacement-srsd-feynman-dummy-i144-v02-v05"
SPLIT_REPORT = ROOT / "docs/environment/2026-10-27-srsd-feynman-dummy-i144-v02-dev-v05.json"
SOURCE_REPORT = ROOT / "docs/environment/2026-10-27-srsd-feynman-dummy-i144-v02-source.json"
RUNTIME_LOCK = ROOT / "extensions/symbolic_basis_v01/runtime-lock.json"
CERTIFICATE = ROOT / "docs/environment/2026-10-27-srsd-feynman-dummy-i144-v02-v05-preflight.json"


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def _basis_compiler(definition, feature_ids):
    spec = v02_make_spec(len(definition.input_names), len(feature_ids))
    return v02_compile_submission({"feature_ids": list(feature_ids),
                                   "explanation": "Host-generated v02 execution payload."}, spec)


def _slot_ids() -> list[str]:
    return [f"{task.task_id}-p01-r{repeat}"
            for task in DUMMY_I144_V02_TASK_DEFINITIONS for repeat in (1, 2)]


def _fake_responses() -> list[dict]:
    responses = []
    for definition in DUMMY_I144_V02_TASK_DEFINITIONS:
        parent = list(definition.parents[0].feature_ids)
        spec = v02_make_spec(len(definition.input_names), len(parent))
        alternatives = [feature for feature in spec["feature_ids"] if feature not in parent]
        candidate = list(parent)
        candidate[-1] = alternatives[0]
        responses.extend([
            {"tool": "submit_basis", "arguments": {"feature_ids": parent}},
            {"tool": "submit_basis", "arguments": {"feature_ids": candidate}},
        ])
    return responses


def _validate_fake_certificate() -> dict:
    certificate = json.loads(CERTIFICATE.read_text(encoding="utf-8"))
    expected_slots = len(_slot_ids())
    required = {"schema": PROTOCOL + "-verification", "status": "passed", "mode": "fake",
                "model_requests": expected_slots, "accepted_slots": expected_slots,
                "gate_records": expected_slots * 3, "real_model_calls": 0,
                "official_test_read": False, "official_test_ood_read": False}
    if any(certificate.get(key) != value for key, value in required.items()):
        raise RuntimeError("v02 fake certificate is incomplete")
    for key, path in (("split_report_sha256", SPLIT_REPORT),
                      ("source_report_sha256", SOURCE_REPORT),
                      ("runtime_lock_sha256", RUNTIME_LOCK)):
        if certificate.get(key) != _sha_file(path):
            raise RuntimeError(f"v02 fake certificate hash mismatch: {key}")
    if subprocess.run(["git", "merge-base", "--is-ancestor", certificate.get("code_commit", ""), _commit()],
                      cwd=ROOT, capture_output=True).returncode != 0:
        raise RuntimeError("v02 fake certificate code commit is not an ancestor")
    return certificate


def run(run_id: str, *, mode: str = "fake", auth_file: str | None = None) -> dict:
    if mode not in {"fake", "real"}:
        raise ValueError("mode must be fake or real")
    if mode == "real":
        _validate_fake_certificate()
    output = ROOT / "runs" / PROTOCOL / run_id
    if output.exists():
        raise FileExistsError("v02 preflight output already exists; no resume")
    check_runtime()
    tasks = load_frozen_tasks(ROOT, SPLIT_REPORT, task_definitions=DUMMY_I144_V02_TASK_DEFINITIONS)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=False, exist_ok=False)
    ledger = BudgetLedger(output / "budget-ledger.json", max_requests=len(_slot_ids()),
                          max_requests_per_session=1, max_output_tokens=8192,
                          max_input_bytes=98304, max_reserved_tokens=200000,
                          max_cost_cny=4, session_ids=_slot_ids())
    settings = sdk_controller.public_settings()
    provider = None
    if mode == "fake":
        settings["api_key"] = "synthetic-no-network-key"
        provider = sdk_controller.FakeProvider(_fake_responses())
    else:
        from scripts.configure_minimax import auth_path, read_key
        settings["api_key"] = read_key(auth_path(auth_file))

    def actor_runner(*, slot_id, packet, spec, output_dir):
        return sdk_controller.run_session(ROOT, output_dir, slot_id, packet, ledger, settings,
                                          stage="actor", spec=spec,
                                          accept_callback=lambda compiled: {"status": "accepted"})

    context = (patch("openhands.sdk.llm.llm.litellm_completion", provider)
               if provider is not None else contextlib.nullcontext())
    with context:
        summary = run_round(
            tasks=tasks, actor_runner=actor_runner,
            fit_executor=sandbox_call, predict_executor=sandbox_call,
            output_dir=output / "round", synthetic_outcome=(mode == "fake"),
            task_definitions=DUMMY_I144_V02_TASK_DEFINITIONS,
            basis_compiler=_basis_compiler, spec_builder=v02_make_spec,
        )
    report = {"schema": PROTOCOL + "-verification", "status": "passed", "mode": mode,
              "run_id": run_id, "code_commit": _commit(),
              "sdk_version": importlib.metadata.version("openhands-sdk"),
              "split_report_sha256": _sha_file(SPLIT_REPORT),
              "source_report_sha256": _sha_file(SOURCE_REPORT),
              "runtime_lock_sha256": _sha_file(RUNTIME_LOCK),
              "model_requests": summary["model_requests"], "accepted_slots": summary["accepted_slots"],
              "gate_records": summary["gate_records"],
              "real_model_calls": 0 if mode == "fake" else summary["model_requests"],
              "official_test_read": False, "official_test_ood_read": False,
              "outcome_dev_read": True,
              "provider_calls": None if provider is None else provider.calls,
              "round_summary_sha256": _sha_file(output / "round/round-summary.json"),
              "budget": ledger.summary()}
    expected = len(_slot_ids())
    if report["model_requests"] != expected or report["accepted_slots"] != expected:
        raise RuntimeError("v02 preflight did not complete every slot")
    if mode == "fake":
        CERTIFICATE.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "run_id": run_id,
                      "model_requests": report["model_requests"], "accepted_slots": report["accepted_slots"],
                      "gate_records": report["gate_records"], "real_model_calls": report["real_model_calls"]},
                     ensure_ascii=False, sort_keys=True))
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("fake", "real"), default="fake")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--auth-file")
    args = parser.parse_args()
    raise SystemExit(run(args.run_id, mode=args.mode, auth_file=args.auth_file) and 0)
