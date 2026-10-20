import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from rsi_eval.executor import evaluate_candidate
from rsi_eval.planning_trace import CandidateTrace


class ExecutorDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def plan(self, public, verdict='task_failure', replay='goal_unsatisfied', worker_error=False, trace=None):
        task = {'family': 'planning', 'objects': [], 'init': [], 'goal': []}
        payload = {'status': 'ok', 'plan': [], 'diagnostic_trace': CandidateTrace().snapshot()}
        if trace is not None:
            payload['diagnostic_trace'] = trace
        if worker_error:
            payload.update(status='candidate_error', error_kind='python_exception', exception_type='ValueError')
        with patch('rsi_eval.executor.planning.prepare_task', return_value=task), \
             patch('rsi_eval.executor.planning_diagnostics.is_public_prompt', return_value=public), \
             patch('rsi_eval.executor.planning_diagnostics.diagnose_plan', return_value={'status': replay}) as diagnose, \
             patch('rsi_eval.executor.planning.validate_plan', return_value={'status': verdict, 'plan_length': 0}), \
             patch('rsi_eval.executor.run_candidate', return_value={'status': 'completed', 'result': payload}) as run:
            result = evaluate_candidate('planning', 'fixed', 'fixture', root=self.root, diagnostics=True)
            return result, run.call_args.args[1], diagnose.call_count

    def test_public_trace_and_replay_are_bound_to_candidate_and_task(self):
        result, request, calls = self.plan(True)
        self.assertTrue(request['diagnostic_trace'])
        self.assertEqual(calls, 1)
        self.assertEqual(result['diagnostics']['candidate_sha256'], result['candidate_hash'])
        self.assertEqual(result['diagnostics']['scope'], 'public_prompt')
        self.assertEqual(result['status'], 'task_failure')

    def test_development_receives_no_trace_request_or_replay(self):
        result, request, calls = self.plan(False)
        self.assertNotIn('diagnostic_trace', request)
        self.assertNotIn('diagnostics', result)
        self.assertEqual(calls, 0)

    def test_disagreement_with_val_is_infrastructure_failure(self):
        result, _, _ = self.plan(True, verdict='success')
        self.assertEqual(result['status'], 'infrastructure_error')
        self.assertEqual(result['error_kind'], 'diagnostic_validator_disagreement')

    def test_worker_exception_keeps_bounded_trace_without_replay(self):
        result, _, calls = self.plan(True, worker_error=True)
        self.assertEqual(result['status'], 'candidate_error')
        self.assertIn('trace', result['diagnostics'])
        self.assertEqual(calls, 0)

    def test_large_valid_trace_does_not_replace_trusted_score(self):
        namespace = {}
        names = ['helper_%03d_' % i + 'x' * 60 for i in range(128)]
        exec(compile('\n'.join('def %s():\n    return None' % name for name in names),
                     'candidate.py', 'exec'), namespace)
        trace = CandidateTrace()
        with trace:
            for name in names:
                namespace[name]()
        result, _, _ = self.plan(True, verdict='success', replay='valid', trace=trace.snapshot())
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['diagnostics']['trace'],
                         {'status': 'unavailable', 'reason': 'candidate_trace_exceeds_feedback_budget'})

    def test_symbolic_stats_computed_from_fresh_predictions_on_host(self):
        task = {'family': 'symbolic', 'X': [[0.0], [1.0], [2.0], [3.0]],
                'y': [0.0, 1.0, 2.0, 3.0], 'input_names': ['x']}
        responses = [
            {'status': 'completed', 'result': {'status': 'ok', 'params': [1.0],
                'converged': True, 'nfev': 1, 'candidate_calls': 1}},
            {'status': 'completed', 'result': {'status': 'ok', 'predictions': [1.0, 2.0, 3.0, 4.0]}}]
        with patch('rsi_eval.executor.symbolic.prepare_task', return_value=task), \
             patch('rsi_eval.executor.run_candidate', side_effect=responses) as run:
            result = evaluate_candidate('symbolic', 'oscillator1', 'fixture', n_params=1,
                                        root=self.root, diagnostics=True)
        self.assertNotIn('y', run.call_args.args[1])
        self.assertEqual(result['diagnostics']['residuals']['bias'], 1.0)
        self.assertEqual(result['diagnostics']['scope'], 'train')
        self.assertNotIn('predictions', result['diagnostics']['residuals'])


if __name__ == '__main__':
    unittest.main()
