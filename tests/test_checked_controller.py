import hashlib
import json
import unittest
from unittest.mock import patch

from tests import test_diagnostic_controller as fixtures
from rsi_eval.checked_controller import CheckedController, public_contract_facts


class CheckedControllerTests(unittest.TestCase):
    setUp = fixtures.DiagnosticControllerTests.setUp

    def controller(self, condition):
        return CheckedController(self.root, self.config, self.root/condition,
                                 condition=condition, session_id='run:'+condition,
                                 policy_text='Use typed claims and predictions.')

    def evaluate(self, *args, **kwargs):
        result = fixtures.DiagnosticControllerTests.evaluate(*args, **kwargs)
        if args[2] == 'worse':
            result['metrics'] = {'mse': 2., 'nmse': 2.}
        return result

    @staticmethod
    def submission(c, key='nmse'):
        snapshot = c.current_evidence()[0]
        reference = dict(snapshot['binding'], key=key)
        return ([dict(kind='scalar', reference=reference, op='gt', value=0.)],
                dict(reference=reference, direction='decrease', min_delta=0.01))

    def test_prediction_persisted_before_execution_and_checks_actual_rejected_child(self):
        c = self.controller('checked')
        def evaluate(*args, **kwargs):
            if args[2] == 'worse':
                saved = json.loads((c.output_dir/'audits.json').read_text())
                self.assertEqual(saved[-1]['registration']['reason'], 'prediction_registered')
                self.assertNotIn('prediction_result', saved[-1])
            return self.evaluate(*args, **kwargs)
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=evaluate):
            c.baseline()
            claims, prediction = self.submission(c)
            child = c.submit('worse', 1, 'test', claims=claims, prediction=prediction)
        self.assertFalse(child['selection']['accepted'])
        self.assertEqual(c.audits[-1]['prediction_result']['status'], 'contradicted')
        self.assertEqual(c.summary()['best']['candidate_id'], 'symbolic-000')
        self.assertEqual(c.audits[-1]['claim_results'][0]['status'], 'supported')

    def test_hidden_stores_checks_but_never_sends_them_in_packet_or_tool_feedback(self):
        for condition in ('hidden', 'checked'):
            c = self.controller(condition)
            with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate):
                c.baseline()
                claims, prediction = self.submission(c)
                feedback = c.submit('worse', 1, 'test', claims=claims, prediction=prediction)
            self.assertEqual(len(c.audits), 1)
            serialized = json.dumps(c.state_packet()) + json.dumps(feedback)
            self.assertEqual('prediction_result' in serialized, condition == 'checked')
            self.assertEqual('claim_results' in serialized, condition == 'checked')

    def test_invalid_or_stale_claim_does_not_gate_execution(self):
        c = self.controller('checked')
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate) as evaluate:
            c.baseline()
            claims, prediction = self.submission(c)
            claims[0]['reference']['candidate_sha256'] = '0'*64
            c.submit('worse', 1, claims=claims, prediction=prediction)
        self.assertEqual(evaluate.call_count, 2)
        self.assertEqual(c.audits[-1]['claim_results'][0]['status'], 'unavailable')

    def test_bias_ratio_and_zero_denominator_remain_finite_or_unavailable(self):
        c = self.controller('checked')
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate):
            c.baseline()
        self.assertEqual(c.current_evidence()[0]['scalars']['bias_squared_over_mse'], 1.)
        c.records[0]['metrics']['mse'] = 0.
        self.assertIsNone(c.evidence_for(c.records[0])[0]['scalars']['bias_squared_over_mse'])

    def test_public_contract_keeps_parameter_order_and_denies_development_before_read(self):
        domain = {'operators': {'walk': {'parameters': {'?a':'loc','?b':'loc','?m':'man'},
            'preconditions': [(False, ('at','?m','?a')), (False, ('link','?a','?b'))],
            'effects': [(True, ('at','?m','?a')), (False, ('at','?m','?b'))]}}}
        task = {'init': {('link','a','b')}, 'goal': {('at','m','b')}}
        with patch('rsi_eval.checked_controller.is_public_prompt', return_value=True), \
             patch('rsi_eval.checked_controller.planning._load_task', return_value=(domain,task,[])):
            facts = public_contract_facts('public', self.root)
        self.assertIn(['link','$0','$1'], facts['action.walk.preconditions.positive'])
        self.assertNotIn(['link','$1','$0'], facts['action.walk.preconditions.positive'])
        with patch('rsi_eval.checked_controller.is_public_prompt', return_value=False), \
             patch('rsi_eval.checked_controller.planning._load_task') as load:
            with self.assertRaises(PermissionError):
                public_contract_facts('private', self.root)
        load.assert_not_called()

    def test_source_limit_rejection_preserves_candidate_and_check_budgets(self):
        c = self.controller('checked')
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate):
            c.baseline()
            claims, prediction = self.submission(c)
            result = c.submit('中'*6000, 1, claims=claims, prediction=prediction)
        self.assertEqual(result['status'], 'invalid_request')
        self.assertEqual(len(c.records), 1)
        self.assertFalse(c.audits)

    def test_rejected_submission_remains_visible_after_history_replacement(self):
        c = self.controller('hidden')
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate):
            c.baseline()
            c.submit('worse', 1, claims=[], prediction={})
        self.assertEqual(c.state_packet()['latest_submission_rejection']['error_kind'],
                         'checked_submission_contract')

    def test_incomplete_infrastructure_batch_is_not_numeric_evidence(self):
        c = self.controller('checked')
        c.family = 'planning'
        record = {'candidate_id': 'planning-001', 'source_sha256': 'a'*64,
                  'status': 'infrastructure_error', 'metrics': {'total_successes': 0, 'total_tasks': 10},
                  'results': [{'task_id': 'spannerlearning/seed0/problem0', 'status': 'infrastructure_error'}]}
        self.assertIsNone(c.evidence_for(record)[0]['scalars']['total_successes'])

    def test_three_large_permitted_declarations_fit_both_visibility_conditions(self):
        for condition in ('hidden', 'checked'):
            c = self.controller(condition)
            with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate):
                c.baseline()
                for _ in range(3):
                    claims, prediction = self.submission(c)
                    # Bounded malformed claims are feedback, not an execution gate.
                    claims[0]['padding'] = 'x'*900
                    c.submit('worse', 1, claims=claims, prediction=prediction)
            packet = c.state_packet()
            self.assertEqual(packet['generated_candidates_remaining'], 0)
            self.assertLess(len(json.dumps(packet).encode()), 65536)


if __name__ == '__main__':
    unittest.main()
