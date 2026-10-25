"""Runner primitives for the frozen replacement-sufficiency round.

This module owns the host side of the new 12-slot experiment.  It deliberately
does not create an OpenHands conversation; callers inject an ``actor_runner``
so the same sequencing can be exercised with FakeProvider before any network
request is authorized.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from analysis.replacement_evidence.triplet_runner import evaluate_triplet
from extensions.symbolic_basis_v01.contract import compile_submission, make_spec
from rsi_eval.basis_actor_evidence import bind_accepted_submission
from rsi_eval.replacement_condition_gate import CONDITIONS, apply_gate
from rsi_eval.symbolic import score_predictions
from rsi_eval.replacement_shadow_outcome import attach_shadow_outcomes, freeze_gate_decisions
from analysis.replacement_evidence.outcome_prediction import run_outcome_prediction


VERSION = "replacement-agent-round-runner-v0.1"
SPLIT_REPORT = "docs/environment/2026-10-24-replacement-dev-splits.json"
HOST_EXPLANATION = "Host-generated execution payload; actor explanation is archived only."
FIT_PROTOCOL = {
    "optimizer": "scipy_least_squares",
    "initial_params": "ones",
    "max_nfev": 100,
    "runtime": "symbolic-diagnostic-v01-locked",
    "metric_scope": "check_dev_nmse_population_variance",
}


@dataclass(frozen=True)
class ParentDefinition:
    parent_id: str
    feature_ids: tuple[str, ...]


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    input_names: tuple[str, ...]
    headers: tuple[str, ...]
    target: str
    parents: tuple[ParentDefinition, ...]


@dataclass(frozen=True)
class SplitData:
    split_name: str
    split_sha256: str
    row_indices: tuple[int, ...]
    X: tuple[tuple[float, ...], ...]
    y: tuple[float, ...]

    def request(self) -> dict[str, Any]:
        return {
            "split_name": self.split_name,
            "split_sha256": self.split_sha256,
            "X": [list(row) for row in self.X],
            "y": list(self.y),
        }


@dataclass(frozen=True)
class FrozenTask:
    definition: TaskDefinition
    source_path: str
    source_sha256: str
    manifest_sha256: str
    splits: Mapping[str, SplitData]


TASK_DEFINITIONS = (
    TaskDefinition(
        task_id="bactgrow",
        input_names=("b", "s", "temp", "pH"),
        headers=("b", "s", "temp", "pH", "db"),
        target="db",
        parents=(
            ParentDefinition("bactgrow-p01", ("m_0_0_0_0", "m_1_0_0_0", "m_0_1_0_0", "m_0_0_1_0")),
            ParentDefinition("bactgrow-p02", ("m_0_0_0_0", "m_1_0_0_0", "m_0_1_0_0", "m_0_0_0_1")),
            ParentDefinition("bactgrow-p03", ("m_0_0_0_0", "m_1_0_0_0", "m_0_0_1_0", "m_0_0_0_1")),
        ),
    ),
    TaskDefinition(
        task_id="stressstrain",
        input_names=("strain", "temp"),
        headers=("strain", "temp", "stress"),
        target="stress",
        parents=(
            ParentDefinition("stressstrain-p01", ("m_0_0", "m_1_0", "m_0_1", "m_1_1")),
            ParentDefinition("stressstrain-p02", ("m_0_0", "m_1_0", "m_0_1", "m_2_0")),
            ParentDefinition("stressstrain-p03", ("m_0_0", "m_1_0", "m_0_1", "m_0_2")),
        ),
    ),
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: Any) -> str:
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return hashlib.sha256(_canonical(value)).hexdigest()


def _verify_self_hash(value: Mapping[str, Any], field: str, name: str) -> str:
    expected = value.get(field)
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError(f"{name} missing {field}")
    body = dict(value)
    body.pop(field)
    actual = _sha(body)
    if actual.lower() != expected.lower():
        raise ValueError(f"{name} hash mismatch")
    return expected.lower()


def _float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be finite")
    return result


def _read_rows(path: Path, definition: TaskDefinition) -> tuple[list[dict[str, str]], str]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != definition.headers:
            raise ValueError(f"{definition.task_id} source headers mismatch")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{definition.task_id} source is empty")
    return rows, digest


def _split_data(rows: list[dict[str, str]], definition: TaskDefinition,
                split_name: str, payload: Mapping[str, Any], source_sha256: str) -> SplitData:
    indices = payload.get("row_indices")
    if (not isinstance(indices, list) or any(type(i) is not int or i < 0 or i >= len(rows) for i in indices)
            or len(set(indices)) != len(indices) or len(indices) != payload.get("n")):
        raise ValueError(f"{definition.task_id}/{split_name} row-index manifest invalid")
    data_hash = payload.get("data_sha256")
    row_hash = payload.get("row_index_sha256")
    if (not isinstance(data_hash, str) or len(data_hash) != 64
            or not isinstance(row_hash, str) or len(row_hash) != 64):
        raise ValueError(f"{definition.task_id}/{split_name} data hash invalid")
    if _sha(indices) != row_hash.lower():
        raise ValueError(f"{definition.task_id}/{split_name} row-index hash mismatch")
    if _sha({"source_data_sha256": source_sha256.lower(), "row_indices": indices}) != data_hash.lower():
        raise ValueError(f"{definition.task_id}/{split_name} data hash mismatch")
    X: list[tuple[float, ...]] = []
    y: list[float] = []
    for index in indices:
        row = rows[index]
        X.append(tuple(_float(row[name], f"{definition.task_id}.{name}") for name in definition.input_names))
        y.append(_float(row[definition.target], f"{definition.task_id}.{definition.target}"))
    return SplitData(split_name, data_hash.lower(), tuple(indices), tuple(X), tuple(y))


def load_frozen_tasks(
    root: Path,
    report_path: Path | None = None,
    task_definitions: tuple[TaskDefinition, ...] = TASK_DEFINITIONS,
) -> dict[str, FrozenTask]:
    """Load the configured frozen train manifests and recheck source hashes."""

    report_file = (root / SPLIT_REPORT) if report_path is None else Path(report_path)
    report = json.loads(report_file.read_text(encoding="utf-8"))
    if report.get("official_test_read") or report.get("official_test_ood_read"):
        raise ValueError("split report claims official test data was read")
    _verify_self_hash(report, "report_sha256", "split report")
    definitions = {item.task_id: item for item in task_definitions}
    if set(report.get("tasks", {})) != set(definitions):
        raise ValueError("split report task set differs from protocol")
    result: dict[str, FrozenTask] = {}
    for task_id, definition in definitions.items():
        entry = report["tasks"][task_id]
        path = root / entry["source_path"]
        rows, source_sha = _read_rows(path, definition)
        if source_sha != entry.get("source_sha256", "").lower() or len(rows) != entry.get("row_count"):
            raise ValueError(f"{task_id} source provenance mismatch")
        manifest = entry.get("manifest")
        if not isinstance(manifest, dict) or manifest.get("task_id") != task_id:
            raise ValueError(f"{task_id} manifest missing")
        manifest_sha = _verify_self_hash(manifest, "manifest_sha256", f"{task_id} manifest")
        source_manifest = manifest.get("source", {})
        if (source_manifest.get("data_sha256") != source_sha
                or source_manifest.get("row_count") != len(rows)
                or tuple(source_manifest.get("headers", ())) != definition.headers
                or source_manifest.get("official_test_read")
                or source_manifest.get("official_test_ood_read")):
            raise ValueError(f"{task_id} manifest source binding mismatch")
        if set(manifest.get("split_order", ())) != {"fit_dev", "check_dev", "outcome_dev"}:
            raise ValueError(f"{task_id} split order mismatch")
        splits = {
            split: _split_data(rows, definition, split, manifest["splits"][split], source_sha)
            for split in ("fit_dev", "check_dev", "outcome_dev")
        }
        all_indices = [index for data in splits.values() for index in data.row_indices]
        if sorted(all_indices) != list(range(len(rows))):
            raise ValueError(f"{task_id} split rows are not a disjoint partition")
        result[task_id] = FrozenTask(definition, entry["source_path"], source_sha,
                                     manifest_sha, splits)
    return result


def compile_basis(definition: TaskDefinition, feature_ids: list[str] | tuple[str, ...]) -> dict[str, Any]:
    spec = make_spec(len(definition.input_names), len(feature_ids))
    return compile_submission({"feature_ids": list(feature_ids), "explanation": HOST_EXPLANATION}, spec)


def classify_structure_change(parent_ids: list[str], candidate_ids: list[str]) -> dict[str, Any]:
    parent = list(parent_ids)
    candidate = list(candidate_ids)
    removed = sorted(set(parent) - set(candidate))
    added = sorted(set(candidate) - set(parent))
    if candidate == parent:
        return {"status": "valid", "mode": "keep", "removed": [], "added": []}
    if len(parent) != len(candidate) or len(removed) != 1 or len(added) != 1:
        return {"status": "invalid", "mode": "invalid", "removed": removed, "added": added}
    return {"status": "valid", "mode": "swap_one", "removed": removed, "added": added}


def fit_protocol_sha256() -> str:
    return _sha(FIT_PROTOCOL)


class SandboxCache:
    """Cache immutable fit and fixed-parameter predictions for one run."""

    def __init__(self, fit_executor: Callable[[str, dict[str, Any]], Mapping[str, Any]],
                 predict_executor: Callable[[str, dict[str, Any]], Mapping[str, Any]]):
        self.fit_executor = fit_executor
        self.predict_executor = predict_executor
        self.fit_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.predict_cache: dict[tuple[str, str, str], dict[str, Any]] = {}

    def fit(self, source: str, request: dict[str, Any]) -> Mapping[str, Any]:
        key = (_sha(source.encode()), request["split_sha256"], _sha({"n_params": request["n_params"], "protocol": FIT_PROTOCOL}))
        if key not in self.fit_cache:
            self.fit_cache[key] = copy.deepcopy(dict(self.fit_executor(source, request)))
        return copy.deepcopy(self.fit_cache[key])

    def predict(self, source: str, request: dict[str, Any]) -> Mapping[str, Any]:
        params = request.get("params")
        key = (_sha(source.encode()), request["split_sha256"], _sha(params))
        if key not in self.predict_cache:
            self.predict_cache[key] = copy.deepcopy(dict(self.predict_executor(source, request)))
        return copy.deepcopy(self.predict_cache[key])


def _score_fixed(source: str, params: list[float], split: SplitData, task: TaskDefinition,
                 predict_runner: Callable[[str, dict[str, Any]], Mapping[str, Any]]) -> dict[str, Any]:
    if split.split_name == "outcome_dev":
        return run_outcome_prediction(
            source=source, params=params, X=[list(row) for row in split.X], y=list(split.y),
            task_id=task.task_id, input_names=list(task.input_names),
            split_sha256=split.split_sha256, runner=predict_runner,
        )
    request = {
        "family": "symbolic", "X": [list(row) for row in split.X],
        "task_id": task.task_id, "input_names": list(task.input_names),
        "phase": "predict", "split_name": split.split_name,
        "split_sha256": split.split_sha256, "params": list(params),
    }
    response = predict_runner(source, request)
    if response.get("status") != "completed" or not isinstance(response.get("result"), Mapping):
        return {"status": "failed", "reason": "predict_runner_status"}
    result = response["result"]
    if result.get("status") != "success":
        return {"status": "failed", "reason": "predict_result_status"}
    scored = score_predictions(list(split.y), result.get("predictions"))
    if scored.get("status") != "success":
        return {"status": "failed", "reason": "metric_unavailable"}
    return {"status": "success", "metrics": scored["metrics"]}


def _fit_feedback(task: FrozenTask, parent: Mapping[str, Any], cache: SandboxCache) -> dict[str, Any]:
    fit = task.splits["fit_dev"]
    request = {
        "family": "symbolic", "task_id": task.definition.task_id,
        "input_names": list(task.definition.input_names), "phase": "fit",
        "split_name": "fit_dev", "split_sha256": fit.split_sha256,
        "X": [list(row) for row in fit.X], "y": list(fit.y),
        "n_params": parent["n_params"],
    }
    response = cache.fit(parent["source"], request)
    if response.get("status") != "completed" or not isinstance(response.get("result"), Mapping):
        raise RuntimeError(f"baseline fit failed for {task.definition.task_id}")
    result = response["result"]
    if result.get("status") != "success":
        raise RuntimeError(f"baseline fit failed for {task.definition.task_id}")
    params = result.get("params")
    score = _score_fixed(parent["source"], params, fit, task.definition, cache.predict)
    if score.get("status") != "success":
        raise RuntimeError(f"baseline feedback score failed for {task.definition.task_id}")
    return {"split_name": "fit_dev", "split_sha256": fit.split_sha256,
            "metric_scope": "fit_dev_nmse_population_variance",
            "metrics": score["metrics"], "n_rows": len(fit.y),
            "parent_source_sha256": parent["source_sha256"]}


def _triplet_binding(task: FrozenTask, parent: Mapping[str, Any], common: Mapping[str, Any],
                     added: Mapping[str, Any], change: Mapping[str, Any]) -> dict[str, Any]:
    fit = task.splits["fit_dev"]
    check = task.splits["check_dev"]
    return {
        "task_id": task.definition.task_id,
        "split_id": f"replacement-dev-{task.manifest_sha256[:16]}",
        "fit_data_sha256": fit.split_sha256,
        "check_data_sha256": check.split_sha256,
        "parent_source_sha256": parent["source_sha256"],
        "common_source_sha256": common["source_sha256"],
        "added_source_sha256": added["source_sha256"],
        "removed_feature_id": change["removed"][0],
        "added_feature_id": change["added"][0],
        "parent_feature_ids": list(parent["feature_ids"]),
        "fit_protocol_sha256": fit_protocol_sha256(),
        "metric_scope": "check_dev_nmse_population_variance",
    }


def evaluate_swap(task: FrozenTask, parent: Mapping[str, Any], candidate: Mapping[str, Any],
                  change: Mapping[str, Any], cache: SandboxCache) -> dict[str, Any]:
    common_ids = [feature for feature in parent["feature_ids"] if feature != change["removed"][0]]
    common = compile_basis(task.definition, common_ids)
    structures = {
        "parent": {key: parent[key] for key in ("source", "source_sha256", "n_params")},
        "common": {key: common[key] for key in ("source", "source_sha256", "n_params")},
        "added": {key: candidate[key] for key in ("source", "source_sha256", "n_params")},
    }
    binding = _triplet_binding(task, parent, common, candidate, change)
    result = evaluate_triplet(
        structures=structures,
        fit_data=task.splits["fit_dev"].request(),
        check_data=task.splits["check_dev"].request(),
        task_id=task.definition.task_id,
        input_names=list(task.definition.input_names), binding=binding,
        fit_runner=cache.fit, predict_runner=cache.predict,
    )
    return {"triplet": result, "common": common, "binding": binding}


def run_round(*, tasks: Mapping[str, FrozenTask], actor_runner: Callable[..., Mapping[str, Any]],
              fit_executor: Callable[[str, dict[str, Any]], Mapping[str, Any]],
              predict_executor: Callable[[str, dict[str, Any]], Mapping[str, Any]],
              output_dir: Path, synthetic_outcome: bool = False,
              task_definitions: tuple[TaskDefinition, ...] = TASK_DEFINITIONS) -> dict[str, Any]:
    """Run the configured slots, freeze gates, then attach outcome shadow scores."""

    if set(tasks) != {item.task_id for item in task_definitions}:
        raise ValueError("run task set does not match the configured protocol tasks")
    output_dir.mkdir(parents=True, exist_ok=False)
    cache = SandboxCache(fit_executor, predict_executor)
    records: list[dict[str, Any]] = []
    gate_rows: list[dict[str, Any]] = []
    accepted_slot_ids: list[str] = []

    def stop_round(reason: str, *, slot_id: str, details: Mapping[str, Any] | None = None):
        payload = {
            "schema": VERSION, "status": "stopped", "reason": reason,
            "slot_id": slot_id, "accepted_slot_ids": list(accepted_slot_ids),
            "accepted_slots": len(accepted_slot_ids),
            "gate_records": len(gate_rows),
        }
        if details:
            payload["details"] = dict(details)
        (output_dir / "round-stop.json").write_text(
            json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(reason)

    for definition in task_definitions:
        task = tasks[definition.task_id]
        for parent_def in definition.parents:
            parent = compile_basis(definition, parent_def.feature_ids)
            for repeat in (1, 2):
                slot_id = f"{parent_def.parent_id}-r{repeat}"
                try:
                    feedback = _fit_feedback(task, parent, cache)
                except Exception as exc:
                    stop_round("baseline_feedback_failure", slot_id=slot_id,
                               details={"error_type": type(exc).__name__})
                packet = {
                    "schema": VERSION, "slot_id": slot_id,
                    "task": {"task_id": definition.task_id, "input_names": list(definition.input_names)},
                    "parent": {"feature_ids": list(parent["feature_ids"]),
                               "source_sha256": parent["source_sha256"], "n_params": parent["n_params"]},
                    "candidate_constraints": {
                        "allowed_modes": ["keep", "swap_one"],
                        "constant_feature_id": parent["feature_ids"][0],
                        "constant_must_be_retained": True,
                    },
                    "feedback": feedback, "condition_blind": True,
                    "output_contract": "submit_basis with feature_ids only",
                }
                session_dir = output_dir / "sessions" / slot_id
                accepted = actor_runner(slot_id=slot_id, packet=packet, spec=make_spec(len(definition.input_names), len(parent["feature_ids"])), output_dir=session_dir)
                if accepted.get("status") != "accepted":
                    stop_round("actor_not_accepted", slot_id=slot_id,
                               details={"sdk_status": accepted.get("status"),
                                        "error_type": accepted.get("error_type")})
                candidate = accepted.get("compiled")
                if not isinstance(candidate, Mapping):
                    stop_round("actor_missing_compiled_candidate", slot_id=slot_id)
                accepted_slot_ids.append(slot_id)
                change = classify_structure_change(parent["feature_ids"], candidate["feature_ids"])
                if change["status"] != "valid":
                    stop_round("invalid_structural_edit", slot_id=slot_id,
                               details={"parent_feature_ids": list(parent["feature_ids"]),
                                        "candidate_feature_ids": list(candidate["feature_ids"]),
                                        "removed": change["removed"], "added": change["added"]})
                if change["mode"] == "keep":
                    evidence = {"status": "unknown", "decision_reason": "no_edit"}
                    triplet = None
                    check_id = f"replacement-check-{slot_id}"
                else:
                    evaluated = evaluate_swap(task, parent, candidate, change, cache)
                    triplet = evaluated["triplet"]
                    evidence = triplet["evidence"]
                    check_id = f"replacement-check-{slot_id}"
                bound = bind_accepted_submission(
                    # The SDK receipt preserves the actor's order, while the
                    # trusted compiler returns canonical catalog order.  Edit
                    # identity must use the latter so a keep is not mistaken
                    # for a structural change.
                    {"status": "accepted",
                     "business": {"feature_ids": list(candidate["feature_ids"])},
                     "execution_payload": {"feature_ids": list(candidate["feature_ids"]) }},
                    task_id=definition.task_id,
                    parent_source_sha256=parent["source_sha256"],
                    candidate_source_sha256=candidate["source_sha256"],
                    parent_feature_ids=list(parent["feature_ids"]),
                    check_id=check_id, check_status=evidence["status"], check_scope="development",
                )
                for condition in CONDITIONS:
                    gate = apply_gate(
                        bound["edit"], condition=condition,
                        check_id=f"gate-{condition}-{slot_id}",
                        replacement_status=evidence["status"] if condition == "replacement_check" else None,
                        scope="development",
                    )
                    gate_rows.append({
                        "proposal_id": slot_id, "condition": condition,
                        "edit_id": bound["edit"]["edit_id"],
                        "final_action": gate["final_action"],
                        "check_status": gate["decision"]["pre_edit_check_status"],
                        "check_applicability": gate.get("check_applicability", "applicable"),
                    })
                records.append({
                    "slot_id": slot_id, "task_id": definition.task_id,
                    "parent_id": parent_def.parent_id, "repeat": repeat,
                    "sdk_status": accepted["status"], "edit_mode": change["mode"],
                    "parent_feature_ids": list(parent["feature_ids"]),
                    "candidate_feature_ids": list(candidate["feature_ids"]),
                    "parent_source_sha256": parent["source_sha256"],
                    "candidate_source_sha256": candidate["source_sha256"],
                    "evidence": evidence, "triplet": triplet,
                })
    if len(records) != 12 or len(gate_rows) != 36:
        raise RuntimeError("round did not produce exactly 12 proposals and 36 gate rows")
    frozen = freeze_gate_decisions(gate_rows)

    outcomes: dict[str, dict[str, Any]] = {}
    for record in records:
        task = tasks[record["task_id"]]
        outcome_split = task.splits["outcome_dev"]
        parent_source = next(
            compile_basis(task.definition, parent.feature_ids)
            for parent in task.definition.parents if parent.parent_id == record["parent_id"]
        )
        parent_params: list[float] | None = None
        candidate_params: list[float] | None = None
        if record["edit_mode"] == "keep":
            # Reuse the immutable parent fit in the per-run cache.
            fit_request = {
                "family": "symbolic", "task_id": task.definition.task_id,
                "input_names": list(task.definition.input_names), "phase": "fit",
                "split_name": "fit_dev", "split_sha256": task.splits["fit_dev"].split_sha256,
                "X": [list(row) for row in task.splits["fit_dev"].X],
                "y": list(task.splits["fit_dev"].y), "n_params": parent_source["n_params"],
            }
            fit_result = cache.fit(parent_source["source"], fit_request)
            parent_params = fit_result.get("result", {}).get("params")
            candidate_params = parent_params
        else:
            triplet = record["triplet"] or {}
            parent_params = (triplet.get("fit_records", {}).get("parent", {}).get("params"))
            candidate_params = (triplet.get("fit_records", {}).get("added", {}).get("params"))
        parent_score = ({"status": "failed"} if parent_params is None else
                        _score_fixed(parent_source["source"], parent_params, outcome_split,
                                     task.definition, cache.predict))
        candidate_score = parent_score
        if record["edit_mode"] == "swap_one" and candidate_params is not None:
            candidate = compile_basis(task.definition, record["candidate_feature_ids"])
            candidate_score = _score_fixed(candidate["source"], candidate_params, outcome_split,
                                           task.definition, cache.predict)
        if parent_score.get("status") != "success" or candidate_score.get("status") != "success":
            outcomes[record["slot_id"]] = {
                "parent_nmse": 0.0 if parent_score.get("status") != "success" else parent_score["metrics"]["nmse"],
                "candidate_nmse": None,
                "edit_mode": record["edit_mode"], "candidate_status": "candidate_failure",
            }
        else:
            outcomes[record["slot_id"]] = {
                "parent_nmse": parent_score["metrics"]["nmse"],
                "candidate_nmse": candidate_score["metrics"]["nmse"],
                "edit_mode": record["edit_mode"],
                "candidate_status": "reused_keep" if record["edit_mode"] == "keep" else "success",
            }
    shadow = attach_shadow_outcomes(frozen, outcomes)
    summary = {
        "schema": VERSION, "status": "passed", "model_requests": 12,
        "accepted_slots": len(records), "gate_records": len(gate_rows),
        "official_test_read": False, "official_test_ood_read": False,
        "outcome_dev_read": True, "synthetic_actor": bool(synthetic_outcome),
        "task_sources": {task_id: {"source_path": task.source_path,
                                    "source_sha256": task.source_sha256,
                                    "manifest_sha256": task.manifest_sha256}
                         for task_id, task in tasks.items()},
        "records": records, "frozen_gates": frozen, "shadow": shadow,
        "cache": {"fit_calls": len(cache.fit_cache), "predict_calls": len(cache.predict_cache)},
    }
    (output_dir / "round-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return summary

