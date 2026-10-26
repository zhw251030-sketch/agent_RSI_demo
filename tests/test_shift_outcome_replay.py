from scripts.run_shift_aware_v03_replay import summarize_proxy_rows


def test_summary_distinguishes_new_shift_block_and_existing_evidence_block():
    rows = [
        {"v02_action": "execute_candidate", "v03_action": "retain_parent", "proxy_harmful": True, "action_changed": True},
        {"v02_action": "retain_parent", "v03_action": "retain_parent", "proxy_harmful": True, "action_changed": False},
        {"v02_action": "execute_candidate", "v03_action": "execute_candidate", "proxy_harmful": False, "action_changed": False},
    ]
    result = summarize_proxy_rows(rows)
    assert result["proposal_count"] == 3
    assert result["proxy_harmful"] == 2
    assert result["v02_deployed_proxy_harmful"] == 1
    assert result["v03_deployed_proxy_harmful"] == 0
    assert result["v03_new_shift_prevented_proxy_harm"] == 1
    assert result["already_retained_proxy_harm"] == 1


def test_summary_counts_validation_outcomes():
    rows = [
        {"decision": "allow_after_validation"},
        {"decision": "retain"},
        {"decision": "defer"},
        {"decision": "allow"},
    ]
    result = summarize_proxy_rows(rows)
    assert result["decision_counts"] == {
        "allow": 1,
        "allow_after_validation": 1,
        "defer": 1,
        "retain": 1,
    }
