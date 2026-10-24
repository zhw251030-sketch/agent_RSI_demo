import unittest

from analysis.basis_edit_comparison.shadow_outcome import (
    attach_shadow_outcomes, freeze_gate_decisions,
)


def gates():
    rows = []
    for proposal_id, action in [("P01-r1", "retain_parent"), ("P01-r2", "execute_candidate")]:
        for condition in ("no_check", "sham_check", "real_check"):
            rows.append({"proposal_id": proposal_id, "condition": condition,
                         "final_action": action if condition == "real_check" else "execute_candidate"})
    return rows


class BasisEditShadowTests(unittest.TestCase):
    def test_outcomes_are_attached_after_gate_freeze(self):
        frozen = freeze_gate_decisions(gates())
        result = attach_shadow_outcomes(frozen, {
            "P01-r1": {"parent_nmse": 0.1, "candidate_nmse": 0.1, "edit_mode": "keep"},
            "P01-r2": {"parent_nmse": 0.1, "candidate_nmse": 0.2, "edit_mode": "swap_one"},
        })
        self.assertEqual(result["summary"]["no_check"]["deployed_harmful"], 1)
        self.assertEqual(result["summary"]["real_check"]["deployed_harmful"], 1)
        self.assertEqual(result["summary"]["real_check"]["prevented_harm"], 0)

    def test_real_retention_counts_prevented_harm_without_rewriting_gate(self):
        rows = gates()
        for row in rows:
            if row["proposal_id"] == "P01-r2" and row["condition"] == "real_check":
                row["final_action"] = "retain_parent"
        frozen = freeze_gate_decisions(rows)
        result = attach_shadow_outcomes(frozen, {
            "P01-r1": {"parent_nmse": 0.1, "candidate_nmse": 0.1, "edit_mode": "keep"},
            "P01-r2": {"parent_nmse": 0.1, "candidate_nmse": 0.2, "edit_mode": "swap_one"},
        })
        self.assertEqual(result["summary"]["real_check"]["deployed_harmful"], 0)
        self.assertEqual(result["summary"]["real_check"]["prevented_harm"], 1)
        self.assertEqual(result["metrics"][-1]["final_action"], "retain_parent")

    def test_missing_condition_or_tampered_freeze_is_rejected(self):
        rows = gates()[:-1]
        with self.assertRaises(ValueError):
            freeze_gate_decisions(rows)
        frozen = freeze_gate_decisions(gates())
        frozen["frozen"]["rows"][0]["final_action"] = "retain_parent"
        with self.assertRaises(ValueError):
            attach_shadow_outcomes(frozen, {
                "P01-r1": {"parent_nmse": 0.1, "candidate_nmse": 0.1, "edit_mode": "keep"},
                "P01-r2": {"parent_nmse": 0.1, "candidate_nmse": 0.2, "edit_mode": "swap_one"},
            })


if __name__ == "__main__":
    unittest.main()
