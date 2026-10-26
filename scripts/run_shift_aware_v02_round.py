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
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("DO_NOT_TRACK", "1")

from analysis.replacement_evidence.cross_task_config import CROSS_TASK_DEFINITIONS
from analysis.replacement_evidence.round_runner import TASK_DEFINITIONS, compile_basis, load_frozen_tasks, run_round
from extensions.basis_trial_v02 import sdk_controller
from extensions.symbolic_basis_v01.executor import check_runtime, sandbox_call
from rsi_eval.pilot_budget import BudgetLedger


ALL_TASK_DEFINITIONS = TASK_DEFINITIONS + CROSS_TASK_DEFINITIONS
SHIFT_REPORT = ROOT / "docs/environment/2026-10-26-shift-aware-dev-v02.json"
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
        output / "budget-ledger.json", max_requests=24,
        max_requests_per_session=1, max_output_tokens=8192,
        max_input_bytes=98304, max_reserved_tokens=600000,
        max_cost_cny=4, session_ids=_slot_ids(),
    )


def run(run_id: str) -> dict:
    output = ROOT / "runs/replacement-shift-aware-v02" / run_id
    if output.exists():
        raise FileExistsError("v02 output already exists; no resume")
    check_runtime()
    tasks = load_frozen_tasks(ROOT, SHIFT_REPORT, task_definitions=ALL_TASK_DEFINITIONS)
    output.mkdir(parents=True, exist_ok=False)
    ledger = _make_ledger(output)
    settings = sdk_controller.public_settings() | {"api_key": "synthetic-no-network-key"}
    provider = sdk_controller.FakeProvider(_fake_responses())

    def actor_runner(*, slot_id, packet, spec, output_dir):
        return sdk_controller.run_session(
            ROOT, output_dir, slot_id, packet, ledger, settings,
            stage="actor", spec=spec,
        )

    with patch("openhands.sdk.llm.llm.litellm_completion", provider):
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
        "mode": "fake",
        "sdk_version": importlib.metadata.version("openhands-sdk"),
        "model_requests": summary["model_requests"],
        "accepted_slots": summary["accepted_slots"],
        "gate_records": summary["gate_records"],
        "outcome_dev_read": summary["outcome_dev_read"],
        "official_test_read": False,
        "official_test_ood_read": False,
        "real_model_calls": 0,
        "provider_calls": provider.calls,
        "task_count": len(ALL_TASK_DEFINITIONS),
        "proposal_count": len(summary["records"]),
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
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = run(args.run_id)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

