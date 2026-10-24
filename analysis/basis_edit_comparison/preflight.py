"""OpenHands fake-provider preflight for the frozen three-condition design."""

from __future__ import annotations

import copy
import importlib.util
import tempfile
from pathlib import Path

from extensions.basis_trial_v02 import sdk_controller
from extensions.symbolic_basis_v01.contract import compile_submission, make_spec
from rsi_eval.basis_actor_evidence import bind_accepted_submission
from rsi_eval.edit_condition_gate import CONDITIONS, apply_gate
from rsi_eval.pilot_budget import BudgetLedger

from .protocol import build_protocol, validate_protocol


def _candidate(parent_features: list[str], index: int) -> list[str]:
    choices = {
        0: parent_features,
        1: parent_features[:-1] + ["m_0_2_0"],
    }
    value = choices[index % 2]
    return list(value)


def _packet(parent: dict) -> dict:
    return {
        "task": "Make one keep-or-one-swap revision of the fixed symbolic basis.",
        "parent": copy.deepcopy(parent),
        "condition_blind": True,
        "output_contract": "submit_basis with feature_ids only",
    }


def run_preflight(root: Path | str | None = None) -> dict:
    """Run six synthetic SDK slots and construct 18 gate records in memory."""

    protocol = validate_protocol(build_protocol())
    try:
        sdk_available = importlib.util.find_spec("openhands.sdk") is not None
    except ModuleNotFoundError:
        sdk_available = False
    if not sdk_available:
        return {"status": "skipped", "reason": "openhands_sdk_unavailable"}
    root = Path(root) if root is not None else Path(tempfile.mkdtemp(prefix="basis-edit-preflight-"))
    root.mkdir(parents=True, exist_ok=True)
    settings = sdk_controller.public_settings() | {"api_key": "synthetic-no-network-key"}
    ledger = BudgetLedger(root / "ledger.json", max_requests=6,
                          max_requests_per_session=1, max_output_tokens=8192,
                          max_reserved_tokens=2_000_000, max_cost_cny=4,
                          session_ids=[slot["slot_id"] for slot in protocol["slots"]])
    spec = make_spec(3, 4)
    rows = []
    for slot_index, slot in enumerate(protocol["slots"]):
        parent = protocol["parents"][slot["parent_id"]]
        candidate = _candidate(parent["feature_ids"], slot["repeat"] - 1)
        provider = sdk_controller.FakeProvider([
            {"tool": "submit_basis", "arguments": {"feature_ids": candidate}}
        ])
        output = root / slot["slot_id"]
        from unittest.mock import patch
        with patch("openhands.sdk.llm.llm.litellm_completion", provider):
            result = sdk_controller.run_session(
                root, output, slot["slot_id"], _packet(parent), ledger, settings,
                stage="actor", spec=spec,
            )
        if result.get("status") != "accepted" or provider.calls != 1:
            raise AssertionError("synthetic SDK slot was not accepted exactly once")
        parent_compiled = compile_submission(
            {"feature_ids": parent["feature_ids"], "explanation": "host"}, spec)
        accepted = {
            "status": "accepted", "business": result["business"],
            "execution_payload": result["execution_payload"],
        }
        edit_record = bind_accepted_submission(
            accepted, task_id="oscillator2",
            parent_source_sha256=parent_compiled["source_sha256"],
            candidate_source_sha256=result["compiled"]["source_sha256"],
            parent_feature_ids=parent["feature_ids"],
            check_id="preflight-real-check-" + slot["slot_id"],
            check_status="supported" if result["business"]["feature_ids"] == parent["feature_ids"]
            else "contradicted",
            check_scope="development",
        )
        for condition in CONDITIONS:
            gate = apply_gate(
                edit_record["edit"], condition=condition,
                check_id="gate-" + condition + "-" + slot["slot_id"],
                real_status=edit_record["check"]["check_status"] if condition == "real_check" else None,
            )
            rows.append({"slot_id": slot["slot_id"], "condition": condition,
                         "candidate_feature_ids": candidate,
                         "final_action": gate["final_action"],
                         "check_status": gate["decision"]["pre_edit_check_status"]})
        if slot_index != len(rows) // len(CONDITIONS) - 1:
            raise AssertionError("unexpected slot accounting")
    summary = ledger.summary()
    return {
        "status": "passed",
        "slots": len(protocol["slots"]),
        "gate_records": len(rows),
        "accepted_slots": sum(1 for slot in protocol["slots"]
                               if (root / slot["slot_id"] / "session-summary.json").is_file()),
        "model_requests": summary["request_count"],
        "usage_unknown": summary["usage_unknown_count"],
        "real_retain_parent": sum(1 for row in rows
                                   if row["condition"] == "real_check"
                                   and row["final_action"] == "retain_parent"),
        "rows": rows,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_preflight(), ensure_ascii=False, indent=2))
