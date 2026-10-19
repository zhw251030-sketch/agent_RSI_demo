import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rsi_eval.executor import evaluate_candidate


class ExecutorContractTests(unittest.TestCase):
    def test_predictions_do_not_receive_labels_and_host_scores(self):
        task = {'family': 'symbolic', 'task_id': 'oscillator1',
                'X': [[0], [1], [2]], 'y': [1, 3, 5], 'input_names': ['x']}
        responses = [
            {'status': 'completed', 'result': {'status': 'success', 'params': [2, 1], 'nfev': 3, 'converged': True, 'candidate_calls': 6}},
            {'status': 'completed', 'result': {'status': 'success', 'predictions': [1, 2, 3], 'mse': 0}},
        ]
        with tempfile.TemporaryDirectory() as td, patch('rsi_eval.executor.symbolic.prepare_task', return_value=task), patch('rsi_eval.executor.run_candidate', side_effect=responses) as run:
            result = evaluate_candidate('symbolic', 'oscillator1', 'source', root=Path(td), n_params=2)
        self.assertEqual(result['status'], 'success')
        self.assertAlmostEqual(result['metrics']['mse'], 5 / 3)
        self.assertNotIn('y', run.call_args_list[1].args[1])
        self.assertEqual(run.call_count, 2)

    def test_fit_failure_does_not_predict(self):
        task = {'family': 'symbolic', 'task_id': 'oscillator1', 'X': [[1]], 'y': [2], 'input_names': ['x']}
        with tempfile.TemporaryDirectory() as td, patch('rsi_eval.executor.symbolic.prepare_task', return_value=task), patch('rsi_eval.executor.run_candidate', return_value={'status': 'timeout'}) as run:
            result = evaluate_candidate('symbolic', 'oscillator1', 'source', root=Path(td), n_params=2)
        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(run.call_count, 1)

    def test_no_arbitrary_task_family(self):
        with tempfile.TemporaryDirectory() as td, patch('rsi_eval.executor.run_candidate') as run:
            result = evaluate_candidate('shell', 'any', 'source', root=Path(td))
        self.assertEqual(result['status'], 'invalid_request')
        run.assert_not_called()

    def test_untrusted_fit_metadata_cannot_break_journal(self):
        task = {'family': 'symbolic', 'task_id': 'oscillator1', 'X': [[1]], 'y': [2], 'input_names': ['x']}
        for bad in [float('nan'), float('inf'), '3', [3], True]:
            payload = {'status': 'success', 'params': [1], 'nfev': bad, 'converged': True, 'candidate_calls': 3}
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as td, patch('rsi_eval.executor.symbolic.prepare_task', return_value=task), patch('rsi_eval.executor.run_candidate', return_value={'status': 'completed', 'result': payload}) as run:
                result = evaluate_candidate('symbolic', 'oscillator1', 'source', root=Path(td), n_params=1)
                self.assertEqual(result['error_kind'], 'invalid_fit_metadata')
                self.assertEqual(run.call_count, 1)

    def test_extreme_fitted_parameter_is_rejected_and_journaled(self):
        task = {'family': 'symbolic', 'task_id': 'oscillator1', 'X': [[1]], 'y': [2], 'input_names': ['x']}
        payload = {'status': 'success', 'params': [10 ** 400], 'nfev': 3,
                   'converged': True, 'candidate_calls': 3}
        with tempfile.TemporaryDirectory() as td, patch('rsi_eval.executor.symbolic.prepare_task', return_value=task), patch('rsi_eval.executor.run_candidate', return_value={'status': 'completed', 'result': payload}) as run:
            result = evaluate_candidate('symbolic', 'oscillator1', 'source', root=Path(td), n_params=1)
            self.assertEqual(result['status'], 'candidate_error')
            self.assertEqual(result['error_kind'], 'invalid_fitted_parameters')
            self.assertEqual(run.call_count, 1)
            journals = list((Path(td) / 'runs/executor_feedback').glob('*.json'))
            self.assertEqual(len(journals), 1)
            self.assertEqual(json.loads(journals[0].read_text(encoding='utf-8')), result)


if __name__ == '__main__':
    unittest.main()
