"""One-shot runner for the frozen three-condition edit-gate pilot.

The runner deliberately separates model generation, gate freezing, and shadow
scoring.  In ``run`` mode the only network operation is the six OpenHands
provider requests; task evaluation stays in the trusted local executor.
"""

from __future__ import annotations

import copy
import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

from extensions.basis_trial_v02 import sdk_controller
from extensions.symbolic_basis_v01.contract import compile_submission, make_spec
from rsi_eval.basis_actor_evidence import bind_accepted_submission
from rsi_eval.edit_condition_gate import CONDITIONS, apply_gate
from rsi_eval.edit_evidence import build_edit
from rsi_eval.evidence_checks import VERSION as EVIDENCE_VERSION
from rsi_eval.evidence_ids import EvidenceRegistry
from rsi_eval.pilot_budget import BudgetLedger

from .protocol import build_protocol, validate_protocol
from .shadow_outcome import attach_shadow_outcomes, freeze_gate_decisions
from rsi_eval.targeted_edit_check import evaluate_targeted_claim


ROOT = Path(__file__).resolve().parents[2]
VERSION = "basis-edit-runner-v0.1"
Evaluate = Callable[..., dict[str, Any]]


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                     sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _packet(protocol: dict[str, Any], parent: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    fitting = baseline.get("fitting", {})
    metrics = baseline.get("metrics", {})
    return {
        "version": VERSION,
        "task": protocol["task"],
        "instruction": (
            "Submit exactly one keep-or-one-feature-swap revision of the supplied "
            "four-term monomial basis. Return only feature_ids. The host owns "
            "coefficients, checks, execution and scoring."
        ),
        "parent": {"parent_id": parent["parent_id"], "feature_ids": parent["feature_ids"],
                   "source_sha256": parent["source_sha256"], "n_params": parent["n_params"]},
        "feedback": {"metric_scope": "train", "metrics": metrics,
                     "coefficients": fitting.get("params", []),
                     "fit_metadata": {key: fitting.get(key) for key in
                                      ("nfev", "candidate_calls", "converged")}},
        "condition_blind": True,
        "output_contract": "submit_basis with feature_ids only",
    }


def _evidence_for_swap(slot_id: str, parent: dict[str, Any], baseline: dict[str, Any],
                       edit: dict[str, Any], threshold: float) -> tuple[str, dict[str, Any]]:
    if edit["mode"] == "keep":
        return "unknown", {"status": "not_applicable", "reason": "no_edit"}
    removed = edit["removed_feature_ids"][0]
    params = baseline.get("fitting", {}).get("params")
    if type(params) is not list or len(params) != len(parent["feature_ids"]):
        return "unknown", {"status": "unavailable", "reason": "parent_coefficients_missing"}
    coefficient = dict(zip(parent["feature_ids"], params)).get(removed)
    if type(coefficient) not in (int, float):
        return "unknown", {"status": "unavailable", "reason": "removed_coefficient_missing"}
    binding = {
        "session_id": slot_id, "candidate_id": parent["parent_id"],
        "candidate_sha256": parent["source_sha256"],
        "task_id": "oscillator2", "version": EVIDENCE_VERSION, "scope": "development",
    }
    registry = EvidenceRegistry([{
        "binding": binding,
        "scalars": {"abs_coefficient:" + removed: abs(float(coefficient))},
        "facts": {},
    }], session_id=slot_id)
    entry = next(item for item in registry.entries()
                 if item["key"] == "abs_coefficient:" + removed)
    checked = evaluate_targeted_claim(
        edit, registry,
        {"evidence_id": entry["evidence_id"], "op": "lt", "value": threshold},
        check_id="targeted-" + slot_id,
    )
    return checked["checked_edit"]["check_status"], checked


def _safe_evaluate(evaluate: Evaluate, *, root: Path, source: str, candidate_id: str,
                   parent_id: str | None) -> dict[str, Any]:
    try:
        result = evaluate("symbolic", "oscillator2", source, root=root, n_params=4,
                          candidate_id=candidate_id, parent_id=parent_id,
                          strategy_version=VERSION)
    except Exception as error:  # raw exception text is never persisted
        return {"status": "candidate_failure", "error_type": type(error).__name__}
    if type(result) is not dict:
        return {"status": "candidate_failure", "error_type": "invalid_evaluator_result"}
    return result


def run_pilot(root: Path | str, output: Path | str, *, settings: dict[str, Any],
              evaluate: Evaluate, provider: Any = None, session_runner: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """Run the full sequencing with either a real or synthetic provider."""

    root, output = Path(root).resolve(), Path(output).resolve()
    output.relative_to(root)
    if output.exists():
        raise FileExistsError("pilot output already exists; no resume")
    protocol = validate_protocol(build_protocol())
    output.mkdir(parents=True)
    _write(output / "protocol.json", protocol)
    spec = make_spec(3, 4)
    slots = protocol["slots"]
    ledger = BudgetLedger(output / "budget-ledger.json", max_requests=6,
                          max_requests_per_session=1, max_output_tokens=8192,
                          max_reserved_tokens=2_000_000, max_cost_cny=4,
                          session_ids=[slot["slot_id"] for slot in slots])
    parents: dict[str, dict[str, Any]] = {}
    for parent_id, parent in protocol["parents"].items():
        compiled = compile_submission(
            {"feature_ids": parent["feature_ids"], "explanation": "host parent"}, spec)
        baseline = _safe_evaluate(evaluate, root=root, source=compiled["source"],
                                  candidate_id="parent-" + parent_id, parent_id=None)
        if baseline.get("status") != "success":
            summary = {"version": VERSION, "status": "stopped",
                       "failure": {"stage": "baseline", "parent_id": parent_id,
                                   "error_type": baseline.get("error_type", "baseline_failed")},
                       "budget": ledger.summary(), "model_requests": 0}
            _write(output / "summary.json", summary)
            return summary
        parents[parent_id] = {"protocol": copy.deepcopy(parent), "compiled": compiled,
                              "baseline": baseline}
    _write(output / "baselines.json", parents)

    gate_rows: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    session_runner = session_runner or sdk_controller.run_session
    context = patch("openhands.sdk.llm.llm.litellm_completion", provider) if provider is not None else nullcontext()
    with context:
        for slot in slots:
            parent_record = parents[slot["parent_id"]]
            parent = parent_record["protocol"]
            packet = _packet(protocol, parent, parent_record["baseline"])
            session_dir = output / "sessions" / slot["slot_id"]
            result = session_runner(
                root, session_dir, slot["slot_id"], packet, ledger, settings,
                stage="actor", spec=spec,
            )
            if result.get("status") != "accepted":
                summary = {"version": VERSION, "status": "stopped",
                           "failure": {"stage": "model", "slot_id": slot["slot_id"],
                                       "error_type": result.get("error_type", "model_rejected")},
                           "completed_slots": len(candidates), "budget": ledger.summary(),
                           "model_requests": ledger.summary()["request_count"]}
                _write(output / "summary.json", summary)
                return summary
            candidate = result["compiled"]
            accepted = {"status": "accepted", "business": result["business"],
                        "execution_payload": result["execution_payload"]}
            edit = build_edit(
                task_id="oscillator2",
                parent_source_sha256=parent["source_sha256"],
                candidate_source_sha256=candidate["source_sha256"],
                parent_feature_ids=parent["feature_ids"],
                candidate_feature_ids=result["business"]["feature_ids"],
            )
            check_status, check_result = _evidence_for_swap(
                slot["slot_id"], parent, parent_record["baseline"], edit,
                protocol["conditions"]["real_check"]["threshold"],
            )
            edit_record = bind_accepted_submission(
                accepted, task_id="oscillator2",
                parent_source_sha256=parent["source_sha256"],
                candidate_source_sha256=candidate["source_sha256"],
                parent_feature_ids=parent["feature_ids"], check_id="targeted-" + slot["slot_id"],
                check_status=check_status, check_scope="development",
            )
            condition_records = []
            for condition in CONDITIONS:
                gate = apply_gate(
                    edit_record["edit"], condition=condition,
                    check_id=f"gate-{condition}-{slot['slot_id']}",
                    real_status=check_status if condition == "real_check" else None,
                )
                condition_records.append(gate)
                gate_rows.append({
                    "proposal_id": slot["slot_id"], "condition": condition,
                    "edit_id": edit["edit_id"],
                    "final_action": gate["final_action"],
                    "check_status": gate["decision"]["pre_edit_check_status"],
                    "check_applicability": gate.get("check_applicability", "applicable"),
                })
            candidates.append({"slot": slot, "parent": parent, "session": result,
                               "edit": edit_record, "raw_check": check_result,
                               "gates": condition_records})
    _write(output / "candidates.json", candidates)
    _write(output / "gate-rows.json", gate_rows)
    frozen = freeze_gate_decisions(gate_rows)
    _write(output / "gate-freeze.json", frozen)

    outcomes = {}
    for record in candidates:
        slot = record["slot"]
        parent_record = parents[slot["parent_id"]]
        parent_nmse = parent_record["baseline"]["metrics"]["nmse"]
        if record["edit"]["edit"]["mode"] == "keep":
            outcomes[slot["slot_id"]] = {
                "parent_nmse": parent_nmse, "candidate_nmse": parent_nmse,
                "edit_mode": "keep", "candidate_status": "reused_keep",
            }
            continue
        scored = _safe_evaluate(
            evaluate, root=root, source=record["session"]["compiled"]["source"],
            candidate_id="shadow-" + slot["slot_id"], parent_id="parent-" + slot["parent_id"],
        )
        success = scored.get("status") == "success" and scored.get("metrics", {}).get("nmse") is not None
        outcomes[slot["slot_id"]] = {
            "parent_nmse": parent_nmse,
            "candidate_nmse": scored.get("metrics", {}).get("nmse") if success else None,
            "edit_mode": "swap_one",
            "candidate_status": "success" if success else "candidate_failure",
            "error_type": scored.get("error_kind") if not success else None,
        }
    _write(output / "shadow-inputs.json", outcomes)
    shadow = attach_shadow_outcomes(frozen, {
        key: {name: value for name, value in outcome.items()
              if name in {"parent_nmse", "candidate_nmse", "edit_mode", "candidate_status"}}
        for key, outcome in outcomes.items()
    })
    _write(output / "shadow-outcomes.json", shadow)
    summary = {"version": VERSION, "status": "complete", "protocol": protocol,
               "budget": ledger.summary(), "model_requests": ledger.summary()["request_count"],
               "baseline_count": len(parents), "candidate_count": len(candidates),
               "gate_record_count": len(gate_rows), "shadow": shadow["summary"],
               "model_weight_updates": 0, "strategy_updates": 0,
               "sealed_data_read": False}
    _write(output / "summary.json", summary)
    return summary


def synthetic_evaluate(family: str, task_id: str, source: str, *, root: Path,
                       n_params: int, candidate_id: str, parent_id: str | None,
                       strategy_version: str) -> dict[str, Any]:
    """Deterministic score fixture for local runner tests; no data access."""

    features = source.split("# Features: ", 1)[1].splitlines()[0].split(", ")
    params = [0.01 * (index + 1) for index in range(n_params)]
    nmse = 0.1 + (0.02 if features[-1] in {"m_0_2_0", "m_0_1_1"} else 0.0)
    return {"status": "success", "candidate_hash": hashlib.sha256(source.encode()).hexdigest(),
            "fitting": {"params": params, "n_params": n_params, "nfev": 1,
                         "candidate_calls": 1, "converged": True},
            "metrics": {"mse": nmse, "nmse": nmse}}
