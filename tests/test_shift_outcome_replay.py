from pathlib import Path

from scripts.run_shift_aware_v03_replay import _repo_relative, summarize_proxy_rows


def test_repo_relative_resolves_relative_paths_against_project_root():
    assert _repo_relative(Path("runs/example/round-summary.json")) == "runs/example/round-summary.json"


def test_summary_distinguishes_new_shift_block_and_existing_evidence_block():
    rows = [
        {"old_action": "execute_candidate", "v02_shift_action": "retain_parent", "v03_action": "retain_parent", "proxy_harmful": True, "changed_from_v02": False},
        {"old_action": "retain_parent", "v02_shift_action": "retain_parent", "v03_action": "retain_parent", "proxy_harmful": True, "changed_from_v02": False},
        {"old_action": "execute_candidate", "v02_shift_action": "retain_parent", "v03_action": "execute_candidate", "proxy_harmful": False, "changed_from_v02": True},
    ]
    result = summarize_proxy_rows(rows)
    assert result["proposal_count"] == 3
    assert result["proxy_harmful"] == 2
    assert result["old_deployed_proxy_harmful"] == 1
    assert result["v02_shift_deployed_proxy_harmful"] == 0
    assert result["v03_deployed_proxy_harmful"] == 0
    assert result["v03_new_prevented_vs_old"] == 1
    assert result["v02_prevented_vs_old"] == 1
    assert result["v03_new_prevented_vs_v02"] == 0
    assert result["v03_action_changes_from_v02"] == 1


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
