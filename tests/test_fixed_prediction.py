import pytest

from analysis.replacement_evidence.fixed_prediction import run_fixed_prediction


def test_fixed_prediction_strips_targets_and_scores_on_check_dev():
    observed = []

    def runner(source, request):
        observed.append((source, request))
        assert request["phase"] == "predict"
        assert "y" not in request
        return {
            "status": "completed",
            "result": {"status": "success", "predictions": [3.0, 5.0]},
        }

    result = run_fixed_prediction(
        source="def predict(X, params): return [3, 5]",
        params=[1.0, 2.0],
        X=[[1.0], [2.0]],
        y=[3.0, 5.0],
        task_id="bactgrow",
        input_names=["b"],
        split_name="check_dev",
        split_sha256="a" * 64,
        runner=runner,
    )
    assert result["status"] == "success"
    assert result["metrics"]["nmse"] == pytest.approx(0.0)
    assert result["request"]["target_present"] is False
    assert len(observed) == 1


def test_fixed_prediction_rejects_non_check_split_before_runner():
    with pytest.raises(ValueError, match="check_dev"):
        run_fixed_prediction(
            source="source",
            params=[1.0],
            X=[[1.0]],
            y=[1.0],
            task_id="bactgrow",
            input_names=["b"],
            split_name="fit_dev",
            split_sha256="a" * 64,
            runner=lambda *_: pytest.fail("runner should not be called"),
        )


def test_fixed_prediction_preserves_runner_failure_without_scoring():
    result = run_fixed_prediction(
        source="source",
        params=[1.0],
        X=[[1.0]],
        y=[1.0],
        task_id="bactgrow",
        input_names=["b"],
        split_name="check_dev",
        split_sha256="a" * 64,
        runner=lambda *_: {"status": "timeout"},
    )
    assert result["status"] == "prediction_failed"
    assert result["error"] == "runner_status:timeout"
