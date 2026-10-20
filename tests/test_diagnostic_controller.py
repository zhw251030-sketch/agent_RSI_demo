import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rsi_eval.diagnostic_controller import DiagnosticController
from rsi_eval.symbolic_diagnostics import summarize_residuals


class DiagnosticControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for folder in ('fixtures', 'prompts'):
            (self.root/folder).mkdir()
        (self.root/'fixtures/start.py').write_bytes(b'initial')
        (self.root/'prompts/task.md').write_text('Public interface.\n## Fixed revision procedure\nOld rule.', encoding='utf-8')
        self.config = dict(session_id='symbolic', family='symbolic', prompt_file='prompts/task.md',
            initial_candidate='fixtures/start.py', initial_candidate_sha256=hashlib.sha256(b'initial').hexdigest(),
            initial_n_params=1, task_ids=['oscillator1'], prompt_task_ids=[],
            strategy_version='fixed-revision-v0.1', max_generated_candidates=3)

    def controller(self, arm):
        return DiagnosticController(self.root, self.config, self.root/arm, arm=arm, policy_text='Policy '+arm)

    @staticmethod
    def evaluate(family, task_id, source, **kwargs):
        digest = hashlib.sha256(source.encode()).hexdigest()
        return {'status': 'success', 'metrics': {'mse': 1.0, 'nmse': 1.0},
                'candidate_hash': digest, 'run_id': 'a'*32,
                'diagnostics': {'version': 'diagnostics-v0.1', 'task_id': task_id,
                    'candidate_sha256': digest, 'scope': 'train',
                    'residuals': summarize_residuals([[0.], [1.]], [0., 1.], [1., 2.], ['x'])}}

    def test_all_arms_compute_same_initial_observations_but_a_hides_them(self):
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate) as run:
            controllers = [self.controller(arm) for arm in 'ABC']
            records = [c.baseline() for c in controllers]
        self.assertEqual(len({c.initial_observation_digest() for c in controllers}), 1)
        self.assertNotIn('diagnostics', records[0]['results'][0])
        self.assertEqual(records[1]['results'][0]['diagnostics'], records[2]['results'][0]['diagnostics'])
        self.assertTrue(all(call.kwargs['diagnostics'] is True for call in run.call_args_list))
        self.assertNotIn('standardized_bias', controllers[0].task_prompt())
        self.assertIn('standardized_bias', controllers[1].task_prompt())
        self.assertNotIn('Old rule', controllers[2].task_prompt())
        self.assertIn('Policy C', controllers[2].task_prompt())

    def test_arm_and_task_bounds_are_preserved(self):
        with self.assertRaises(ValueError):
            self.controller('D')
        self.config['task_ids'] = ['oscillator2']
        with self.assertRaises(ValueError):
            self.controller('B')

    def test_binding_mismatch_fails_closed_before_observation_is_exposed(self):
        def forged(*args, **kwargs):
            result = self.evaluate(*args, **kwargs)
            result['diagnostics']['candidate_sha256'] = '0'*64
            return result
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=forged):
            c = self.controller('B'); result = c.baseline()
        self.assertTrue(c.halted)
        self.assertEqual(result['results'][0]['error_kind'], 'diagnostic_contract')

    def test_unexpected_nested_private_field_is_rejected(self):
        def forged(*args, **kwargs):
            result = self.evaluate(*args, **kwargs)
            result['diagnostics']['residuals']['private'] = 'secret'
            return result
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=forged):
            c = self.controller('B'); result = c.baseline()
        self.assertTrue(c.halted)
        self.assertNotIn('secret', json.dumps(result))

    def test_candidate_limit_and_no_strategy_self_update(self):
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate) as run:
            c = self.controller('C'); c.baseline()
            for _ in range(3): c.submit('candidate', 1, 'uncertain')
            self.assertEqual(c.submit('extra', 1)['status'], 'budget_exhausted')
        self.assertEqual(run.call_count, 4)
        self.assertFalse(c.summary()['strategy_updated'])
        self.assertEqual(c.summary()['arm'], 'C')


if __name__ == '__main__':
    unittest.main()
