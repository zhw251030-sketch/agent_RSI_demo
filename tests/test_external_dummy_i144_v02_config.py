from analysis.replacement_evidence.external_dummy_i144_v02_task_config import DUMMY_I144_V02_TASK_DEFINITIONS


def test_i144_dummy_v02_has_five_inputs_and_six_term_parent():
    task = DUMMY_I144_V02_TASK_DEFINITIONS[0]
    assert len(task.input_names) == 5
    assert task.headers == (*task.input_names, "y")
    assert len(task.parents[0].feature_ids) == 6
    assert task.parents[0].feature_ids[0] == "m_0_0_0_0_0"
