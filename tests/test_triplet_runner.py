import hashlib

import pytest

from analysis.replacement_evidence.triplet_runner import evaluate_triplet


def digest(letter):
    return letter * 64


def binding():
    return {
        "task_id": "fixture",
        "split_id": "fixture-splits-v01",
        "fit_data_sha256": digest("f"),
        "check_data_sha256": digest("a"),
        "parent_source_sha256": digest("b"),
        "common_source_sha256": digest("c"),
        "added_source_sha256": digest("d"),
        "removed_feature_id": "m_1_0",
        "added_feature_id": "m_0_1",
        "parent_feature_ids": ["m_0_0", "m_1_0"],
        "fit_protocol_sha256": digest("e"),
        "metric_scope": "check_dev_nmse_population_variance",
    }


def structures():
    return {
        "parent": {"source": "parent", "source_sha256": digest("b"), "n_params": 2},
        "common": {"source": "common", "source_sha256": digest("c"), "n_params": 1},
        "added": {"source": "added", "source_sha256": digest("d"), "n_params": 2},
    }


def test_triplet_fits_all_on_fit_then_predicts_without_check_targets():
    calls = []
    predictions = {
        "parent": [1.0, 2.0, 3.0, 4.0],
        "common": [1.0, 2.0, 4.0, 5.0],
        "added": [1.0, 2.0, 3.0, 4.0],
    }

    def fit_runner(source, request):
        calls.append(("fit", source, request))
        assert request["split_name"] == "fit_dev"
        assert "y" in request
        return {"status": "completed", "result": {
            "status": "success", "params": [1.0] * request["n_params"],
            "converged": True, "nfev": 2, "candidate_calls": 2,
        }}

    def predict_runner(source, request):
        calls.append(("predict", source, request))
        assert request["split_name"] == "check_dev"
        assert "y" not in request
        return {"status": "completed", "result": {
            "status": "success", "predictions": predictions[source],
        }}

    result = evaluate_triplet(
        structures=structures(),
        fit_data={"split_name": "fit_dev", "split_sha256": digest("f"),
                  "X": [[0.0], [1.0]], "y": [1.0, 2.0]},
        check_data={"split_name": "check_dev", "split_sha256": digest("a"),
                    "X": [[0.0], [1.0], [2.0], [3.0]], "y": [1.0, 2.0, 3.0, 4.0]},
        task_id="fixture",
        input_names=["x"],
        binding=binding(),
        fit_runner=fit_runner,
        predict_runner=predict_runner,
    )
    assert [call[0] for call in calls] == ["fit", "fit", "fit", "predict", "predict", "predict"]
    assert result["evidence"]["status"] == "supported"
    assert result["evidence"]["ratio"] == pytest.approx(1.0)
    assert result["phase_order"] == ["fit_dev", "check_dev"]


def test_triplet_does_not_predict_a_failed_fit_and_returns_unknown():
    calls = []

    def fit_runner(source, request):
        calls.append(("fit", source))
        if source == "common":
            return {"status": "completed", "result": {"status": "failed"}}
        return {"status": "completed", "result": {
            "status": "success", "params": [1.0] * request["n_params"],
            "converged": True, "nfev": 1, "candidate_calls": 1,
        }}

    def predict_runner(source, request):
        calls.append(("predict", source))
        return {"status": "completed", "result": {
            "status": "success", "predictions": [1.0, 2.0],
        }}

    result = evaluate_triplet(
        structures=structures(),
        fit_data={"split_name": "fit_dev", "split_sha256": digest("f"),
                  "X": [[0.0], [1.0]], "y": [1.0, 2.0]},
        check_data={"split_name": "check_dev", "split_sha256": digest("a"),
                    "X": [[0.0], [1.0]], "y": [1.0, 2.0]},
        task_id="fixture", input_names=["x"], binding=binding(),
        fit_runner=fit_runner, predict_runner=predict_runner,
    )
    assert result["evidence"]["status"] == "unknown"
    assert result["evidence"]["decision_reason"] == "fit_failure"
    assert not any(kind == "predict" and source == "common" for kind, source in calls)


def test_triplet_rejects_split_binding_mismatch_before_execution():
    with pytest.raises(ValueError, match="check_data_sha256"):
        evaluate_triplet(
            structures=structures(),
            fit_data={"split_name": "fit_dev", "split_sha256": digest("f"),
                      "X": [[0.0]], "y": [1.0]},
            check_data={"split_name": "check_dev", "split_sha256": digest("9"),
                        "X": [[0.0]], "y": [1.0]},
            task_id="fixture", input_names=["x"], binding=binding(),
            fit_runner=lambda *_: pytest.fail("fit should not run"),
            predict_runner=lambda *_: pytest.fail("predict should not run"),
        )
