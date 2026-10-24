import unittest

from rsi_eval.edit_evidence import build_edit
from rsi_eval.evidence_checks import VERSION, check_claim
from rsi_eval.evidence_ids import EvidenceRegistry
from rsi_eval.targeted_edit_check import evaluate_targeted_claim


PARENT = "a" * 64
CHILD = "b" * 64


def make_registry(value=0.495):
    binding = {
        "session_id": "calibration",
        "candidate_id": "parent-000",
        "candidate_sha256": PARENT,
        "task_id": "oscillator1",
        "version": VERSION,
        "scope": "development",
    }
    return EvidenceRegistry([{
        "binding": binding,
        "scalars": {"coefficient:m_1_1": value},
        "facts": {},
    }], session_id="calibration")


class TargetedEditCheckTests(unittest.TestCase):
    def edit(self):
        return build_edit(
            task_id="oscillator1", parent_source_sha256=PARENT,
            candidate_source_sha256=CHILD,
            parent_feature_ids=["m_0_0", "m_0_1", "m_1_0", "m_1_1"],
            candidate_feature_ids=["m_0_0", "m_0_1", "m_1_0", "m_2_0"],
        )

    def claim(self, registry, op="lt", value=0.1):
        identifier = next(item["evidence_id"] for item in registry.entries()
                          if item["key"] == "coefficient:m_1_1")
        return {"evidence_id": identifier, "op": op, "value": value}

    def test_supported_claim_allows_candidate(self):
        registry = make_registry(value=0.01)
        result = evaluate_targeted_claim(
            self.edit(), registry, self.claim(registry), check_id="check-1")
        self.assertEqual(result["raw_result"]["status"], "supported")
        self.assertEqual(result["decision"]["decision"], "allow_candidate")

    def test_contradicted_claim_retains_parent(self):
        registry = make_registry(value=0.495)
        result = evaluate_targeted_claim(
            self.edit(), registry, self.claim(registry), check_id="check-2")
        self.assertEqual(result["raw_result"]["status"], "contradicted")
        self.assertEqual(result["decision"]["decision"], "retain_parent")

    def test_unavailable_claim_is_explicitly_deferred(self):
        registry = make_registry()
        claim = self.claim(registry)
        claim["evidence_id"] = "e_0000000000000000"
        result = evaluate_targeted_claim(
            self.edit(), registry, claim, check_id="check-3")
        self.assertEqual(result["raw_result"]["status"], "unavailable")
        self.assertEqual(result["checked_edit"]["check_status"], "unknown")
        self.assertEqual(result["decision"]["decision"], "defer")

    def test_raw_checker_schema_remains_bounded(self):
        self.assertEqual(check_claim({}, [])["status"], "schema_invalid")
