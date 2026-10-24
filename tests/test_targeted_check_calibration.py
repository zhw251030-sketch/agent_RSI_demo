import unittest

from analysis.basis_trial_v02.targeted_check_calibration import calibrate


class TargetedCheckCalibrationTests(unittest.TestCase):
    def test_three_way_calibration_is_deterministic(self):
        report = calibrate()
        self.assertTrue(report["calibration_passed"])
        self.assertEqual(report["observed_decisions"],
                         ["allow_candidate", "retain_parent", "defer"])
        self.assertEqual(report["model_calls"], 0)
        self.assertEqual(report["candidate_executions"], 0)
        self.assertEqual(report["archive_writes"], 0)
