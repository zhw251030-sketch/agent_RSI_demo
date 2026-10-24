import unittest

from analysis.basis_edit_comparison.threshold_sensitivity import scan_thresholds


class BasisThresholdSensitivityTests(unittest.TestCase):
    def test_scalar_threshold_exposes_mixed_outcomes_with_same_evidence(self):
        rows = [
            {
                "proposal_id": "P02-r1",
                "parent_id": "P02",
                "removed_feature_id": "m_2_0_0",
                "removed_coefficient_abs": 3.0e-5,
                "delta_nmse": -1.0e-3,
            },
            {
                "proposal_id": "P02-r2",
                "parent_id": "P02",
                "removed_feature_id": "m_2_0_0",
                "removed_coefficient_abs": 3.0e-5,
                "delta_nmse": 2.0e-3,
            },
            {
                "proposal_id": "P03-r1",
                "parent_id": "P03",
                "removed_feature_id": "m_0_1_1",
                "removed_coefficient_abs": 0.18,
                "delta_nmse": -2.0e-4,
            },
        ]

        report = scan_thresholds(rows, [0.0, 4.0e-5, 0.2])

        self.assertEqual(report["ambiguous_groups"], [
            {
                "parent_id": "P02",
                "removed_feature_id": "m_2_0_0",
                "removed_coefficient_abs": 3.0e-5,
                "proposal_ids": ["P02-r1", "P02-r2"],
                "harmful_proposal_ids": ["P02-r2"],
            }
        ])
        self.assertEqual(
            [item["harmful_deployments"] for item in report["thresholds"]],
            [0, 1, 1],
        )
        self.assertEqual(
            [item["candidate_executions"] for item in report["thresholds"]],
            [0, 2, 3],
        )

    def test_rejects_missing_or_invalid_rows(self):
        with self.assertRaises(ValueError):
            scan_thresholds([{"proposal_id": "P01"}], [0.05])
        with self.assertRaises(ValueError):
            scan_thresholds([], [0.05])
        with self.assertRaises(ValueError):
            scan_thresholds(
                [
                    {
                        "proposal_id": "P01",
                        "parent_id": "P01",
                        "removed_feature_id": "m_1",
                        "removed_coefficient_abs": -1.0,
                        "delta_nmse": 0.1,
                    }
                ],
                [0.05],
            )


if __name__ == "__main__":
    unittest.main()
