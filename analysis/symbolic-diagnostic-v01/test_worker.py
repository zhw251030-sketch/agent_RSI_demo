"""Artificial arrays and optimizer doubles only; zero real-data fits."""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np


BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
SOURCE = 'def equation(x, params):\n    return params[0] * x + params[1]\n'
FIT = dict(phase='fit', X=[[0.], [1.], [2.]], y=[1., 3., 5.], n_params=2)


def load_worker(path=None):
    spec = importlib.util.spec_from_file_location(
        'diagnostic_worker_test', path or BASE/'runtime/rsi_eval/symbolic_worker.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.np = np
    return module


def optimizer_result(**overrides):
    values = dict(x=np.array([2., 1.]), success=True, status=1,
                  message='`gtol` termination condition is satisfied.',
                  nfev=2, njev=2, cost=0., optimality=0.)
    values.update(overrides)
    return SimpleNamespace(**values)


class DiagnosticWorkerTests(unittest.TestCase):
    def setUp(self):
        self.worker = load_worker()

    def run_with(self, result=None, source=SOURCE, request=None):
        if result is None:
            result = optimizer_result()
        def optimizer(residual, initial, **kwargs):
            self.assertEqual(kwargs, {'max_nfev': 100})
            self.assertEqual(initial.tolist(), [1., 1.])
            residual(initial)
            residual(np.array([2., 1.]))
            return result
        self.worker.least_squares = optimizer
        return self.worker.run(source, request or FIT)

    def diagnostics(self, value):
        self.assertIn('diagnostics', value)
        return value['diagnostics']

    def test_success_records_optimizer_without_extra_candidate_calls(self):
        value = self.run_with()
        self.assertEqual(value['status'], 'success')
        self.assertEqual(value['params'], [2., 1.])
        self.assertEqual(value['candidate_calls'], 3)
        d = self.diagnostics(value)
        self.assertEqual(d['initial_params'], [1., 1.])
        self.assertEqual(d['final_params'], [2., 1.])
        self.assertTrue(d['final_params_finite'])
        self.assertTrue(d['optimizer_returned'])
        self.assertEqual(d['optimizer_invocations'], 1)
        self.assertTrue(d['optimizer_success'])
        self.assertEqual(d['optimizer_status'], 1)
        self.assertEqual(d['optimizer_message'], '`gtol` termination condition is satisfied.')
        self.assertEqual((d['nfev'], d['njev']), (2, 2))
        self.assertEqual((d['optimizer_cost'], d['optimality']), (0., 0.))
        self.assertEqual((d['optimizer_candidate_calls'], d['postfit_confirmation_calls'], d['candidate_calls']), (2, 1, 3))
        self.assertIsNone(d['exception_type'])

    def test_nonconvergence_preserves_last_iterate_and_reason_without_score(self):
        value = self.run_with(optimizer_result(success=False, status=0,
            message='The maximum number of function evaluations is exceeded.',
            x=np.array([1.5, 1.]), nfev=100, njev=98, cost=0.625, optimality=2.5))
        self.assertEqual((value['status'], value['error']), ('candidate_error', 'optimization_failed'))
        self.assertNotIn('params', value)
        self.assertNotIn('nmse', value)
        d = self.diagnostics(value)
        self.assertFalse(d['optimizer_success'])
        self.assertEqual(d['optimizer_status'], 0)
        self.assertEqual(d['nfev'], 100)
        self.assertEqual(d['final_params'], [1.5, 1.])
        self.assertEqual(d['optimizer_cost'], 0.625)
        self.assertEqual((d['candidate_calls'], d['postfit_confirmation_calls']), (2, 0))

    def test_nonfinite_last_iterate_is_explicit_json_null(self):
        value = self.run_with(optimizer_result(x=np.array([np.inf, np.nan]),
            cost=np.inf, optimality=np.nan))
        self.assertEqual(value['error'], 'optimization_failed')
        d = self.diagnostics(value)
        self.assertEqual(d['final_params'], [None, None])
        self.assertFalse(d['final_params_finite'])
        self.assertIsNone(d['optimizer_cost'])
        self.assertIsNone(d['optimality'])
        json.dumps(value, allow_nan=False)

    def test_optimizer_exception_does_not_fabricate_result_or_message(self):
        def optimizer(residual, initial, **kwargs):
            residual(initial)
            raise ValueError('do not expose arbitrary data exception text')
        self.worker.least_squares = optimizer
        value = self.worker.run(SOURCE, FIT)
        d = self.diagnostics(value)
        self.assertEqual(value['error'], 'optimization_failed')
        self.assertEqual(d['exception_type'], 'ValueError')
        self.assertEqual((d['optimizer_invocations'], d['candidate_calls']), (1, 1))
        self.assertFalse(d['optimizer_returned'])
        for name in ('optimizer_status', 'optimizer_message', 'optimizer_success', 'nfev', 'final_params'):
            self.assertIsNone(d[name])
        self.assertNotIn('arbitrary data', json.dumps(value))

    def test_candidate_error_during_optimizer_preserves_calls(self):
        def optimizer(residual, initial, **kwargs):
            residual(initial)
        self.worker.least_squares = optimizer
        value = self.worker.run('def equation(x, params):\n    raise RuntimeError("private")\n', FIT)
        self.assertEqual(value['error'], 'execution_error')
        d = self.diagnostics(value)
        self.assertEqual(d['candidate_calls'], 1)
        self.assertEqual(d['exception_type'], 'RuntimeError')
        self.assertFalse(d['optimizer_returned'])

    def test_compilation_error_records_no_optimizer_invocation(self):
        self.worker.least_squares = lambda *args, **kwargs: self.fail('optimizer should not run')
        value = self.worker.run('def equation(:', FIT)
        self.assertEqual(value['error'], 'execution_error')
        d = self.diagnostics(value)
        self.assertEqual((d['optimizer_invocations'], d['candidate_calls']), (0, 0))
        self.assertEqual(d['initial_params'], [1., 1.])
        self.assertEqual(d['exception_type'], 'SyntaxError')

    def test_no_parameter_branch_does_not_invoke_optimizer(self):
        self.worker.least_squares = lambda *args, **kwargs: self.fail('optimizer should not run')
        value = self.worker.run('def equation(x, params):\n    return 2*x+1\n', {**FIT, 'n_params': 0})
        self.assertEqual(value['status'], 'success')
        d = self.diagnostics(value)
        self.assertEqual(d['final_params'], [])
        self.assertEqual((d['optimizer_invocations'], d['candidate_calls']), (0, 1))
        self.assertFalse(d['optimizer_returned'])
        self.assertIsNone(d['optimizer_status'])

    def test_predict_and_request_validation_match_old_worker(self):
        old = load_worker(ROOT/'rsi_eval/symbolic_worker.py')
        old.least_squares = self.worker.least_squares = lambda *args, **kwargs: self.fail('not a fit')
        requests = [dict(phase='predict', X=[[0.], [1.]], params=[2., 1.]),
                    dict(phase='predict', X=[[0.]], params=[2., 1.], y=[1.]),
                    {**FIT, 'n_params': 17}, {**FIT, 'X': [[float('inf')]]},
                    {**FIT, 'y': [1.]}, {**FIT, 'phase': 'unknown'}]
        for request in requests:
            with self.subTest(request=request):
                self.assertEqual(self.worker.run(SOURCE, request), old.run(SOURCE, request))

    def test_bootstrap_performs_only_original_synthetic_warmup(self):
        calls = []
        def fake(residual, initial, **kwargs):
            calls.append((initial.tolist(), kwargs, residual(initial).tolist()))
        scipy = ModuleType('scipy')
        optimize = ModuleType('scipy.optimize')
        scipy.optimize = optimize
        optimize.least_squares = fake
        with patch.dict(sys.modules, {'scipy': scipy, 'scipy.optimize': optimize}):
            self.worker.prepare_runtime()
        self.assertEqual(calls, [([1., 1., 1.], {'max_nfev': 2}, [-1., 4., -3., 0.])])


if __name__ == '__main__':
    unittest.main(verbosity=2)
