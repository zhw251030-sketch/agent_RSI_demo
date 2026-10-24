import importlib.util
import unittest

from analysis.basis_edit_comparison.preflight import run_preflight


try:
    SDK = importlib.util.find_spec("openhands.sdk") is not None
except ModuleNotFoundError:
    SDK = False


@unittest.skipUnless(SDK, "Requires OpenHands SDK 1.55.1")
class BasisEditPreflightTests(unittest.TestCase):
    def test_six_slots_and_eighteen_gates_have_one_request_each(self):
        result = run_preflight()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["slots"], 6)
        self.assertEqual(result["accepted_slots"], 6)
        self.assertEqual(result["gate_records"], 18)
        self.assertEqual(result["model_requests"], 6)
        self.assertEqual(result["usage_unknown"], 0)
        self.assertGreaterEqual(result["real_retain_parent"], 1)


if __name__ == "__main__":
    unittest.main()
