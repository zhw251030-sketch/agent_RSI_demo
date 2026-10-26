from scripts.run_shift_aware_v03_fake_round import summarize_fake_round


def test_fake_round_summary_binds_sdk_round_to_v03_replay():
    fake_summary = {
        "model_requests": 8,
        "accepted_slots": 8,
        "gate_records": 24,
        "official_test_read": False,
        "official_test_ood_read": False,
        "real_model_calls": 0,
        "provider_calls": 8,
        "budget": {"actual_tokens": 960},
    }
    v03_summary = {
        "proposal_count": 8,
        "model_requests": 0,
        "official_test_read": False,
        "official_test_ood_read": False,
        "v03_deployed_proxy_harmful": 0,
    }
    result = summarize_fake_round(fake_summary, v03_summary)
    assert result["status"] == "passed_shift_aware_v03_fake_round"
    assert result["provider_calls"] == 8
    assert result["real_model_calls"] == 0
    assert result["v03_model_requests"] == 0
    assert result["proposal_count"] == 8


def test_fake_round_rejects_holdout_flags():
    fake_summary = {
        "official_test_read": True,
        "official_test_ood_read": False,
    }
    v03_summary = {
        "official_test_read": False,
        "official_test_ood_read": False,
    }
    try:
        summarize_fake_round(fake_summary, v03_summary)
    except ValueError as exc:
        assert "official holdout" in str(exc)
    else:
        raise AssertionError("holdout flags must be rejected")
