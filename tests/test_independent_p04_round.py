from scripts.run_natural_domain_v04_p04_round import build_fake_responses
from analysis.replacement_evidence.independent_round_config import P04_TASK_DEFINITIONS


def test_fake_plan_has_two_one_shot_submissions_per_p04_parent():
    responses = build_fake_responses(P04_TASK_DEFINITIONS)
    assert len(responses) == 8
    assert all(item["tool"] == "submit_basis" for item in responses)
    for index, task in enumerate(P04_TASK_DEFINITIONS):
        parent_ids = list(task.parents[0].feature_ids)
        first = responses[index * 2]["arguments"]["feature_ids"]
        second = responses[index * 2 + 1]["arguments"]["feature_ids"]
        assert first == parent_ids
        assert len(second) == len(parent_ids)
        assert second != parent_ids
