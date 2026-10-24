from pathlib import Path

from analysis.replacement_evidence.outcome_prediction import run_outcome_prediction
from analysis.replacement_evidence.round_runner import (
    SplitData,
    FrozenTask,
    TASK_DEFINITIONS,
    classify_structure_change,
    run_round,
)
from rsi_eval.replacement_condition_gate import CONDITIONS


def test_structure_change_accepts_keep_and_one_swap_only():
    parent = ["m_0_0", "m_1_0", "m_0_1"]
    assert classify_structure_change(parent, parent)["mode"] == "keep"
    assert classify_structure_change(parent, ["m_0_0", "m_1_0", "m_2_0"])["mode"] == "swap_one"
    assert classify_structure_change(parent, ["m_0_0", "m_2_0", "m_2_1"])["status"] == "invalid"


def test_outcome_prediction_omits_targets_and_binds_outcome_split():
    observed = []

    def runner(source, request):
        observed.append(request)
        assert request["split_name"] == "outcome_dev"
        assert "y" not in request
        return {"status": "completed", "result": {"status": "success", "predictions": [1.0, 2.0]}}

    result = run_outcome_prediction(
        source="source", params=[1.0], X=[[0.0], [1.0]], y=[1.0, 2.0],
        task_id="fixture", input_names=["x"], split_sha256="a" * 64, runner=runner,
    )
    assert result["status"] == "success"
    assert len(observed) == 1


def _fixture_tasks():
    tasks = {}
    for definition in TASK_DEFINITIONS:
        splits = {}
        for split in ("fit_dev", "check_dev", "outcome_dev"):
            splits[split] = SplitData(
                split, ("a" if split == "fit_dev" else "b" if split == "check_dev" else "c") * 64,
                (0, 1), ((0.0,) * len(definition.input_names), (1.0,) * len(definition.input_names)),
                (1.0, 2.0),
            )
        tasks[definition.task_id] = FrozenTask(
            definition, f"data/{definition.task_id}/train.csv", "d" * 64, "e" * 64, splits,
        )
    return tasks


def test_fake_actor_round_has_twelve_slots_and_replacement_condition_names(tmp_path):
    tasks = _fixture_tasks()
    calls = []

    def actor_runner(*, slot_id, packet, spec, output_dir):
        output_dir.mkdir(parents=True)
        parent = list(packet["parent"]["feature_ids"])
        candidate = list(parent)
        if slot_id.endswith("-r2"):
            replacement = next(feature for feature in spec["feature_ids"] if feature not in parent)
            candidate[-1] = replacement
        compiled = __import__("analysis.replacement_evidence.round_runner", fromlist=["compile_basis"]).compile_basis(
            tasks[packet["task"]["task_id"]].definition, candidate,
        )
        calls.append(slot_id)
        return {"status": "accepted", "business": {"feature_ids": candidate},
                "execution_payload": {"feature_ids": candidate}, "compiled": compiled}

    def fit_runner(source, request):
        return {"status": "completed", "result": {"status": "success",
                "params": [1.0] * request["n_params"], "converged": True,
                "nfev": 1, "candidate_calls": 1}}

    def predict_runner(source, request):
        return {"status": "completed", "result": {"status": "success",
                "predictions": [1.0, 2.0]}}

    result = run_round(tasks=tasks, actor_runner=actor_runner,
                       fit_executor=fit_runner, predict_executor=predict_runner,
                       output_dir=Path(tmp_path) / "round", synthetic_outcome=True)
    assert len(calls) == 12
    assert result["accepted_slots"] == 12
    assert result["gate_records"] == 36
    assert result["outcome_dev_read"] is True
    assert result["frozen_gates"]["frozen"]["conditions"] == list(CONDITIONS)
    assert set(result["shadow"]["summary"]) == set(CONDITIONS)

