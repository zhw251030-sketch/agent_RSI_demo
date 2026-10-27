import hashlib

import pytest

from scripts.verify_srsd_i144_v02_closure import ClosureError, _check_hash, validate_metadata


def _reports():
    return {
        "certificate": {
            "schema": "replacement-srsd-feynman-dummy-i144-v02-v05-verification",
            "status": "passed",
            "mode": "fake",
            "official_test_read": False,
            "official_test_ood_read": False,
            "model_requests": 2,
            "accepted_slots": 2,
            "gate_records": 6,
            "real_model_calls": 0,
        },
        "round": {
            "schema": "replacement-agent-round-runner-v0.1",
            "status": "passed",
            "official_test_read": False,
            "official_test_ood_read": False,
            "model_requests": 2,
            "accepted_slots": 2,
            "gate_records": 6,
        },
        "val": {
            "schema": "replacement-srsd-feynman-dummy-i144-v02-val-replay-v05",
            "status": "passed",
            "official_test_read": False,
            "official_test_ood_read": False,
            "rows": [{"dual_gate_action": "retain_parent"}, {"dual_gate_action": "retain_parent"}],
        },
        "holdout": {
            "schema": "replacement-srsd-feynman-dummy-i144-v02-test-holdout-v05",
            "status": "passed_descriptive_holdout",
            "official_test_read": True,
            "official_test_ood_read": False,
            "one_time_read": True,
            "rules_frozen_before_read": True,
            "rows": [{"deployed_harmful": False}, {"deployed_harmful": False}],
        },
    }


def test_validate_metadata_accepts_frozen_boundary():
    validate_metadata(_reports())


def test_validate_metadata_rejects_test_access_before_holdout():
    reports = _reports()
    reports["val"]["official_test_read"] = True
    with pytest.raises(ClosureError, match="val report must not read official test"):
        validate_metadata(reports)


def test_validate_metadata_rejects_extra_allow_action():
    reports = _reports()
    reports["val"]["rows"] = [
        {"dual_gate_action": "allow_after_val_dual_validation"},
        {"dual_gate_action": "allow_after_val_dual_validation"},
    ]
    with pytest.raises(ClosureError, match="at most one frozen val allow"):
        validate_metadata(reports)


def test_hash_check_rejects_tampered_artifact(tmp_path):
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{\"status\":\"passed\"}\n", encoding="utf-8")
    report = {"artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}
    _check_hash(report, "artifact_sha256", artifact, "artifact")
    artifact.write_text("{\"status\":\"tampered\"}\n", encoding="utf-8")
    with pytest.raises(ClosureError, match="artifact hash mismatch"):
        _check_hash(report, "artifact_sha256", artifact, "artifact")
