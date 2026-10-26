import pytest

from analysis.replacement_evidence.independent_round_config import (
    P04_TASK_DEFINITIONS,
    assert_source_novelty,
    historical_source_hashes,
    assert_records_novelty,
    slot_ids,
)


def test_p04_batch_freezes_one_new_parent_per_task_and_two_repeats():
    assert [task.task_id for task in P04_TASK_DEFINITIONS] == [
        "bactgrow", "stressstrain", "oscillator1", "oscillator2",
    ]
    assert [task.parents[0].parent_id for task in P04_TASK_DEFINITIONS] == [
        "bactgrow-p04", "stressstrain-p04", "oscillator1-p04", "oscillator2-p04",
    ]
    assert len(slot_ids()) == 8
    assert len(set(slot_ids())) == 8


def test_source_novelty_guard_accepts_new_hashes():
    assert_source_novelty(
        proposed_parent_hashes={"parent-new"},
        proposed_candidate_hashes={"candidate-new"},
        historical_hashes={"old-parent", "old-candidate"},
    )


@pytest.mark.parametrize("proposed", [{"old-parent"}, {"old-candidate"}])
def test_source_novelty_guard_rejects_any_historical_collision(proposed):
    with pytest.raises(ValueError, match="source collision"):
        assert_source_novelty(
            proposed_parent_hashes=proposed,
            proposed_candidate_hashes=set(),
            historical_hashes={"old-parent", "old-candidate"},
        )


def test_source_novelty_guard_rejects_parent_candidate_collision():
    with pytest.raises(ValueError, match="parent/candidate"):
        assert_source_novelty(
            proposed_parent_hashes={"same"},
            proposed_candidate_hashes={"same"},
            historical_hashes=set(),
        )


def test_historical_source_hashes_are_scoped_by_task():
    summary = {"records": [
        {"task_id": "stressstrain", "parent_source_sha256": "same", "candidate_source_sha256": "same"},
        {"task_id": "oscillator1", "parent_source_sha256": "same", "candidate_source_sha256": "same"},
    ]}
    assert historical_source_hashes(summary) == {
        "stressstrain": {"same"}, "oscillator1": {"same"},
    }


def test_records_novelty_guard_allows_same_hash_for_different_tasks():
    records = [
        {"task_id": "stressstrain", "edit_mode": "swap_one", "parent_source_sha256": "new", "candidate_source_sha256": "new-c"},
        {"task_id": "oscillator1", "edit_mode": "swap_one", "parent_source_sha256": "new", "candidate_source_sha256": "new-c"},
    ]
    assert_records_novelty(records, {"stressstrain": {"old"}, "oscillator1": {"old"}})
