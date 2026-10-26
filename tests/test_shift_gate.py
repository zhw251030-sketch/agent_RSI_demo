import pytest

from analysis.replacement_evidence.shift_gate import build_profile, score_batch


def test_profile_is_deterministic_and_uses_only_input_rows():
    profile = build_profile([[0.0, 1.0], [1.0, 2.0], [2.0, 3.0]], ["x", "v"])
    assert profile["schema"] == "replacement-shift-profile-v0.1"
    assert profile["n_rows"] == 3
    assert profile["profile_sha256"] == build_profile(
        [[0.0, 1.0], [1.0, 2.0], [2.0, 3.0]], ["x", "v"]
    )["profile_sha256"]


def test_in_domain_batch_is_covered():
    profile = build_profile([[0.0], [1.0], [2.0], [3.0], [4.0]], ["x"])
    result = score_batch(profile, [[1.0], [2.0], [3.0]])
    assert result["status"] == "covered"
    assert result["shifted_features"] == []


def test_out_of_domain_batch_is_shifted():
    profile = build_profile([[0.0], [1.0], [2.0], [3.0], [4.0]], ["x"])
    result = score_batch(profile, [[10.0], [11.0], [12.0]])
    assert result["status"] == "shifted"
    assert result["shifted_features"] == ["x"]
    assert "outside_rate" in result["per_feature"]["x"]["reasons"]


def test_constant_reference_feature_does_not_divide_by_zero():
    profile = build_profile([[1.0], [1.0], [1.0]], ["x"])
    result = score_batch(profile, [[1.0], [1.0], [1.0]])
    assert result["status"] == "covered"
    assert result["per_feature"]["x"]["variance_ratio"] == 1.0


@pytest.mark.parametrize(
    "rows,names",
    [([[1.0, 2.0]], ["x"]), ([[float("nan")]], ["x"]), ([[1.0]], ["x", "x"])],
)
def test_invalid_profile_inputs_are_rejected(rows, names):
    with pytest.raises(ValueError):
        build_profile(rows, names)


def test_profile_schema_and_row_width_are_checked():
    profile = build_profile([[0.0], [1.0]], ["x"])
    with pytest.raises(ValueError, match="schema"):
        score_batch({**profile, "schema": "other"}, [[0.0]])
    with pytest.raises(ValueError, match="width"):
        score_batch(profile, [[0.0, 1.0]])

