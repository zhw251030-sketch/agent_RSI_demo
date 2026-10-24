import hashlib
import unittest

from rsi_eval.edit_evidence import (
    build_edit, classify_observed_outcome, decide_from_check, attach_check,
)


PARENT = "a" * 64
CHILD = "b" * 64


class EditEvidenceTests(unittest.TestCase):
    def edit(self):
        return build_edit(
            task_id="oscillator1", parent_source_sha256=PARENT,
            candidate_source_sha256=CHILD,
            parent_feature_ids=["m_0_0", "m_0_1", "m_1_0", "m_1_1"],
            candidate_feature_ids=["m_0_0", "m_0_1", "m_1_0", "m_2_0"],
        )

    def test_build_binds_one_swap_and_canonical_edit_id(self):
        edit = self.edit()
        self.assertEqual(edit["mode"], "swap_one")
        self.assertEqual(edit["removed_feature_ids"], ["m_1_1"])
        self.assertEqual(edit["added_feature_ids"], ["m_2_0"])
        expected = hashlib.sha256(edit["canonical"].encode("utf-8")).hexdigest()
        self.assertEqual(edit["edit_id"], "edit_" + expected[:16])

    def test_keep_is_an_explicit_edit_without_fake_added_or_removed_terms(self):
        edit = build_edit(
            task_id="oscillator1", parent_source_sha256=PARENT,
            candidate_source_sha256=PARENT,
            parent_feature_ids=["m_0_0", "m_0_1"],
            candidate_feature_ids=["m_0_0", "m_0_1"],
        )
        self.assertEqual(edit["mode"], "keep")
        self.assertEqual(edit["added_feature_ids"], [])
        self.assertEqual(edit["removed_feature_ids"], [])

    def test_invalid_multi_edit_and_duplicate_features_are_rejected(self):
        with self.assertRaises(ValueError):
            build_edit(task_id="t", parent_source_sha256=PARENT,
                       candidate_source_sha256=CHILD,
                       parent_feature_ids=["a", "b"], candidate_feature_ids=["c", "d"])
        with self.assertRaises(ValueError):
            build_edit(task_id="t", parent_source_sha256=PARENT,
                       candidate_source_sha256=CHILD,
                       parent_feature_ids=["a", "a"], candidate_feature_ids=["a", "b"])

    def test_check_status_maps_to_a_provisional_decision(self):
        edit = self.edit()
        for status, decision in [("supported", "allow_candidate"),
                                 ("contradicted", "retain_parent"),
                                 ("unknown", "defer")]:
            checked = attach_check(edit, check_id="check-1", status=status,
                                   scope="development")
            self.assertEqual(decide_from_check(checked)["decision"], decision)

    def test_check_is_bound_to_edit_and_sealed_evidence_is_not_allowed(self):
        edit = self.edit()
        checked = attach_check(edit, check_id="check-1", status="unknown",
                               scope="development")
        self.assertEqual(checked["edit_id"], edit["edit_id"])
        with self.assertRaises(ValueError):
            attach_check(edit, check_id="check-1", status="supported", scope="sealed")

    def test_observed_outcome_is_separate_from_pre_edit_decision(self):
        edit = self.edit()
        checked = attach_check(edit, check_id="check-1", status="unknown",
                               scope="development")
        record = classify_observed_outcome(checked, parent_metric=0.004,
                                           candidate_metric=0.096, direction="decrease",
                                           tolerance=1e-5)
        self.assertEqual(record["pre_edit_decision"], "defer")
        self.assertEqual(record["posthoc_status"], "contradicted")
        self.assertAlmostEqual(record["delta"], -0.092)


if __name__ == "__main__":
    unittest.main()
