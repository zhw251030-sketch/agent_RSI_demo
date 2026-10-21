"""Boundary and original-response diagnosis, with no provider or task execution."""
import importlib.util
import json
from pathlib import Path
import unittest

MODULE=Path(__file__).with_name('replay_failure.py')
SPEC=importlib.util.spec_from_file_location('basis_trial_failure_replay',MODULE)
replay=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


class FailureDiagnosisTests(unittest.TestCase):
    def test_original_rules_valid_but_explanation_exceeds_frozen_bound(self):
        result=replay.diagnose(replay.ROOT,replay.ROOT/replay.DEFAULT_SOURCE)
        self.assertEqual(result['valid_policy']['rule_ids'],['R01','R05','R04','R08'])
        self.assertEqual(result['explanation_characters'],4223)
        self.assertEqual(result['explanation_utf8_bytes'],4223)
        self.assertEqual(result['excess_characters'],2223)
        self.assertEqual(result['parser_error'],{'type':'ValueError','message':'Nonblank bounded policy explanation required'})
        self.assertEqual(result['synthetic_length_boundary_check'],{'2000':'accepted','2001':'rejected'})

    def test_original_response_and_usage_are_preserved_without_acceptance(self):
        root=replay.ROOT
        before=(root/replay.DEFAULT_SOURCE/'requests/request-0001.response.json').read_bytes()
        result=replay.diagnose(root,root/replay.DEFAULT_SOURCE)
        self.assertEqual(result['original_recorded_usage'],{'prompt_tokens':25210,'completion_tokens':944,'total_tokens':26154})
        self.assertEqual(result['new_model_requests'],0)
        self.assertEqual(result['candidate_executions'],0)
        self.assertEqual((root/replay.DEFAULT_SOURCE/'requests/request-0001.response.json').read_bytes(),before)

    def test_explanation_boundary_is_character_not_byte_bound(self):
        business={'rule_ids':['R01','R05','R04','R08'],'explanation':'中'*2000}
        self.assertEqual(replay.sdk_controller.validate_policy_business(business),business)
        business['explanation']+='中'
        with self.assertRaises(ValueError): replay.sdk_controller.validate_policy_business(business)


if __name__=='__main__':unittest.main()
