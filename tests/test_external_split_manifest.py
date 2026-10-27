import hashlib

import pytest

from analysis.replacement_evidence.dev_splits import (
    build_generic_split_manifest,
    build_split_manifest,
)


def _rows(n=20):
    return [{"x0": str(i + 1), "x1": str((i % 5) + 1), "y": str((i + 1) * ((i % 5) + 1))}
            for i in range(n)]


def test_generic_manifest_is_disjoint_and_self_bound():
    rows = _rows()
    digest = hashlib.sha256(b"external-train").hexdigest()
    manifest = build_generic_split_manifest(
        task_id="srsd-feynman-i12-1",
        headers=("x0", "x1", "y"),
        rows=rows,
        data_sha256=digest,
        target="y",
    )
    assert manifest["source"]["official_test_read"] is False
    assert manifest["split_counts"] == {"fit_dev": 12, "check_dev": 4, "outcome_dev": 4}
    indices = [i for split in manifest["splits"].values() for i in split["row_indices"]]
    assert sorted(indices) == list(range(len(rows)))
    assert len(indices) == len(set(indices))
    assert len(manifest["manifest_sha256"]) == 64


def test_generic_manifest_rejects_unknown_target_or_malformed_rows():
    with pytest.raises(ValueError, match="target"):
        build_generic_split_manifest(
            task_id="external", headers=("x0", "y"), rows=[{"x0": 1, "y": 2}],
            data_sha256="0" * 64, target="missing",
        )
    with pytest.raises(ValueError, match="keys"):
        build_generic_split_manifest(
            task_id="external", headers=("x0", "y"), rows=[{"x0": 1, "z": 2}],
            data_sha256="0" * 64, target="y",
        )


def test_legacy_wrapper_remains_compatible():
    rows = [{"strain": i, "temp": 20, "stress": i * 2} for i in range(20)]
    manifest = build_split_manifest(
        task_id="stressstrain", headers=("strain", "temp", "stress"), rows=rows,
        data_sha256="1" * 64,
    )
    assert manifest["task_id"] == "stressstrain"
    assert manifest["allocation"]["stratification"] == ["temp", "target_decile"]
