#!/usr/bin/env python3
"""Run the SRSD-Feynman Easy fake-provider preflight.

This is deliberately separate from the real round: it exercises the same
OpenHands tool contract, compiler, fit/predict sandbox and gate ledger without
making any model request.  A real run is allowed only after this certificate
exists and still matches the frozen data/runtime hashes.
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

from analysis.replacement_evidence.external_task_config import EXTERNAL_TASK_DEFINITIONS
from analysis.replacement_evidence.round_runner import load_frozen_tasks, run_round
from extensions.basis_trial_v02 import sdk_controller
from extensions.symbolic_basis_v01.executor import check_runtime, sandbox_call
from rsi_eval.pilot_budget import BudgetLedger


PROTOCOL = "replacement-srsd-feynman-easy-v05"
SPLIT_REPORT = ROOT / "docs/environment/2026-10-27-srsd-feynman-easy-dev-v05.json"
SOURCE_REPORT = ROOT / "docs/environment/2026-10-27-srsd-feynman-easy-source.json"
RUNTIME_LOCK = ROOT / "extensions/symbolic_basis_v01/runtime-lock.json"
CERTIFICATE = ROOT / "docs/environment/2026-10-27-srsd-feynman-easy-v05-preflight.json"


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def _slot_ids() -> list[str]:
    return [f"{task.task_id}-p01-r{repeat}"
            for task in EXTERNAL_TASK_DEFINITIONS for repeat in (1, 2)]


def _fake_responses() -> list[dict]:
    responses = []
    for definition in EXTERNAL_TASK_DEFINITIONS:
        parent = list(definition.parents[0].feature_ids)
        spec = sdk_controller.make_spec(len(definition.input_names), len(parent))
        alternatives = [feature for feature in spec["feature_ids"] if feature not in parent]
        if not alternatives:
            raise RuntimeError(f"no replacement feature for {definition.task_id}")
        candidate = list(parent)
        candidate[-1] = alternatives[0]
        responses.extend([
            {"tool": "submit_basis", "arguments": {"feature_ids": parent}},
            {"tool": "submit_basis", "arguments": {"feature_ids": candidate}},
        ])
    return responses


def run(run_id: str) -> dict:
    output = ROOT / "runs" / PROTOCOL / run_id
    if output.exists():
        raise FileExistsError("preflight output already exists; no resume")
    check_runtime()
    tasks = load_frozen_tasks(ROOT, SPLIT_REPORT, task_definitions=EXTERNAL_TASK_DEFINITIONS)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=False, exist_ok=False)
    ledger = BudgetLedger(
        output / "budget-ledger.json", max_requests=len(_slot_ids()),
        max_requests_per_session=1, max_output_tokens=8192, max_input_bytes=98304,
        max_reserved_tokens=200000, max_cost_cny=4, session_ids=_slot_ids(),
    )
    settings = sdk_controller.public_settings() | {"api_key": "synthetic-no-network-key"}
    provider = sdk_controller.FakeProvider(_fake_responses())

    def actor_runner(*, slot_id, packet, spec, output_dir):
        return sdk_controller.run_session(
            ROOT, output_dir, slot_id, packet, ledger, settings, stage="actor", spec=spec,
        )

    with patch("openhands.sdk.llm.llm.litellm_completion", provider):
        summary = run_round(
            tasks=tasks, actor_runner=actor_runner,
            fit_executor=sandbox_call, predict_executor=sandbox_call,
            output_dir=output / "round", synthetic_outcome=True,
            task_definitions=EXTERNAL_TASK_DEFINITIONS,
        )
    report = {
        "schema": PROTOCOL + "-verification",
        "status": "passed",
        "mode": "fake",
        "run_id": run_id,
        "code_commit": _commit(),
        "sdk_version": importlib.metadata.version("openhands-sdk"),
        "split_report_sha256": _sha_file(SPLIT_REPORT),
        "source_report_sha256": _sha_file(SOURCE_REPORT),
        "runtime_lock_sha256": _sha_file(RUNTIME_LOCK),
        "model_requests": summary["model_requests"],
        "accepted_slots": summary["accepted_slots"],
        "gate_records": summary["gate_records"],
        "real_model_calls": 0,
        "official_test_read": False,
        "official_test_ood_read": False,
        "outcome_dev_read": True,
        "provider_calls": provider.calls,
        "round_summary_sha256": _sha_file(output / "round/round-summary.json"),
        "budget": ledger.summary(),
    }
    if report["model_requests"] != len(_slot_ids()) or report["accepted_slots"] != len(_slot_ids()):
        raise RuntimeError("external fake preflight did not complete every slot")
    CERTIFICATE.parent.mkdir(parents=True, exist_ok=True)
    CERTIFICATE.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "run_id": run_id,
        "model_requests": report["model_requests"], "accepted_slots": report["accepted_slots"],
        "gate_records": report["gate_records"], "real_model_calls": report["real_model_calls"],
    }, ensure_ascii=False, sort_keys=True))
    return report


def main() -> int:
    parser = __import__("argparse").ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    run(args.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
