#!/usr/bin/env python3
"""OpenHands FakeProvider preflight for the replacement-check gate sequence.

Provider replies are synthetic feature-ID submissions.  Numerical outcomes use
small in-memory fixtures; this command does not read task CSVs or call a model.
It verifies the SDK business contract and the host-side gate/freeze ordering.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.basis_edit_comparison.shadow_outcome import attach_shadow_outcomes, freeze_gate_decisions
from analysis.replacement_evidence.triplet_runner import evaluate_triplet
from extensions.basis_trial_v02 import sdk_controller
from extensions.symbolic_basis_v01.contract import compile_submission, make_spec
from rsi_eval.basis_actor_evidence import bind_accepted_submission
from rsi_eval.edit_condition_gate import CONDITIONS, apply_gate
from rsi_eval.pilot_budget import BudgetLedger
from rsi_eval.edit_evidence import build_edit


TASKS = {
    "bactgrow": {
        "input_names": ["b", "s", "temp", "pH"],
        "parent": ["m_0_0_0_0", "m_1_0_0_0", "m_0_1_0_0", "m_0_0_1_0"],
        "added": "m_0_0_0_1",
    },
    "stressstrain": {
        "input_names": ["strain", "temp"],
        "parent": ["m_0_0", "m_1_0", "m_0_1", "m_1_1"],
        "added": "m_2_0",
    },
}


def _sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _compiled(n_inputs: int, features: list[str]) -> dict:
    spec = make_spec(n_inputs, len(features))
    return compile_submission({"feature_ids": features, "explanation": "host preflight"}, spec)


def _fixture_split(task_id: str, split: str, n_inputs: int) -> dict:
    digest = _sha({"version": "replacement-agent-preflight-v0.1", "task": task_id, "split": split})
    if split == "fit_dev":
        rows = [[0.0] * n_inputs, [1.0] * n_inputs]
        y = [1.0, 2.0]
    else:
        rows = [[float(i)] * n_inputs for i in range(4)]
        y = [1.0, 2.0, 3.0, 4.0]
    return {"split_name": split, "split_sha256": digest, "X": rows, "y": y}


def _triplet(task_id: str, parent: dict, candidate: dict, *, outcome: str) -> dict:
    n_inputs = len(TASKS[task_id]["input_names"])
    common_features = [feature for feature in parent["feature_ids"] if feature != parent["feature_ids"][-1]]
    common = _compiled(n_inputs, common_features)
    structures = {
        "parent": {"source": parent["source"], "source_sha256": parent["source_sha256"],
                    "n_params": parent["n_params"]},
        "common": {"source": common["source"], "source_sha256": common["source_sha256"],
                    "n_params": common["n_params"]},
        "added": {"source": candidate["source"], "source_sha256": candidate["source_sha256"],
                   "n_params": candidate["n_params"]},
    }
    fit_data = _fixture_split(task_id, "fit_dev", n_inputs)
    check_data = _fixture_split(task_id, "check_dev", n_inputs)
    binding = {
        "task_id": task_id,
        "split_id": "replacement-agent-preflight-v0.1",
        "fit_data_sha256": fit_data["split_sha256"],
        "check_data_sha256": check_data["split_sha256"],
        "parent_source_sha256": parent["source_sha256"],
        "common_source_sha256": common["source_sha256"],
        "added_source_sha256": candidate["source_sha256"],
        "removed_feature_id": parent["feature_ids"][-1],
        "added_feature_id": TASKS[task_id]["added"],
        "parent_feature_ids": parent["feature_ids"],
        "fit_protocol_sha256": _sha({"optimizer": "fixture", "initial_params": "ones"}),
        "metric_scope": "check_dev_nmse_population_variance",
    }

    def fit_runner(source, request):
        return {"status": "completed", "result": {
            "status": "success", "params": [1.0] * request["n_params"],
            "converged": True, "nfev": 1, "candidate_calls": 1,
        }}

    def predict_runner(source, request):
        parent_source = parent["source"]
        if source == parent_source:
            predictions = [1.0, 2.0, 3.0, 4.0]
        elif source == common["source"]:
            predictions = [1.0, 2.0, 4.0, 5.0]
        elif outcome == "improve":
            predictions = [1.0, 2.0, 3.0, 4.0]
        else:
            predictions = [1.0, 2.0, 5.0, 6.0]
        return {"status": "completed", "result": {"status": "success", "predictions": predictions}}

    return evaluate_triplet(
        structures=structures, fit_data=fit_data, check_data=check_data,
        task_id=task_id, input_names=TASKS[task_id]["input_names"], binding=binding,
        fit_runner=fit_runner, predict_runner=predict_runner,
    )


def run(root: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError("preflight output already exists")
    output.mkdir(parents=True)
    session_ids = [f"{task}-r{repeat}" for task in TASKS for repeat in (1, 2)]
    ledger = BudgetLedger(output / "budget-ledger.json", max_requests=4,
                          max_requests_per_session=1, max_output_tokens=8192,
                          max_reserved_tokens=200000, max_cost_cny=4,
                          session_ids=session_ids)
    responses = []
    for task_id, config in TASKS.items():
        for repeat in (1, 2):
            features = list(config["parent"])
            if repeat == 2:
                features[-1] = config["added"]
            responses.append({"tool": "submit_basis", "arguments": {"feature_ids": features}})
    provider = sdk_controller.FakeProvider(responses)
    settings = sdk_controller.public_settings() | {"api_key": "synthetic-no-network-key"}
    records = []
    gate_rows = []
    candidates = {}
    response_index = 0
    with patch("openhands.sdk.llm.llm.litellm_completion", provider):
        for task_id, config in TASKS.items():
            spec = make_spec(len(config["input_names"]), 4)
            parent = _compiled(len(config["input_names"]), config["parent"])
            for repeat in (1, 2):
                slot_id = f"{task_id}-r{repeat}"
                packet = {
                    "version": "replacement-agent-preflight-v0.1",
                    "task": {"task_id": task_id, "input_names": config["input_names"]},
                    "parent": {"feature_ids": config["parent"], "source_sha256": parent["source_sha256"], "n_params": 4},
                    "feedback": {"metric_scope": "synthetic_fixture", "metrics": {"nmse": 0.1}},
                    "condition_blind": True,
                    "output_contract": "submit_basis with feature_ids only",
                }
                session_dir = output / "sessions" / slot_id
                result = sdk_controller.run_session(root, session_dir, slot_id, packet, ledger, settings,
                                                    stage="actor", spec=spec)
                if result.get("status") != "accepted":
                    raise RuntimeError(f"SDK preflight slot rejected: {slot_id}")
                candidate = result["compiled"]
                candidates[slot_id] = candidate
                if repeat == 1:
                    edit = build_edit(task_id=task_id, parent_source_sha256=parent["source_sha256"],
                                      candidate_source_sha256=candidate["source_sha256"],
                                      parent_feature_ids=config["parent"], candidate_feature_ids=config["parent"])
                    evidence = {"status": "unknown", "decision_reason": "no_edit"}
                else:
                    outcome_kind = "improve" if task_id == "bactgrow" else "harm"
                    triplet = _triplet(task_id, parent, candidate, outcome=outcome_kind)
                    evidence = triplet["evidence"]
                    edit = build_edit(task_id=task_id, parent_source_sha256=parent["source_sha256"],
                                      candidate_source_sha256=candidate["source_sha256"],
                                      parent_feature_ids=config["parent"],
                                      candidate_feature_ids=candidate["feature_ids"])
                accepted = {"status": "accepted", "business": result["business"],
                            "execution_payload": result["execution_payload"]}
                bound = bind_accepted_submission(
                    accepted, task_id=task_id, parent_source_sha256=parent["source_sha256"],
                    candidate_source_sha256=candidate["source_sha256"], parent_feature_ids=config["parent"],
                    check_id=f"replacement-check-{slot_id}", check_status=evidence["status"],
                    check_scope="development",
                )
                for condition in CONDITIONS:
                    gate = apply_gate(bound["edit"], condition=condition,
                                      check_id=f"gate-{condition}-{slot_id}",
                                      real_status=evidence["status"] if condition == "real_check" else None,
                                      scope="development")
                    gate_rows.append({"proposal_id": slot_id, "condition": condition,
                                      "edit_id": bound["edit"]["edit_id"],
                                      "final_action": gate["final_action"],
                                      "check_status": gate["decision"]["pre_edit_check_status"],
                                      "check_applicability": gate.get("check_applicability", "applicable")})
                records.append({"slot_id": slot_id, "task_id": task_id, "sdk_status": result["status"],
                                "edit_mode": bound["edit"]["mode"], "evidence_status": evidence["status"],
                                "evidence_reason": evidence["decision_reason"]})
                response_index += 1
    frozen = freeze_gate_decisions(gate_rows)
    synthetic_outcomes = {}
    for record in records:
        slot_id = record["slot_id"]
        if record["edit_mode"] == "keep":
            synthetic_outcomes[slot_id] = {"parent_nmse": 0.0, "candidate_nmse": 0.0,
                                           "edit_mode": "keep", "candidate_status": "reused_keep"}
        elif record["task_id"] == "bactgrow":
            synthetic_outcomes[slot_id] = {"parent_nmse": 0.0, "candidate_nmse": 0.0,
                                           "edit_mode": "swap_one", "candidate_status": "success"}
        else:
            synthetic_outcomes[slot_id] = {"parent_nmse": 0.0, "candidate_nmse": 1.0,
                                           "edit_mode": "swap_one", "candidate_status": "success"}
    shadow = attach_shadow_outcomes(frozen, synthetic_outcomes)
    summary = {
        "schema": "replacement-agent-preflight-v0.1",
        "status": "passed",
        "sdk_version": "1.55.1",
        "model_requests": ledger.summary()["request_count"],
        "accepted_slots": len(records),
        "gate_records": len(gate_rows),
        "real_model_calls": 0,
        "real_candidate_evaluations": 0,
        "synthetic_outcome_dev": True,
        "outcome_dev_read": False,
        "records": records,
        "shadow_summary": shadow["summary"],
        "provider_calls": provider.calls,
        "budget": ledger.summary(),
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    output = ROOT / "runs/replacement-agent-preflight/2026-10-24-v02"
    print(json.dumps(run(ROOT, output), ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
