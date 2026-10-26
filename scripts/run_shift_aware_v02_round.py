#!/usr/bin/env python3
"""Run a four-task v02 fake round on the train-only shift-aware manifest.

This is an integration preflight: it uses the real OpenHands SDK boundary and
locked symbolic sandbox, but a synthetic provider.  It does not read official
test files and does not claim mechanism performance.
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
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("DO_NOT_TRACK", "1")

from analysis.replacement_evidence.cross_task_config import CROSS_TASK_DEFINITIONS
from analysis.replacement_evidence.round_runner import TASK_DEFINITIONS, TaskDefinition, load_frozen_tasks, run_round
from extensions.basis_trial_v02 import sdk_controller
from extensions.symbolic_basis_v01.executor import check_runtime, sandbox_call
from rsi_eval.pilot_budget import BudgetLedger


# The project ledger intentionally caps one session at 16 unique identifiers.
# v02 preflight therefore uses one pre-registered parent per task (2 repeats),
# giving 8 total Agent slots while retaining all four task families.  A later
# measured round can add parents in separate bounded batches.
ALL_TASK_DEFINITIONS = tuple(
    TaskDefinition(item.task_id, item.input_names, item.headers, item.target, item.parents[:1])
    for item in (TASK_DEFINITIONS + CROSS_TASK_DEFINITIONS)
)
SHIFT_REPORT = ROOT / "docs/environment/2026-10-26-shift-aware-dev-v02.json"
FAKE_CERTIFICATE = ROOT / "docs/environment/2026-10-26-shift-aware-v02-fake-verification.json"
PROTOCOL = "replacement-shift-aware-v02-preflight"


def _slot_ids() -> list[str]:
    return [f"{parent.parent_id}-r{repeat}"
            for task in ALL_TASK_DEFINITIONS
            for parent in task.parents for repeat in (1, 2)]


def _fake_responses() -> list[dict]:
    responses = []
    for definition in ALL_TASK_DEFINITIONS:
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


def _make_ledger(output: Path) -> BudgetLedger:
    return BudgetLedger(
        output / "budget-ledger.json", max_requests=8,
        max_requests_per_session=1, max_output_tokens=8192,
        max_input_bytes=98304, max_reserved_tokens=600000,
        max_cost_cny=4, session_ids=_slot_ids(),
    )


def _validate_fake_certificate() -> dict:
    certificate = json.loads(FAKE_CERTIFICATE.read_text(encoding="utf-8"))
    required = {
        "status": "passed_shift_aware_v02_fake_round",
        "task_count": 4, "proposal_count": 8, "accepted_slots": 8,
        "gate_records": 24, "model_requests": 8, "provider_calls": 8,
        "real_model_calls": 0, "outcome_dev_read": True,
        "official_test_read": False, "official_test_ood_read": False,
    }
    if any(certificate.get(key) != value for key, value in required.items()):
        raise RuntimeError("v02 fake certificate is incomplete")
    if certificate.get("split_report_sha256") != hashlib.sha256(SHIFT_REPORT.read_bytes()).hexdigest():
        raise RuntimeError("v02 fake certificate split report changed")
    current = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                             check=True, capture_output=True, text=True).stdout.strip()
    # The fake round certificate is reusable only while the core runner and
    # runtime contract remain unchanged; replay/report files may evolve.
    fake_commit = "c4fa3e105f"
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", fake_commit, current], cwd=ROOT)
    if ancestor.returncode != 0:
        raise RuntimeError("v02 fake runner commit is not an ancestor")
    return certificate


def run(mode: str, run_id: str, auth_file: str | None = None) -> dict:
    if mode not in {"fake", "real"}:
        raise ValueError("mode must be fake or real")
    if mode == "real":
        _validate_fake_certificate()
    output = ROOT / "runs/replacement-shift-aware-v02" / run_id
    if output.exists():
        raise FileExistsError("v02 output already exists; no resume")
    check_runtime()
    tasks = load_frozen_tasks(ROOT, SHIFT_REPORT, task_definitions=ALL_TASK_DEFINITIONS)
    output.mkdir(parents=True, exist_ok=False)
    ledger = _make_ledger(output)
    settings = sdk_controller.public_settings()
    provider = None
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
            output_dir=output / "round", synthetic_outcome=True,
            task_definitions=ALL_TASK_DEFINITIONS,
        )
    result = {
        "schema": PROTOCOL,
        "status": "passed",
        "run_id": run_id,
        "mode": mode,
        "sdk_version": importlib.metadata.version("openhands-sdk"),
        "model_requests": summary["model_requests"],
        "accepted_slots": summary["accepted_slots"],
        "gate_records": summary["gate_records"],
        "outcome_dev_read": summary["outcome_dev_read"],
        "official_test_read": False,
        "official_test_ood_read": False,
        "real_model_calls": 0 if mode == "fake" else summary["model_requests"],
        "provider_calls": None if provider is None else provider.calls,
        "task_count": len(ALL_TASK_DEFINITIONS),
        "proposal_count": len(summary["records"]),
        "parents_per_task": 1,
        "split_report": str(SHIFT_REPORT.relative_to(ROOT)).replace("\\", "/"),
        "split_report_sha256": hashlib.sha256(SHIFT_REPORT.read_bytes()).hexdigest(),
        "round_summary_sha256": hashlib.sha256((output / "round/round-summary.json").read_bytes()).hexdigest(),
        "budget": ledger.summary(),
    }
    (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "run_id", "task_count", "proposal_count", "model_requests", "accepted_slots", "gate_records", "real_model_calls")}, ensure_ascii=False, sort_keys=True))
    return result


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("fake", "real"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--auth-file")
    args = parser.parse_args()
    result = run(args.mode, args.run_id, args.auth_file)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

