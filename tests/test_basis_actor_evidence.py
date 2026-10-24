import copy
import unittest

from rsi_eval.basis_actor_evidence import bind_accepted_submission


PARENT = "a" * 64
CHILD = "b" * 64


class BasisActorEvidenceTests(unittest.TestCase):
    def accepted(self, feature_ids):
        return {
            "status": "accepted",
            "business": {"feature_ids": copy.deepcopy(feature_ids)},
            "execution_payload": {"feature_ids": copy.deepcopy(feature_ids),
                                   "explanation": "host-authored"},
        }

    def test_accepted_basis_submission_becomes_edit_record(self):
        result = bind_accepted_submission(
            self.accepted(["m_0_0", "m_0_1", "m_1_0", "m_2_0"]),
            task_id="oscillator1", parent_source_sha256=PARENT,
            candidate_source_sha256=CHILD,
            parent_feature_ids=["m_0_0", "m_0_1", "m_1_0", "m_1_1"],
            check_id="check-small-coefficient", check_status="contradicted",
            check_scope="development",
        )
        self.assertEqual(result["edit"]["removed_feature_ids"], ["m_1_1"])
        self.assertEqual(result["pre_edit_decision"]["decision"], "retain_parent")
        self.assertFalse(result["model_explanation_used"])

    def test_metrics_are_kept_as_posthoc_outcome(self):
        result = bind_accepted_submission(
            self.accepted(["m_0_0", "m_0_1", "m_1_0", "m_1_1"]),
            task_id="oscillator1", parent_source_sha256=PARENT,
            candidate_source_sha256=PARENT,
            parent_feature_ids=["m_0_0", "m_0_1", "m_1_0", "m_1_1"],
            check_id="check-unknown", check_status="unknown",
            check_scope="development", parent_metric=0.004,
            candidate_metric=0.096,
        )
        self.assertEqual(result["pre_edit_decision"]["decision"], "defer")
        self.assertEqual(result["posthoc_outcome"]["posthoc_status"], "contradicted")

    def test_changed_execution_ids_are_rejected(self):
        accepted = self.accepted(["m_0_0", "m_0_1", "m_1_0", "m_2_0"])
        accepted["execution_payload"]["feature_ids"][-1] = "m_1_2"
        with self.assertRaises(ValueError):
            bind_accepted_submission(
                accepted, task_id="oscillator1", parent_source_sha256=PARENT,
                candidate_source_sha256=CHILD,
                parent_feature_ids=["m_0_0", "m_0_1", "m_1_0", "m_1_1"],
                check_id="check", check_status="unknown", check_scope="development",
            )
