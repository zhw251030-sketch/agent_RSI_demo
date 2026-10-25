import hashlib

from analysis.replacement_evidence.dev_splits import build_split_manifest


def rows(n=30):
    return [
        {
            "b": str((i % 5) + 1),
            "s": str((i % 3) + 0.1),
            "temp": str((i % 5) / 6),
            "pH": str(4 + i % 8),
            "db": str((i * 7) % 19),
        }
        for i in range(n)
    ]


def test_bactgrow_split_is_exact_deterministic_and_disjoint():
    data = rows()
    manifest = build_split_manifest(
        task_id="bactgrow",
        headers=list(data[0]),
        rows=data,
        data_sha256=hashlib.sha256(b"fixture-bactgrow").hexdigest(),
    )
    assert manifest["split_counts"] == {"fit_dev": 18, "check_dev": 6, "outcome_dev": 6}
    split_rows = [set(manifest["splits"][name]["row_indices"]) for name in manifest["split_order"]]
    assert sum(map(len, split_rows)) == len(data)
    assert not (split_rows[0] & split_rows[1] or split_rows[0] & split_rows[2] or split_rows[1] & split_rows[2])
    assert manifest["splits"]["fit_dev"]["data_sha256"] != manifest["splits"]["check_dev"]["data_sha256"]
    repeat = build_split_manifest(
        task_id="bactgrow", headers=list(data[0]), rows=data,
        data_sha256=hashlib.sha256(b"fixture-bactgrow").hexdigest(),
    )
    assert manifest == repeat


def test_stressstrain_preserves_temperature_strata():
    data = [
        {"strain": str(i / 10), "temp": str(temp), "stress": str((i + j) % 11)}
        for j, temp in enumerate(("0.1", "0.5", "1.0"))
        for i in range(10)
    ]
    manifest = build_split_manifest(
        task_id="stressstrain", headers=["strain", "temp", "stress"], rows=data,
        data_sha256=hashlib.sha256(b"fixture-stressstrain").hexdigest(),
    )
    assert manifest["split_counts"] == {"fit_dev": 18, "check_dev": 6, "outcome_dev": 6}
    for split in manifest["split_order"]:
        indices = manifest["splits"][split]["row_indices"]
        temperatures = {data[index]["temp"] for index in indices}
        assert temperatures == {"0.1", "0.5", "1.0"}


def test_oscillator_split_uses_target_strata_without_temperature_column():
    data = [
        {"x": str(i / 10), "v": str((i % 7) / 7), "a": str((i * 3) % 13)}
        for i in range(30)
    ]
    manifest = build_split_manifest(
        task_id="oscillator1", headers=["x", "v", "a"], rows=data,
        data_sha256=hashlib.sha256(b"fixture-oscillator1").hexdigest(),
        version="replacement-cross-task-v0.1",
    )
    assert manifest["split_counts"] == {"fit_dev": 18, "check_dev": 6, "outcome_dev": 6}
    indices = [index for split in manifest["split_order"] for index in manifest["splits"][split]["row_indices"]]
    assert sorted(indices) == list(range(len(data)))


def test_manifest_rejects_wrong_task_schema_or_digest():
    data = rows()
    try:
        build_split_manifest(
            task_id="unknown", headers=list(data[0]), rows=data,
            data_sha256=hashlib.sha256(b"fixture").hexdigest(),
        )
    except ValueError as exc:
        assert "task" in str(exc)
    else:
        raise AssertionError("unknown task should be rejected")
