from analysis.replacement_evidence.external_task_config import EXTERNAL_TASK_DEFINITIONS
from analysis.replacement_evidence.round_runner import compile_basis


def test_srsd_external_tasks_are_within_existing_executable_contract():
    assert [task.task_id for task in EXTERNAL_TASK_DEFINITIONS] == [
        "srsd-feynman-i12-1", "srsd-feynman-i14-4", "srsd-feynman-ii8-31",
    ]
    for task in EXTERNAL_TASK_DEFINITIONS:
        assert len(task.headers) == len(task.input_names) + 1
        for parent in task.parents:
            compiled = compile_basis(task, parent.feature_ids)
            assert compiled["n_params"] == len(parent.feature_ids)
            assert compiled["source_sha256"]


def test_external_parent_sources_are_distinct():
    sources = [
        compile_basis(task, task.parents[0].feature_ids)["source_sha256"]
        for task in EXTERNAL_TASK_DEFINITIONS
    ]
    assert len(sources) == len(set(sources))
