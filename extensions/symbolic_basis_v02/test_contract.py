import pytest

from extensions.symbolic_basis_v02.contract import compile_submission, make_spec


def test_five_input_catalog_has_56_terms_and_accepts_k16():
    spec = make_spec(5, 16)
    assert spec["schema_version"] == "symbolic-basis-v0.2"
    assert len(spec["feature_ids"]) == 56
    compiled = compile_submission(
        {"feature_ids": ["m_0_0_0_0_0", "m_1_0_0_0_0", "m_0_1_0_0_0",
                          "m_0_0_1_0_0", "m_0_0_0_1_0", "m_0_0_0_0_1",
                          "m_1_1_0_0_0", "m_1_0_1_0_0", "m_1_0_0_1_0",
                          "m_1_0_0_0_1", "m_0_1_1_0_0", "m_0_1_0_1_0",
                          "m_0_1_0_0_1", "m_0_0_1_1_0", "m_0_0_1_0_1",
                          "m_0_0_0_1_1"], "explanation": "test"}, spec)
    assert compiled["n_params"] == 16
    assert "x4" in compiled["source"]


def test_v02_rejects_four_input_spec_schema_or_out_of_range_dimensions():
    with pytest.raises(ValueError):
        make_spec(0, 1)
    with pytest.raises(ValueError):
        make_spec(6, 1)
    with pytest.raises(ValueError):
        make_spec(5, 17)
