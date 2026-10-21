"""New role boundaries, synthetic data, and isolated worker contract tests."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_planning import DOMAIN, PROBLEM


ROOT = Path(__file__).resolve().parents[1]
P_SELECT = 'spannerlearning/seed1/problem0'
P_EVAL = 'spannerlearning/seed3/problem0'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class RoleExecutorAvailability(unittest.TestCase):
    def test_pinned_metadata_opens_exact_role_sets_without_task_files(self):
        from rsi_eval.role_executor import RoleExecutor
        selection = RoleExecutor(ROOT, role='selection')
        learning = RoleExecutor(ROOT, role='learning')
        self.assertEqual(len(selection.task_ids('planning')), 19)
        self.assertEqual(selection.task_ids('symbolic'), ['oscillator2'])
        self.assertEqual(len(learning.task_ids('planning')), 10)
        self.assertEqual(learning.task_ids('symbolic'), ['oscillator1'])


class RoleExecutorTests(unittest.TestCase):
    def setUp(self):
        from rsi_eval import role_executor as module
        self.module = module
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.domain = self.root / 'data/planning/spanner/spannerlearning.pddl'
        self.domain.parent.mkdir(parents=True)
        self.domain.write_bytes(DOMAIN.encode())
        tasks = []
        for task, role in [(P_SELECT, 'selection'), (P_EVAL, 'evaluation'),
                           ('spannerlearning/seed0/problem0', 'learning'),
                           ('spannerlearning_test/seed1/problem0', 'sealed'),
                           ('spannerlearning/seed2/problem0', 'duplicate_excluded')]:
            relative = 'data/planning/spanner/' + task + '.pddl'
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(PROBLEM.encode())
            tasks.append(dict(task_id=task, role=role, data_path=relative,
                              sha256=sha(PROBLEM.encode())))
        files = []
        for task, role, columns in [
            ('oscillator1', 'learning', ['x', 'v', 'a']),
            ('oscillator2', 'selection', ['t', 'x', 'v', 'a']),
            ('bactgrow', 'evaluation', ['b', 's', 'temp', 'pH', 'db']),
            ('stressstrain', 'evaluation', ['strain', 'temp', 'stress'])]:
            for split in ['train', 'test_id']:
                values = ','.join('1' for _ in columns[:-1])
                raw = (','.join(columns) + '\n' + values + ',1\n' + values + ',3\n').encode()
                relative = f'data/symbolic/llm-sr/{task}/{split}.csv'
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                files.append(dict(task_id=task, split=split,
                                  role=role if split == 'train' else 'sealed',
                                  data_path=relative, sha256=sha(raw), bytes=len(raw),
                                  rows=2, columns=columns))
        self.manifest = dict(planning=dict(tasks=tasks, domain_sha256=sha(DOMAIN.encode())),
                             symbolic=dict(files=files))
        # The only fixture seam is metadata: all guarded loading, parsing,
        # execution orchestration, metric computation and journaling are real.
        self.patcher = patch.object(module, '_load_partition', return_value=(copy.deepcopy(self.manifest), 'a' * 64))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.executor = module.RoleExecutor(self.root, role='selection')

    def test_role_refusal_precedes_data_io(self):
        self.domain.unlink()
        for family, task in [('planning', P_EVAL), ('planning', 'spannerlearning/seed0/problem0'),
                             ('planning', 'spannerlearning_test/seed1/problem0'),
                             ('planning', 'spannerlearning/seed2/problem0'),
                             ('symbolic', 'bactgrow'), ('symbolic', 'oscillator1'),
                             ('symbolic', 'oscillator2/test_id'), ('symbolic', '../oscillator2')]:
            with self.subTest(task=task), self.assertRaises(PermissionError):
                self.executor.prepare_task(family, task)
        self.assertFalse((self.root / 'runs').exists())

    def test_selection_task_input_uses_only_authorized_data(self):
        prepared = self.executor.prepare_task('planning', P_SELECT)
        self.assertEqual(prepared['request']['goal'], [['tightened', 'nut1']])
        self.assertIn(['bob', 'man'], prepared['request']['objects'])
        self.assertEqual(prepared['provenance']['data_sha256'], sha(PROBLEM.encode()))
        symbolic = self.executor.prepare_task('symbolic', 'oscillator2')
        self.assertEqual(symbolic['request']['X'], [[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]])
        self.assertEqual(symbolic['request']['y'], [1.0, 3.0])
        self.assertEqual(symbolic['request']['input_names'], ['t', 'x', 'v'])
        self.assertEqual(symbolic['provenance']['metric_scope'], 'train')

    def test_changed_allowed_data_is_rejected_before_sandbox(self):
        path = self.root / f'data/planning/spanner/{P_SELECT}.pddl'
        path.write_text(PROBLEM + '\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.executor.prepare_task('planning', P_SELECT)

    def test_unknown_role_and_fake_evaluation_flag_are_refused(self):
        for role in ['sealed', True, 'evaluation']:
            with self.subTest(role=role), self.assertRaises((ValueError, PermissionError)):
                self.module.RoleExecutor(self.root, role=role)
        with self.assertRaises((ValueError, PermissionError)):
            self.module.RoleExecutor(self.root, role='evaluation', evaluation_gate=True)

    def test_evaluation_claimed_completion_does_not_authorize_data(self):
        for gate in [{'complete': True}, 'frozen', {'path': 'gate.json', 'sha256': 'a' * 64}]:
            with self.subTest(gate=gate), self.assertRaises(PermissionError):
                self.module.RoleExecutor(self.root, role='evaluation', evaluation_gate=gate)
        self.assertFalse((self.root / 'runs').exists())

    def test_evaluation_gate_rechecked_before_each_data_read(self):
        from rsi_eval import strategy_binding
        gate = strategy_binding.EvaluationGate('gate.json', 'a' * 64)
        # Replay verification is separately tested by strategy_binding. This
        # seam tests that an already-created executor cannot cache permission.
        with patch.object(strategy_binding, 'verify_evaluation_gate', return_value='a' * 64):
            executor = self.module.RoleExecutor(self.root, role='evaluation', evaluation_gate=gate)
            self.assertEqual(executor.prepare_task('symbolic', 'bactgrow')['request']['input_names'],
                             ['b', 's', 'temp', 'pH'])
            self.assertEqual(executor.prepare_task('symbolic', 'stressstrain')['request']['input_names'],
                             ['strain', 'temp'])
            with self.assertRaises(PermissionError):
                executor.prepare_task('symbolic', 'oscillator2')
        with patch.object(strategy_binding, 'verify_evaluation_gate', side_effect=PermissionError('revoked')):
            with self.assertRaises(PermissionError):
                executor.prepare_task('planning', P_EVAL)
        self.assertFalse((self.root / 'runs').exists())

    def test_learning_role_cannot_consume_selection_or_evaluation_data(self):
        executor = self.module.RoleExecutor(self.root, role='learning')
        prepared = executor.prepare_task('planning', 'spannerlearning/seed0/problem0')
        self.assertEqual(prepared['provenance']['metric_scope'], 'learning')
        self.assertEqual(executor.prepare_task('symbolic', 'oscillator1')['request']['y'], [1.0, 3.0])
        for family, task in [('planning', P_SELECT), ('planning', P_EVAL),
                             ('symbolic', 'oscillator2'), ('symbolic', 'bactgrow')]:
            with self.subTest(task=task), self.assertRaises(PermissionError):
                executor.prepare_task(family, task)

    def test_missing_allowed_data_yields_journaled_infrastructure_failure(self):
        (self.root / f'data/planning/spanner/{P_SELECT}.pddl').unlink()
        result = self.executor.evaluate('planning', P_SELECT, 'source')
        self.assertEqual(result['status'], 'infrastructure_error')
        self.assertEqual(result['executions'], [])
        self.assertTrue((self.root / result['journal_path']).is_file())

    def test_planning_success_requires_validator_and_sanitizes_operator_text(self):
        val_relative = 'vendor/llm-genplan/' + self.module.planning.VAL_DIRECTORY
        val_dir = self.root / val_relative
        val_dir.mkdir(parents=True)
        (val_dir / 'Validate').write_bytes(b'fake validator')
        (val_dir / 'libVAL.so').write_bytes(b'fake library')
        expected = {'Validate': sha(b'fake validator'), 'libVAL.so': sha(b'fake library')}
        response = dict(status='completed', result=dict(status='success', plan=[' (WALK shed gate bob) ']))
        def validator(binary, domain, problem, plan, directory, name, timeout):
            self.assertEqual(plan, ['(walk shed gate bob)'])
            self.assertEqual(problem.read_bytes(), PROBLEM.encode())
            return dict(status='valid', elapsed_seconds=0.1)
        with patch.object(self.module.planning, 'VAL_HASHES', expected), \
             patch.object(self.module.planning, 'run_val', side_effect=validator), \
             patch.object(self.module, 'run_candidate', return_value=response):
            result = self.executor.evaluate('planning', P_SELECT, 'source')
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['plan_length'], 1)
        self.assertEqual(result['validator']['status'], 'valid')

    def test_missing_validator_is_not_a_task_failure(self):
        response = dict(status='completed', result=dict(status='success', plan=[]))
        with patch.object(self.module, 'run_candidate', return_value=response):
            result = self.executor.evaluate('planning', P_SELECT, 'source')
        self.assertEqual(result['status'], 'infrastructure_error')
        self.assertEqual(result['error_kind'], 'validator_integrity')

    def test_symbolic_scoring_recomputes_on_host_and_predict_has_no_labels(self):
        seen = []
        def sandbox(source, request, **limits):
            seen.append(copy.deepcopy(request))
            if request['phase'] == 'fit':
                payload = dict(status='success', params=[2], converged=True, nfev=2, candidate_calls=3)
            else:
                self.assertNotIn('y', request)
                payload = dict(status='success', predictions=[2, 2], metrics={'nmse': 0})
            return dict(status='completed', elapsed_seconds=0.1, stdout_bytes=20,
                        stderr_bytes=0, result=payload)
        with patch.object(self.module, 'run_candidate', side_effect=sandbox):
            result = self.executor.evaluate('symbolic', 'oscillator2', 'def equation(X, params): return 2',
                                            n_params=1, strategy_version='b' * 64)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['metrics'], {'mse': 1.0, 'nmse': 1.0})
        self.assertEqual(result['n_params'], 1)
        self.assertEqual(len(result['executions']), 2)
        self.assertEqual([r['phase'] for r in seen], ['fit', 'predict'])
        self.assertEqual(result['task_role'], 'selection')
        self.assertEqual(result['sealed_tasks_executed'], 0)
        path = self.root / result['journal_path']
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), result)
        self.assertEqual((path.parent / 'source.py').read_bytes(), b'def equation(X, params): return 2')
        receipt = json.loads((path.parent / 'request.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['candidate_sha256'], result['candidate_hash'])
        self.assertEqual(result['request_sha256'], sha((path.parent / 'request.json').read_bytes()))

    def test_symbolic_fit_failure_has_no_prediction_or_score(self):
        with patch.object(self.module, 'run_candidate', return_value=dict(status='timeout', elapsed_seconds=20)):
            result = self.executor.evaluate('symbolic', 'oscillator2', 'source', n_params=1)
        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(len(result['executions']), 1)
        self.assertNotIn('metrics', result)

    def test_candidate_failure_preserves_exception_location_not_private_message(self):
        response = dict(status='completed', result=dict(status='candidate_error',
                        exception_type='TypeError', candidate_line=6, error='runtime_error',
                        message='private-message'))
        with patch.object(self.module, 'run_candidate', return_value=response):
            result = self.executor.evaluate('planning', P_SELECT, 'source', n_params=0)
        self.assertEqual(result['status'], 'candidate_error')
        self.assertEqual(result['candidate_line'], 6)
        self.assertNotIn('private-message', json.dumps(result))

    def test_malformed_plan_never_becomes_success(self):
        response = dict(status='completed', result=dict(status='success', plan=['(teleport bob)']))
        with patch.object(self.module, 'run_candidate', return_value=response):
            result = self.executor.evaluate('planning', P_SELECT, 'source', n_params=0)
        self.assertEqual(result['status'], 'invalid_output')
        self.assertEqual(result['error_kind'], 'unknown_operator')

    def test_permission_denial_cannot_create_record_or_run_candidate(self):
        with self.assertRaises(PermissionError):
            self.executor.evaluate('symbolic', 'bactgrow', 'source', n_params=1)
        self.assertFalse((self.root / 'runs').exists())

    def test_fitting_metadata_and_parameter_limits_are_not_trusted(self):
        for n_params in [True, -1, 17, 1.5]:
            with self.subTest(n_params=n_params), self.assertRaises(ValueError):
                self.executor.evaluate('symbolic', 'oscillator2', 'source', n_params=n_params)
        for params in [[float('inf')], [True], ['1'], []]:
            response = dict(status='completed', result=dict(status='success', params=params,
                            converged=True, nfev=2, candidate_calls=3))
            with self.subTest(params=params), patch.object(self.module, 'run_candidate', return_value=response):
                result = self.executor.evaluate('symbolic', 'oscillator2', 'source', n_params=1)
                self.assertEqual(result['error_kind'], 'invalid_fitted_parameters')
                self.assertEqual(len(result['executions']), 1)


if __name__ == '__main__':
    unittest.main()
