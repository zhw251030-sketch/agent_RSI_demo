"""A paired archived state starts without execution and permits exactly one child."""
import copy
import hashlib
import importlib
import importlib.util
import json
import unittest
from unittest.mock import patch

from tests import test_diagnostic_controller as fixtures


class CompactControllerTests(unittest.TestCase):
    def setUp(self):
        fixtures.DiagnosticControllerTests.setUp(self)
        if importlib.util.find_spec('rsi_eval.compact_controller') is None:
            self.fail('Compact archived-state controller is not implemented')
        self.module = importlib.import_module('rsi_eval.compact_controller')
        source = 'archived candidate\n'
        digest = hashlib.sha256(source.encode()).hexdigest()
        raw = fixtures.DiagnosticControllerTests.evaluate('symbolic', 'oscillator1', source)
        diagnostic = raw['diagnostics']
        record = {'candidate_id': 'symbolic-002', 'parent_id': 'symbolic-001',
            'source_sha256': digest, 'n_params': 2, 'status': 'evaluated',
            'origin': 'model_proposed', 'rationale': 'Original uncorrected rationale.',
            'metrics': {'mse': 1.0, 'nmse': 1.0},
            'results': [{'task_id': 'oscillator1', **raw}],
            'selection': {'accepted': False, 'incumbent_id': 'symbolic-001',
                          'incumbent_source': 'earlier winner'},
            'generated_candidates_used': 2, 'generated_candidates_remaining': 1}
        self.seed = {'state_id': 'S1', 'family': 'symbolic', 'source': source,
            'n_params': 2, 'record': record, 'diagnostics': [diagnostic],
            'historical_common': {'claims': [{'malformed': 'preserve exactly'}],
                'prediction': {'reference': {'session_id': 'old-session'}, 'min_delta': 0.5}},
            'historical_checks': {'claim_results': [{'status': 'schema_invalid'}],
                'prediction_result': {'status': 'contradicted', 'actual': -1.0}},
            'provenance': {'runtime_commit': 'old', 'source_candidate_id': 'symbolic-002'}}

    def controller(self, condition='checked', suffix=''):
        return self.module.CompactController(self.root, self.config, self.root/(condition+suffix),
            condition=condition, session_id='run:S1', policy_text='One bounded revision.',
            repair_state=self.seed)

    def submission(self, controller):
        entry = next(row for row in controller.state_packet()['evidence'] if row['key'] == 'nmse')
        return dict(claim_id=entry['evidence_id'], claim_op='eq', claim_value_json='1.0',
                    prediction_id=entry['evidence_id'], prediction_direction='decrease',
                    prediction_min_delta=0.1)

    @staticmethod
    def evaluate(*args, **kwargs):
        result = fixtures.DiagnosticControllerTests.evaluate(*args, **kwargs)
        result['metrics'] = {'mse': 2.0, 'nmse': 2.0}
        return result

    def test_baseline_clones_previously_rejected_candidate_without_execution(self):
        original = copy.deepcopy(self.seed)
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate') as execute:
            c = self.controller()
            result = c.baseline()
            self.assertIs(c.baseline(), result)
        execute.assert_not_called()
        self.assertEqual(self.seed, original)
        self.assertEqual(result['candidate_id'], 'symbolic-000')
        self.assertIsNone(result['parent_id'])
        self.assertTrue(result['selection']['accepted'])
        self.assertEqual(result['selection']['incumbent_id'], 'symbolic-000')
        self.assertEqual(c.state_packet()['incumbent']['source'], self.seed['source'])
        self.assertEqual(result['metrics'], self.seed['record']['metrics'])
        self.assertEqual(result['results'], self.seed['record']['results'])
        self.assertEqual(result['origin'], 'archived_model_proposed_initial')
        self.assertEqual((c.output_dir/'candidates/symbolic-000.py').read_bytes(),
                         self.seed['source'].encode())
        self.assertEqual(c.summary()['executions'], 0)
        self.assertEqual(c.summary()['archived_task_records'], 1)
        self.assertFalse(c.summary()['strategy_updated'])

    def test_initial_common_packets_are_exactly_identical_and_history_unchanged(self):
        packets = []
        for condition in ('hidden', 'checked'):
            c = self.controller(condition)
            c.baseline()
            packet = c.state_packet()
            self.assertEqual(packet['frozen_history_common'], self.seed['historical_common'])
            self.assertEqual('frozen_history_checks' in packet, condition == 'checked')
            self.assertEqual(packet['generated_candidates_remaining'], 1)
            for field in ('checks_visible', 'audits', 'frozen_history_checks'):
                packet.pop(field, None)
            packets.append(packet)
        self.assertEqual(packets[0], packets[1])

    def test_registrations_and_exact_registry_are_persisted_before_new_execution(self):
        c = self.controller()
        c.baseline()
        def execute(*args, **kwargs):
            audit = json.loads((c.output_dir/'audits.json').read_text())[-1]
            self.assertEqual(audit['registration']['before'], 1.0)
            self.assertEqual(audit['registration']['reason'], 'prediction_registered')
            self.assertNotIn('prediction_result', audit)
            manifest = json.loads((c.output_dir/'evidence-registry.json').read_text())
            self.assertEqual(manifest['session_id'], 'run:S1')
            self.assertTrue(manifest['entries'])
            return self.evaluate(*args, **kwargs)
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=execute) as execute:
            c.submit('worse', 2, 'test', **self.submission(c))
        self.assertEqual(execute.call_count, 1)
        audit = c.audits[-1]
        self.assertEqual(audit['claim_results'][0]['status'], 'supported')
        self.assertEqual(audit['prediction_result']['status'], 'contradicted')
        self.assertEqual(audit['prediction_result']['after'], 2.0)
        self.assertFalse(c.records[-1]['selection']['accepted'])
        self.assertEqual(c.summary()['best']['candidate_id'], 'symbolic-000')
        self.assertEqual(c.summary()['executions'], 1)

    def test_invalid_json_claim_is_a_check_failure_and_never_blocks_candidate(self):
        invalid = ['true', 'null', '{}', '1 trailing', 'NaN', 'Infinity', '[1]', '[]']
        for index, value in enumerate(invalid):
            with self.subTest(value=value):
                c = self.controller(suffix=str(index))
                c.baseline()
                fields = self.submission(c)
                fields['claim_value_json'] = value
                with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate) as run:
                    c.submit('worse', 2, **fields)
                self.assertEqual(run.call_count, 1)
                self.assertEqual(c.audits[0]['claim_results'][0]['status'], 'schema_invalid')

    def test_non_utf8_decoded_fact_is_schema_invalid_without_breaking_audit_write(self):
        c = self.controller()
        c.baseline()
        evidence = c.current_evidence()
        evidence[0]['facts']['edges'] = [['from', 'a', 'b']]
        with patch.object(c, 'current_evidence', return_value=evidence):
            fields = self.submission(c)
            identifier = next(row['evidence_id'] for row in c.state_packet()['evidence']
                              if row['key'] == 'edges')
            fields.update(claim_id=identifier, claim_op='contains', claim_value_json='["\\ud800"]')
            with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate) as run:
                c.submit('worse', 2, **fields)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(c.audits[0]['claim_results'][0]['status'], 'schema_invalid')

    def test_unknown_claim_and_prediction_ids_do_not_gate_execution(self):
        c = self.controller()
        c.baseline()
        fields = self.submission(c)
        fields.update(claim_id='e_'+'0'*16, prediction_id='e_'+'0'*16)
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate) as run:
            c.submit('worse', 2, **fields)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(c.audits[0]['claim_results'][0]['status'], 'unavailable')
        self.assertEqual(c.audits[0]['registration']['status'], 'unavailable')

    def test_one_new_candidate_limit_is_independent_of_old_candidate_index(self):
        c = self.controller()
        c.baseline()
        fields = self.submission(c)
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate) as run:
            c.submit('worse', 2, **fields)
            denied = c.submit('second', 2, **fields)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(denied['status'], 'budget_exhausted')
        self.assertEqual(len(c.audits), 1)
        self.assertEqual(c.state_packet()['generated_candidates_remaining'], 0)

    def test_hidden_and_checked_child_packets_differ_only_in_declared_check_fields(self):
        packets = []
        for condition in ('hidden', 'checked'):
            c = self.controller(condition)
            c.baseline()
            with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate):
                feedback = c.submit('worse', 2, **self.submission(c))
            packet = c.state_packet()
            self.assertEqual('audit' in feedback, condition == 'checked')
            self.assertEqual('audits' in packet, condition == 'checked')
            if condition == 'checked':
                serialized = json.dumps(packet['audits'])
                self.assertNotIn('reference', serialized)
                self.assertNotIn('candidate_sha256', serialized)
            for field in ('checks_visible', 'audits', 'frozen_history_checks'):
                packet.pop(field, None)
            packets.append(packet)
        self.assertEqual(packets[0], packets[1])

    def test_invalid_source_does_not_spend_candidate_or_create_audit(self):
        c = self.controller()
        c.baseline()
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate') as run:
            result = c.submit('中'*6000, 2, **self.submission(c))
        run.assert_not_called()
        self.assertEqual(result['status'], 'invalid_request')
        self.assertFalse(c.audits)

    def test_seed_source_tampering_fails_before_use(self):
        self.seed['source'] += 'changed'
        with self.assertRaises(ValueError):
            self.controller().baseline()


if __name__ == '__main__':
    unittest.main()
