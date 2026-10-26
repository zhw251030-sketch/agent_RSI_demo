import pytest

from scripts.audit_p04_round import audit_p04_records


def _round_records():
    return [
        {"slot_id": "task-p04-r1", "task_id": "task", "edit_mode": "swap_one",
         "evidence": {"status": "supported"}},
        {"slot_id": "task-p04-r2", "task_id": "task", "edit_mode": "keep",
         "evidence": {"status": "unknown"}},
    ]


def _v03_rows():
    return [
        {"proposal_id": "task-p04-r1", "evidence_status": "supported", "v03_action": "execute_candidate"},
        {"proposal_id": "task-p04-r2", "evidence_status": "unknown", "v03_action": "retain_parent"},
    ]


def _v04_rows():
    return [
        {"proposal_id": "task-p04-r1", "task_id": "task", "edit_mode": "swap_one",
         "evidence_status": "supported", "v04_action": "retain_parent",
         "decision": {"decision": "retain", "final_action": "retain_parent"}},
        {"proposal_id": "task-p04-r2", "task_id": "task", "edit_mode": "keep",
         "evidence_status": "unknown", "v04_action": "retain_parent",
         "decision": {"decision": "retain", "final_action": "retain_parent", "reason": "no_candidate_edit"}},
    ]


def test_p04_audit_accepts_matching_three_layer_ledgers():
    result = audit_p04_records(
        round_records=_round_records(),
        v03_rows=_v03_rows(),
        v04_rows=_v04_rows(),
        official_test_read=False,
        official_test_ood_read=False,
    )
    assert result["status"] == "passed"
    assert result["checks_passed"] == 5


def test_p04_audit_rejects_missing_replay_proposal():
    with pytest.raises(ValueError, match="proposal IDs"):
        audit_p04_records(
            round_records=_round_records(),
            v03_rows=_v03_rows()[:-1],
            v04_rows=_v04_rows(),
            official_test_read=False,
            official_test_ood_read=False,
        )


def test_p04_audit_rejects_holdout_access_flag():
    with pytest.raises(ValueError, match="official holdout"):
        audit_p04_records(
            round_records=_round_records(),
            v03_rows=_v03_rows(),
            v04_rows=_v04_rows(),
            official_test_read=True,
            official_test_ood_read=False,
        )
