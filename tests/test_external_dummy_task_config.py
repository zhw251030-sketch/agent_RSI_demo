from analysis.replacement_evidence.external_dummy_task_config import DUMMY_TASK_DEFINITIONS
from analysis.replacement_evidence.round_runner import compile_basis


def test_dummy_tasks_bind_distractor_inputs_inside_current_contract():
    assert [task.task_id for task in DUMMY_TASK_DEFINITIONS] == [
        "srsd-feynman-i12-1-dummy", "srsd-feynman-ii8-31-dummy",
    ]
    for task in DUMMY_TASK_DEFINITIONS:
        assert len(task.input_names) == 3
        assert len(task.headers) == 4
        compiled = compile_basis(task, task.parents[0].feature_ids)
        assert compiled["n_params"] == len(task.parents[0].feature_ids)
