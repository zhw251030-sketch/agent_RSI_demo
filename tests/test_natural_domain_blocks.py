from scripts.build_natural_domain_v04 import (
    assign_region, build_feature_rule, build_feature_blocks,
)


def test_low_cardinality_feature_uses_exact_levels():
    rule = build_feature_rule([0.2, 0.4, 0.2], max_exact_levels=16)
    assert rule["kind"] == "exact_level"
    assert rule["levels"] == [0.2, 0.4]
    assert assign_region(0.4, rule) == "level:0.4"
    assert assign_region(0.7, rule) == "unseen"


def test_continuous_feature_uses_five_fixed_quantile_bins():
    rule = build_feature_rule(list(range(100)), max_exact_levels=16)
    assert rule["kind"] == "quantile_bins"
    assert len(rule["edges"]) == 4
    assert assign_region(-1.0, rule) == "bin:0"
    assert assign_region(101.0, rule) == "bin:4"


def test_blocks_are_deterministic_and_drop_sparse_regions():
    headers = ["temp", "stress"]
    rows = [
        {"temp": str(index % 2), "stress": str(index)}
        for index in range(10)
    ]
    result = build_feature_blocks(
        task_id="stressstrain", headers=headers, rows=rows,
        fit_indices=list(range(10)), outcome_indices=list(range(10)),
        source_data_sha256="a" * 64, min_rows=6,
    )
    assert result == build_feature_blocks(
        task_id="stressstrain", headers=headers, rows=rows,
        fit_indices=list(range(10)), outcome_indices=list(range(10)),
        source_data_sha256="a" * 64, min_rows=6,
    )
    assert result["blocks"]
    assert all(block["valid"] == (block["n_rows"] >= 6) for block in result["blocks"])
    assert any(not block["valid"] for block in result["blocks"])
    assert result["ordinary"]["n_rows"] == 10
    assert result["not_benchmark"] is True
