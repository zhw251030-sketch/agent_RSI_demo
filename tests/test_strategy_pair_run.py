"""The scheduler is exercised with fabricated provider and execution receipts.

No candidate source is executed and no benchmark data is opened in this file.
"""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rsi_eval import strategy_binding as binding
from rsi_eval.revision_policy import S0
from rsi_eval.role_executor import LIMITS, runtime_inventory, RoleExecutor

try:
    runner = importlib.import_module('rsi_eval.strategy_pair_run')
except ModuleNotFoundError as error:
    if error.name != 'rsi_eval.strategy_pair_run':
        raise
    runner = None

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = {'model': 'synthetic', 'messages': [
    {'role': 'system', 'content': 'Synthetic session'}, {'role': 'user', 'content': None}]}
BUDGET = {'max_requests': 36, 'max_requests_per_slot': 1, 'num_retries': 0}


def write(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else binding.canonical(value) + b'\n')
    return binding.file_ref(root, relative)


class SyntheticExecutorFactory:
    synthetic_only = True

    def __init__(self, output):
        self.output = output
        self.calls = []
        self.fail_at = None
        self.comparison_pattern = None

    def __call__(self, root, *, role, evaluation_gate=None):
        factory = self
        class Executor:
            synthetic_only = True

            def evaluate(self, family, task_id, source, *, n_params=0,
                         candidate_id=None, parent_id=None, strategy_version='baseline'):
                factory.calls.append((role, candidate_id, task_id))
                part = json.loads((root / binding.PARTITION).read_text())
                entries = part['planning']['tasks'] if family == 'planning' else part['symbolic']['files']
                entry = next(x for x in entries if x['task_id'] == task_id
                             and (family == 'planning' or x['split'] == 'train'))
                assert entry['role'] == role
                files, runtime = runtime_inventory()
                folder = factory.output + '/synthetic-executions/' + str(len(factory.calls))
                source_ref = write(root, folder + '/source.py', source.encode())
                request = dict(version='role-executor-v0.1', role=role, family=family,
                    task_id=task_id, candidate_sha256=source_ref['sha256'], n_params=n_params,
                    strategy_version=strategy_version, partition_sha256=binding.PARTITION_SHA256,
                    data_sha256=entry['sha256'], domain_sha256=part['planning']['domain_sha256'] if family == 'planning' else None,
                    evaluator_sha256=runtime, metric_scope=role if family == 'planning' else 'train', limits=LIMITS)
                request_ref = write(root, folder + '/request.json', request)
                row = {k: v for k, v in request.items() if k not in ('role', 'candidate_sha256')}
                row.update(record_kind='executor_observation', evidence_kind='synthetic', task_role=role,
                    candidate_hash=source_ref['sha256'], runtime_files=files, model_calls=0,
                    sealed_tasks_executed=0, request_sha256=request_ref['sha256'],
                    journal_path=folder + '/result.json', status='success',
                    executions=[{'phase': 'plan', 'status': 'completed'}])
                if family == 'planning':
                    row['validator'] = {'status': 'valid'}
                    if factory.comparison_pattern == 'mixed' and candidate_id and (
                            candidate_id.startswith('r1-selection-') and candidate_id.endswith('-fixed')
                            or candidate_id.startswith('r2-selection-') and candidate_id.endswith('-updated')):
                        row.update(status='task_failure', validator={'status': 'invalid'})
                else:
                    row.update(metrics={'nmse': 0.1, 'mse': 0.2}, fitting={
                        'n_params': n_params, 'split': 'train', 'converged': True,
                        'params': [0.0] * n_params, 'nfev': 1, 'candidate_calls': 1, 'max_nfev': 100},
                        executions=[{'phase': p, 'status': 'completed'} for p in ('fit', 'predict')])
                if len(factory.calls) == factory.fail_at:
                    row.update(status='infrastructure_error', executions=[])
                    row.pop('validator', None)
                write(root, row['journal_path'], row)
                return row
        return Executor()


