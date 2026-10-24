import json
import shutil
from pathlib import Path

import pytest

from analysis.basis_trial_v02.diagnose import diagnose_archive, verify_source_hash


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "artifacts/basis-trial-v02/2026-10-22/measured-v01/raw"


def test_a_records_preserve_all_repetitions_and_outcomes():
    report = diagnose_archive(ARCHIVE)

    assert len(report["records"]) == 6
    assert report["summary"] == {
        "records": 6,
        "modifications": 5,
        "kept": 1,
        "degraded_modifications": 5,
        "pre_edit_supported": 0,
        "pre_edit_contradicted": 0,
        "pre_edit_unknown": 6,
    }
    assert [r["slot_id"] for r in report["records"]] == [
        "A-r1-S0", "A-r1-S1", "A-r2-S0", "A-r2-S1", "A-r3-S0", "A-r3-S1"
    ]
    assert all(r["pre_edit_evidence_status"] == "unknown" for r in report["records"])
    assert all(
        r["posthoc_result_status"] == "contradicted"
        for r in report["records"]
        if r["edit_type"] == "swap_one"
    )


def test_policy_counts_and_parent_child_bindings_are_verified():
    report = diagnose_archive(ARCHIVE)
    by_policy = {policy: [] for policy in ("S0", "S1")}
    for record in report["records"]:
        by_policy[record["policy"]].append(record)

    assert sum(r["edit_type"] == "swap_one" for r in by_policy["S0"]) == 3
    assert sum(r["edit_type"] == "swap_one" for r in by_policy["S1"]) == 2
    assert sum(r["edit_type"] == "keep" for r in by_policy["S1"]) == 1
    assert all(r["source_hash_verified"] for r in report["records"])
    assert all(r["transition_verified"] for r in report["records"])


def test_tampered_source_hash_is_rejected(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("return 1\n", encoding="utf-8")
    expected = verify_source_hash(source)
    source.write_text("return 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source hash mismatch"):
        verify_source_hash(source, expected)


def test_missing_row_fields_are_rejected(tmp_path):
    copied = tmp_path / "raw"
    shutil.copytree(ARCHIVE, copied)
    row_path = copied / "experiment/row-A-r1-S0.json"
    row = json.loads(row_path.read_text(encoding="utf-8"))
    del row["transition"]
    row_path.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="missing transition"):
        diagnose_archive(copied)
