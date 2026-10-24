import unittest

from analysis.basis_edit_comparison.protocol import (
    CONDITIONS, build_protocol, validate_protocol,
)


class EditCheckProtocolTests(unittest.TestCase):
    def test_protocol_has_six_candidates_and_three_shared_conditions(self):
        protocol = validate_protocol(build_protocol())
        self.assertEqual(len(protocol["parents"]), 3)
        self.assertEqual(len(protocol["slots"]), 6)
        self.assertTrue(all(slot["conditions"] == CONDITIONS for slot in protocol["slots"]))
        self.assertEqual(protocol["candidate_generation"]["model_requests"], 6)
        self.assertEqual(protocol["budget"]["max_gate_records"], 18)

    def test_protocol_keeps_sealed_splits_out(self):
        protocol = build_protocol()
        self.assertFalse(protocol["leakage_controls"]["sealed_data_read"])
        self.assertFalse(protocol["leakage_controls"]["test_id_read"])
        self.assertFalse(protocol["leakage_controls"]["test_ood_read"])

    def test_protocol_rejects_tampered_threshold(self):
        protocol = build_protocol()
        protocol["conditions"]["real_check"]["threshold"] = 0.1
        with self.assertRaises(ValueError):
            validate_protocol(protocol)


if __name__ == "__main__":
    unittest.main()