class SyntheticSessions:
    def __init__(self):
        self.calls = []
        self.fail_at = None
        self.policy_override = None

    def __call__(self, slot, packet, directory):
        self.calls.append((copy.deepcopy(slot), copy.deepcopy(packet)))
        if len(self.calls) == self.fail_at:
            return {'status': 'error', 'request_id': 'request-' + slot['id'],
                    'usage_known': False, 'error_type': 'SyntheticTransportFailure'}
        folder = directory.relative_to(ROOT).as_posix()
        request = copy.deepcopy(TEMPLATE)
        request['messages'][1]['content'] = binding.canonical(packet).decode()
        request_ref = write(ROOT, folder + '/request.json', request)
        result = dict(status='accepted', request_id='request-' + slot['id'], request=request_ref)
        if slot['phase'] == 'update':
            rules = (['R05', 'R04', 'R06', 'R08'] if slot['arm'] == 'shadow' else
                     ['R01' if slot['replicate'] == 'r1' else 'R02', 'R04', 'R06', 'R08'])
            result['policy'] = self.policy_override or {'version': S0['version'], 'rule_ids': rules}
            return result
        state = packet['current_state']
        source_ref = write(ROOT, folder + '/source.py', state['source'].encode())
        sub = dict(version='strategy-submission-v0.1', slot_id=slot['id'],
            request_id=result['request_id'], request_sha256=request_ref['sha256'],
            status='accepted', source_sha256=source_ref['sha256'], n_params=state['n_params'])
        result.update(source=source_ref, submission=write(ROOT, folder + '/submission.json', sub))
        return result


class StrategyPairRunTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(runner, 'Bounded strategy scheduler is not implemented')
        temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp', prefix='scheduler-test-')
        self.addCleanup(temp.cleanup)
        self.output = (Path(temp.name) / 'run').relative_to(ROOT).as_posix()
        self.sessions = SyntheticSessions()
        self.executors = SyntheticExecutorFactory(self.output)

    def run_synthetic(self, **kwargs):
        return runner.run_strategy_pair(ROOT, self.output, session_runner=self.sessions,
            executor_factory=self.executors, request_template=TEMPLATE, budget=BUDGET,
            evidence_kind='synthetic', **kwargs)

    def test_all_36_slots_preserve_frozen_order_and_do_not_unlock_real_gate(self):
        self.executors.comparison_pattern = 'mixed'
        report = self.run_synthetic()
        expected = json.loads((ROOT / binding.FUTURE_ALLOCATION).read_text())['slots']
        self.assertEqual(report['status'], 'complete')
        self.assertEqual([s['id'] for s, _ in self.sessions.calls], [s['id'] for s in expected])
        self.assertEqual(report['evidence_kind'], 'synthetic')
        self.assertIsNone(report['production_evaluation_gate'])
        self.assertEqual(report['slot_counts'], {'completed': 36, 'failed': 0, 'not_started': 0})
        decisions = {rep: json.loads((ROOT / ref['path']).read_text()) for rep, ref in report['decisions'].items()}
        self.assertEqual(decisions['r1']['replay']['decision']['decision'], 'promote')
        self.assertEqual(decisions['r2']['replay']['decision']['decision'], 'retain')
        eval_updated = {s['replicate']: p['repair_policy']['rule_ids'] for s, p in self.sessions.calls
                        if s['phase'] == 'evaluation' and s['arm'] == 'updated'}
        self.assertEqual(eval_updated['r1'][0], 'R01')
        self.assertEqual(eval_updated['r2'], S0['rule_ids'])
        with self.assertRaisesRegex(ValueError, 'Synthetic'):
            binding.freeze_evaluation_gate(ROOT, report['decisions'], self.output + '/forbidden-gate.json')

    def test_transport_failure_stops_without_replacement_or_resume(self):
        self.sessions.fail_at = 3
        report = self.run_synthetic()
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(report['slot_counts'], {'completed': 2, 'failed': 1, 'not_started': 33})
        self.assertEqual(len(self.executors.calls), 0)
        self.assertFalse(report['failure']['session']['usage_known'])
        with self.assertRaises(FileExistsError):
            self.run_synthetic()

    def test_all_proposals_frozen_before_baselines_and_both_decisions_before_eval(self):
        report = self.run_synthetic()
        events = report['events']
        self.assertEqual([e['ordinal'] for e in events], list(range(1, len(events) + 1)))
        proposal = next(e['ordinal'] for e in events if e['kind'] == 'proposals_frozen')
        selection_base = min(e['ordinal'] for e in events if e['kind'] == 'baseline_started')
        self.assertLess(proposal, selection_base)
        gate = next(e['ordinal'] for e in events if e['kind'] == 'both_decisions_frozen')
        for event in events:
            if event['kind'] == 'baseline_started' and event['state_id'] in binding.EVALUATION_STATES:
                self.assertGreater(event['ordinal'], gate)
        actors = [p for s, p in self.sessions.calls if s['phase'] != 'update']
        self.assertTrue(all(p['repair_policy']['rule_ids'][0] != 'R05' for p in actors))

    def test_infrastructure_failure_stops_before_any_actor(self):
        self.executors.fail_at = 1
        report = self.run_synthetic()
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(len(self.sessions.calls), 4)
        self.assertIn('infrastructure', report['failure']['message'].lower())
        self.assertEqual(report['slot_counts']['not_started'], 32)

    def test_synthetic_mode_refuses_production_executor_factory(self):
        with self.assertRaisesRegex(ValueError, 'synthetic'):
            runner.run_strategy_pair(ROOT, self.output, session_runner=self.sessions,
                request_template=TEMPLATE, budget=BUDGET, evidence_kind='synthetic')

    def test_invalid_update_policy_stops_before_selection(self):
        self.sessions.policy_override = {'version': S0['version'], 'rule_ids': ['R01']}
        report = self.run_synthetic()
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(len(self.sessions.calls), 1)
        self.assertEqual(len(self.executors.calls), 0)

    def test_failure_between_decisions_never_starts_evaluation_baseline(self):
        original = binding.freeze_selection
        def fail_second(root, manifest, checksum, output):
            if output.endswith('r2-decision.json'):
                raise RuntimeError('Synthetic second decision write failure')
            return original(root, manifest, checksum, output)
        with patch.object(binding, 'freeze_selection', side_effect=fail_second):
            report = self.run_synthetic()
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(set(report['decisions']), {'r1'})
        self.assertEqual(len(self.sessions.calls), 20)
        self.assertFalse(any(state.startswith(('P-eval', 'S-bact', 'S-stress'))
                             for _, state, _ in self.executors.calls))

    def test_first_evaluation_baseline_failure_blocks_remaining_16_model_slots(self):
        self.executors.fail_at = 183  # 22 shared selection baselines + 160 selection measurements.
        report = self.run_synthetic()
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(set(report['decisions']), {'r1', 'r2'})
        self.assertEqual(len(self.sessions.calls), 20)
        self.assertEqual(report['slot_counts']['not_started'], 16)

    def test_pre_action_guard_rejection_precedes_provider_dispatch(self):
        def guard(action, **fields):
            if action == 'network':
                raise ValueError('frozen runtime changed')
        report = self.run_synthetic(pre_action_guard=guard)
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(self.sessions.calls, [])
        self.assertEqual(self.executors.calls, [])

    def test_reused_global_request_id_stops_second_proposal(self):
        original = self.sessions
        def repeated(slot, packet, directory):
            result = original(slot, packet, directory)
            result['request_id'] = 'reused'
            return result
        self.sessions = repeated
        report = self.run_synthetic()
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(report['slot_counts']['completed'], 1)
        self.assertIn('global request ID', report['failure']['message'])

    def test_synthetic_factory_returning_real_executor_is_rejected(self):
        class FakeFactory:
            synthetic_only = True
            def __call__(self, *args, **kwargs):
                return object.__new__(RoleExecutor)
        self.executors = FakeFactory()
        report = self.run_synthetic()
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(len(self.sessions.calls), 4)
        self.assertIn('synthetic executor instance', report['failure']['message'])

    def _observed_shape_fixture(self, family, role, tasks, source, n_params, gate_hash=None):
        """Fabricate contract-only observations; no genuine observed run is made.

        The tests patch authorization only around projection. These receipts
        never form a decision or production gate and are deleted at teardown.
        """
        executor = self.executors(ROOT, role=role)
        refs = []
        for task in tasks:
            row = executor.evaluate(family, task, source, n_params=n_params)
            path = row['journal_path']
            folder = Path(path).parent.as_posix()
            request = json.loads((ROOT / folder / 'request.json').read_text())
            row.pop('evidence_kind')
            row['error_kind'] = None  # Real planning._result(success) includes this.
            if gate_hash is not None:
                request['evaluation_gate_sha256'] = gate_hash
                row['evaluation_gate_sha256'] = gate_hash
            request_ref = write(ROOT, folder + '/request.json', request)
            row['request_sha256'] = request_ref['sha256']
            refs.append(write(ROOT, path, row))
        return refs

    def test_observed_evaluation_receipt_requires_exact_gate_hash(self):
        source = 'def equation(b, s, temp, pH, params):\n    return b * params[0]\n'
        gate_hash = 'a' * 64
        refs = self._observed_shape_fixture('symbolic', 'evaluation', ['bactgrow'], source, 1, gate_hash)
        gate = binding.EvaluationGate('unused-test-gate.json', gate_hash)
        with patch.object(binding, 'authorize_state_phase', return_value=gate_hash):
            result = runner.project_evaluation(ROOT, 'S-bact-eval-1', refs, source=source,
                n_params=1, policy_sha256='baseline', role='evaluation', evidence_kind='observed', evaluation_gate=gate)
            self.assertEqual(result[0]['status'], 'success')
            folder = Path(refs[0]['path']).parent.as_posix()
            request = json.loads((ROOT / folder / 'request.json').read_text())
            request['evaluation_gate_sha256'] = 'b' * 64
            request_ref = write(ROOT, folder + '/request.json', request)
            row = json.loads((ROOT / refs[0]['path']).read_text())
            row['request_sha256'] = request_ref['sha256']
            refs[0] = write(ROOT, refs[0]['path'], row)
            with self.assertRaisesRegex(ValueError, 'gate provenance'):
                runner.project_evaluation(ROOT, 'S-bact-eval-1', refs, source=source,
                    n_params=1, policy_sha256='baseline', role='evaluation', evidence_kind='observed', evaluation_gate=gate)

    def test_observed_eval_source_learning_feedback_accepts_null_diagnostics(self):
        source = 'def get_plan(objects, init, goal):\n    return []\n'
        tasks = [f'spannerlearning/seed0/problem{i}' for i in range(10)]
        refs = self._observed_shape_fixture('planning', 'learning', tasks, source, 0)
        with patch.object(binding, 'authorize_state_phase', return_value='a' * 64):
            result = runner.project_evaluation(ROOT, 'P-eval-1', refs, source=source,
                n_params=0, policy_sha256='baseline', role='learning', evidence_kind='observed')
            self.assertEqual(len(result), 10)
            self.assertTrue(all('error_kind' not in row for row in result))
            row = json.loads((ROOT / refs[0]['path']).read_text())
            row['candidate_line'] = True
            refs[0] = write(ROOT, refs[0]['path'], row)
            with self.assertRaisesRegex(ValueError, 'diagnostic location'):
                runner.project_evaluation(ROOT, 'P-eval-1', refs, source=source,
                    n_params=0, policy_sha256='baseline', role='learning', evidence_kind='observed')

    def test_observed_run_requires_pre_action_guard_before_creating_output(self):
        with self.assertRaisesRegex(ValueError, 'pre-action guard'):
            runner.run_strategy_pair(ROOT, self.output, session_runner=self.sessions,
                request_template=TEMPLATE, budget=BUDGET)
        self.assertFalse((ROOT / self.output).exists())


if __name__ == '__main__':
    unittest.main()
