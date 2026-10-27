from analysis.replacement_evidence.external_replication_task_config import REPLICATION_TASK_DEFINITIONS


def test_replication_tasks_fit_existing_v01_contract():
    assert [task.task_id for task in REPLICATION_TASK_DEFINITIONS] == [
        "srsd-feynman-i12-5", "srsd-feynman-i14-3"
    ]
    assert all(len(task.input_names) <= 4 for task in REPLICATION_TASK_DEFINITIONS)
    assert all(len(parent.feature_ids) == 4 if len(task.input_names) == 2 else len(parent.feature_ids) == 3
               for task in REPLICATION_TASK_DEFINITIONS for parent in task.parents)
