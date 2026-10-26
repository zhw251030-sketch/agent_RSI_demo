from scripts.run_shift_aware_v03_contract import build_contract_cases


def test_contract_matrix_contains_all_deployment_boundaries():
    cases = build_contract_cases()
    by_name = {case["name"]: case for case in cases}
    assert set(by_name) == {
        "supported_covered",
        "supported_shifted_pass",
        "supported_shifted_fail",
        "supported_shifted_unavailable",
        "contradicted_covered",
        "contradicted_shifted",
        "unknown_shifted",
    }
    assert by_name["supported_covered"]["final_action"] == "execute_candidate"
    assert by_name["supported_shifted_pass"]["final_action"] == "execute_candidate"
    assert by_name["supported_shifted_fail"]["final_action"] == "retain_parent"
    assert by_name["supported_shifted_unavailable"]["decision"] == "defer"
    assert by_name["contradicted_shifted"]["final_action"] == "retain_parent"


def test_contract_cases_are_deterministic():
    assert build_contract_cases() == build_contract_cases()
