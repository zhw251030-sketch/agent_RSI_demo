import unittest

from rsi_eval.edit_condition_gate import apply_gate
from rsi_eval.edit_evidence import build_edit


PARENT = "a" * 64
CHILD = "b" * 64


class EditConditionGateTests(unittest.TestCase):
    def edit(self):
        return build_edit(
            task_id="oscillator1", parent_source_sha256=PARENT,
            candidate_source_sha256=CHILD,
            parent_feature_ids=["m_0_0", "m_0_1", "m_1_0", "m_1_1"],
            candidate_feature_ids=["m_0_0", "m_0_1", "m_1_0", "m_2_0"],
        )

    def test_controls_share_the_same_execution_gate(self):
        no_check = apply_gate(self.edit(), condition="no_check", check_id="nc")
        sham = apply_gate(self.edit(), condition="sham_check", check_id="sham")
        self.assertEqual(no_check["final_action"], "execute_candidate")
        self.assertEqual(sham["final_action"], "execute_candidate")
        self.assertEqual(no_check["common_gate"], sham["common_gate"])
        self.assertEqual(no_check["check_reason"], "control_bypass")
        self.assertEqual(sham["check_reason"], "uninformative_sham")

    def test_real_contradiction_retains_parent(self):
        result = apply_gate(self.edit(), condition="real_check", check_id="real",
                            real_status="contradicted")
        self.assertEqual(result["decision"]["decision"], "retain_parent")
        self.assertEqual(result["final_action"], "retain_parent")
        self.assertEqual(result["common_gate"], "execute_only_when_supported")

    def test_real_unknown_does_not_execute(self):
        result = apply_gate(self.edit(), condition="real_check", check_id="real",
                            real_status="unknown")
        self.assertEqual(result["final_action"], "retain_parent")

    def test_real_status_cannot_be_omitted(self):
        with self.assertRaises(ValueError):
            apply_gate(self.edit(), condition="real_check", check_id="real")

    def test_keep_is_not_a_check_success_or_candidate_execution(self):
        edit = build_edit(
            task_id="oscillator1", parent_source_sha256=PARENT,
            candidate_source_sha256=PARENT,
            parent_feature_ids=["m_0_0", "m_0_1"],
            candidate_feature_ids=["m_0_0", "m_0_1"],
        )
        result = apply_gate(edit, condition="real_check", check_id="keep")
        self.assertEqual(result["check_applicability"], "not_applicable")
        self.assertEqual(result["final_action"], "retain_parent")
        self.assertEqual(result["decision"]["decision"], "defer")


if __name__ == "__main__":
    unittest.main()
