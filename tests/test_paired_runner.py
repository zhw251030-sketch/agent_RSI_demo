"""Paired-run boundaries with no SDK, credentials, model, or task execution."""
import contextlib
import copy
import hashlib
import importlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


PROJECT = Path(__file__).resolve().parents[1]
CONFIG = 'configs/pilots/paired-repair-v0.1.json'


class FakeController:
    def __init__(self, family='planning', condition='hidden', pair_id='P1-r1'):
        self.family = family
        self.condition = condition
        self.halted = False
        self.initial_source = 'fixed source for '+family
        self.initial_n_params = 0 if family == 'planning' else 3
        digest = hashlib.sha256(self.initial_source.encode()).hexdigest()
        score = {'prompt_successes': 0, 'development_successes': 0, 'total_successes': 0} if family == 'planning' else {'mse': 0.1, 'nmse': 0.2}
        self.records = [{'candidate_id': family+'-000', 'source_sha256': digest,
            'n_params': self.initial_n_params, 'source': self.initial_source, 'status': 'evaluated',
            'metrics': score, 'results': [{'status': 'success'}]*(10 if family == 'planning' else 1),
            'selection': {'incumbent_id': family+'-000', 'incumbent_source': self.initial_source}}]
        self.packet = {'session_id': pair_id, 'incumbent': {
            'source': self.initial_source, 'source_sha256': digest, 'n_params': self.initial_n_params},
            'evidence': [{'key': 'same evidence'}], 'metadata': {'same': 'same'},
            'checks_visible': condition == 'checked'}
        if condition == 'checked':
            self.packet.update(audits=[], frozen_history_checks={'prediction_result': {'status': 'contradicted'}})

    def state_packet(self):
        return copy.deepcopy(self.packet)

    def add_child(self, *, status='evaluated', metrics=None):
        if metrics is None:
            metrics = {'prompt_successes': 2, 'development_successes': 8, 'total_successes': 10} if self.family == 'planning' else {'mse': 0.05, 'nmse': 0.1}
        self.records.append({'candidate_id': self.family+'-001', 'status': status,
            'metrics': copy.deepcopy(metrics), 'n_params': self.initial_n_params,
            'results': [{'status': 'success' if status == 'evaluated' else 'infrastructure_error'}]
                       *(10 if self.family == 'planning' else 1)})

    def summary(self):
        return {'family': self.family, 'baseline': self.records[0], 'first': self.records[1] if len(self.records)>1 else None,
                'last': self.records[-1] if len(self.records)>1 else None, 'best': self.records[-1],
                'generated_candidates': len(self.records)-1, 'halted': self.halted,
                'executions': sum(len(r['results']) for r in self.records)}


class FakeLedger:
    def __init__(self):
        self.value = {'halted': False, 'usage_unknown_count': 0, 'reserved_count': 0, 'request_count': 0,
                      'failed_count': 0, 'session_counts': {}}

    def summary(self):
        return copy.deepcopy(self.value)


class PairedRunnerTests(unittest.TestCase):
    def setUp(self):
        self.runner = importlib.import_module('scripts.run_paired_repair')
        self.config = json.loads((PROJECT/CONFIG).read_text(encoding='utf-8'))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def prepared(self):
        result = []
        for item in self.config['order']:
            entry = dict(item, status='not_started')
            controller = FakeController(entry['family'], entry['condition'], entry['pair_id'])
            directory = self.root/entry['session_id']
            directory.mkdir(exist_ok=True)
            result.append((controller, directory, entry))
        return result

    def test_frozen_config_is_accepted_and_returned_values_are_clones(self):
        original = copy.deepcopy(self.config)
        order, budgets = self.runner.validate_config(self.config)
        self.assertEqual(order, self.config['order'])
        self.assertEqual(budgets, self.config['budgets'])
        order[0]['state_id'] = 'changed'
        budgets['max_requests'] = 999
        self.assertEqual(self.config, original)

    def test_order_pairing_and_conditions_cannot_be_rearranged(self):
        changes = [lambda c: c['order'].reverse(), lambda c: c['order'].pop(),
                   lambda c: c['order'][0].update(condition='checked'),
                   lambda c: c['order'][0].update(pair_id='S1-r1'),
                   lambda c: c['order'][0].update(repeat=2),
                   lambda c: c['order'][0].update(family='symbolic'),
                   lambda c: c['order'][0].update(session_id='../outside')]
        for change in changes:
            with self.subTest(change=change):
                config = copy.deepcopy(self.config)
                change(config)
                with self.assertRaises(ValueError):
                    self.runner.validate_config(config)

    def test_budget_expansion_and_invalid_numbers_are_rejected(self):
        for key, value in [('max_requests', 9), ('max_requests_per_session', 2),
                           ('max_output_tokens', 4097), ('max_input_bytes', 98305),
                           ('max_reserved_tokens', 1500001), ('max_cost_cny', 5.01),
                           ('max_cost_cny', float('nan')), ('input_cny_per_million', float('inf')),
                           ('input_cny_per_million', 2.0), ('output_cny_per_million', 8.0),
                           ('max_requests', True), ('max_requests', 0)]:
            with self.subTest(key=key, value=value):
                config = copy.deepcopy(self.config)
                config['budgets'][key] = value
                with self.assertRaises(ValueError):
                    self.runner.validate_config(config)

    def test_protocol_policy_and_no_recovery_flags_are_frozen(self):
        for key, value in [('schema_version', '9'), ('base_config', '../other.json'),
                           ('policy_file', 'prompts/checked/policy.md'), ('protocol', 'other.md'),
                           ('max_generated_candidates', 2), ('max_iterations', 2),
                           ('strategy_updated', True), ('checks_gate_execution', True),
                           ('checks_change_selection', True), ('automatic_recovery', True),
                           ('baseline_reexecution', True), ('source_limit_bytes', 16385)]:
            with self.subTest(key=key):
                config = copy.deepcopy(self.config)
                config[key] = value
                with self.assertRaises(ValueError):
                    self.runner.validate_config(config)

    def test_common_packet_removes_only_three_declared_channels_without_mutation(self):
        packet = {'checks_visible': True, 'audits': [{'supported': True}],
                  'frozen_history_checks': {'outcome': 'contradicted'},
                  'metadata': {'audits_sha256': 'must-not-be-silently-hidden'},
                  'frozen_history': {'prediction': {'threshold': 0.5}}}
        original = copy.deepcopy(packet)
        common = self.runner.common_packet(packet)
        self.assertEqual(common, {k:v for k,v in packet.items() if k not in
                                 {'checks_visible', 'audits', 'frozen_history_checks'}})
        common['frozen_history']['prediction']['threshold'] = 0
        self.assertEqual(packet, original)

    def test_pairs_accept_only_check_channel_differences_and_report_four_digests(self):
        prepared = self.prepared()
        digests = self.runner.verify_pairs(prepared)
        self.assertEqual(set(digests), {'P1-r1', 'P1-r2', 'S1-r1', 'S1-r2'})
        for pair_id, value in digests.items():
            self.assertEqual(len(value['common_sha256']), 64)
            controller = next(c for c,_,entry in prepared if entry['pair_id'] == pair_id)
            self.assertEqual(value['source_sha256'], controller.records[0]['source_sha256'])
            self.assertEqual(value['n_params'], controller.records[0]['n_params'])

    def test_common_metadata_or_source_or_parameter_difference_rejects_pair(self):
        for mutation in [lambda c: c.packet['metadata'].update(condition_leak='hidden'),
                         lambda c: c.records[0].update(source_sha256='0'*64),
                         lambda c: c.records[0].update(n_params=7),
                         lambda c: c.packet['incumbent'].update(source='different source')]:
            with self.subTest(mutation=mutation):
                prepared = self.prepared()
                mutation(prepared[0][0])
                with self.assertRaises(ValueError):
                    self.runner.verify_pairs(prepared)

    def test_missing_or_duplicate_pair_condition_is_rejected(self):
        prepared = self.prepared()
        with self.assertRaises(ValueError):
            self.runner.verify_pairs(prepared[1:])
        prepared = self.prepared()
        prepared[0][2]['condition'] = 'checked'
        with self.assertRaises(ValueError):
            self.runner.verify_pairs(prepared)

    def test_no_child_has_no_method_score_and_no_new_task_execution(self):
        for family in ('planning', 'symbolic'):
            result = self.runner.summarize_endpoint(FakeController(family))
            self.assertEqual(result['generated_candidates_executed'], 0)
            self.assertEqual(result['actual_task_executions'], 0)
            self.assertIsNone(result['child_metrics'])
            self.assertIsNone(result['improvement'])
            self.assertFalse(result['submitted_and_improved'])
            self.assertTrue(result['baseline_metrics'])

    def test_single_child_improvement_is_relative_to_seed_and_counts_only_new_tasks(self):
        for family, delta, executions in [('planning', 10, 10), ('symbolic', 0.1, 1)]:
            controller = FakeController(family)
            controller.add_child()
            result = self.runner.summarize_endpoint(controller)
            self.assertEqual(result['generated_candidates_executed'], 1)
            self.assertEqual(result['actual_task_executions'], executions)
            self.assertAlmostEqual(result['improvement'], delta)
            self.assertTrue(result['submitted_and_improved'])
            self.assertEqual(result['child_metrics'], controller.records[1]['metrics'])

    def test_tie_and_degradation_are_not_improvements(self):
        for nmse, delta in [(0.2, 0.0), (0.3, -0.1)]:
            controller = FakeController('symbolic')
            controller.add_child(metrics={'mse': 0.1, 'nmse': nmse})
            result = self.runner.summarize_endpoint(controller)
            self.assertFalse(result['submitted_and_improved'])
            self.assertAlmostEqual(result['improvement'], delta)

    def test_infrastructure_or_nonfinite_child_is_not_assigned_a_score(self):
        for status, metrics in [('infrastructure_error', {'mse': 0.0, 'nmse': 0.0}),
                                ('evaluated', {'mse': 0.0, 'nmse': float('nan')})]:
            controller = FakeController('symbolic')
            controller.add_child(status=status, metrics=metrics)
            result = self.runner.summarize_endpoint(controller)
            self.assertFalse(result['submitted_and_improved'])
            self.assertIsNone(result['child_metrics'])
            self.assertIsNone(result['improvement'])

    def test_incomplete_task_results_cannot_receive_a_score(self):
        for family in ('planning', 'symbolic'):
            controller = FakeController(family)
            controller.add_child()
            controller.records[1]['results'].pop()
            result = self.runner.summarize_endpoint(controller)
            self.assertIsNone(result['child_metrics'])
            self.assertIsNone(result['improvement'])
            self.assertFalse(result['submitted_and_improved'])

    def invoke_prepared(self, behavior):
        prepared = self.prepared()
        self.runner.verify_pairs(prepared)
        ledger = FakeLedger()
        calls = []
        agent = types.ModuleType('rsi_eval.compact_agent')
        auth = types.ModuleType('scripts.configure_minimax')
        auth.auth_path = lambda value: value
        auth.read_key = lambda path: 'fixture-secret-token'

        class LLM:
            def __init__(self, **kwargs):
                self.config = kwargs
            def bind_controller(self, controller):
                self.controller = controller
                return self
            def bind_pilot(self, received_ledger, session_id, path):
                self.ledger = received_ledger
                self.session_id = session_id
                return self

        def run(controller, llm, session_id, directory, *, tool_factory, max_iterations):
            self.assertEqual(max_iterations, 1)
            self.assertIs(tool_factory, agent.compact_candidate_tool)
            calls.append(session_id)
            ledger.value['request_count'] += 1
            return behavior(controller, ledger, session_id, len(calls))

        agent.CompactStatePacketLLM = LLM
        agent.compact_candidate_tool = object()
        agent.run_session = run
        report = {'sessions': [entry for _,_,entry in prepared]}
        config = {'model': 'frozen'}
        with patch.dict('sys.modules', {'rsi_eval.compact_agent': agent, 'scripts.configure_minimax': auth}):
            self.runner._run_prepared(prepared, report, ledger, config, self.root/'auth.json')
        self.assertNotIn('api_key', config)
        self.assertNotIn('fixture-secret-token', json.dumps(report))
        for path in self.root.rglob('*.json'):
            self.assertNotIn('fixture-secret-token', path.read_text(encoding='utf-8'))
        return report, calls, ledger

    def test_sdk_iteration_stop_is_preserved_after_real_candidate_and_does_not_abort(self):
        def stopped(controller, ledger, session, count):
            controller.add_child()
            return {'session_id': session, 'status': 'stopped', 'model_error_type': None,
                    'conversation_status': 'ConversationExecutionStatus.ERROR', 'controller': controller.summary()}
        report, calls, _ = self.invoke_prepared(stopped)
        self.assertEqual(len(calls), 8)
        self.assertEqual([entry['status'] for entry in report['sessions']], ['stopped']*8)
        self.assertNotIn('stop_reason', report)

    def test_known_incomplete_tool_response_with_known_usage_does_not_abort_later_pairs(self):
        def incomplete(controller, ledger, session, count):
            return {'session_id': session, 'status': 'error', 'model_error_type': 'IncompleteToolResponseError',
                    'controller': controller.summary()}
        report, calls, _ = self.invoke_prepared(incomplete)
        self.assertEqual(len(calls), 8)
        self.assertEqual([entry['status'] for entry in report['sessions']], ['error']*8)
        self.assertNotIn('stop_reason', report)

    def test_unknown_usage_aborts_remaining_sessions_even_for_known_contract_error(self):
        def unknown(controller, ledger, session, count):
            ledger.value.update(usage_unknown_count=1, halted=True)
            return {'session_id': session, 'status': 'error', 'model_error_type': 'IncompleteToolResponseError',
                    'controller': controller.summary()}
        report, calls, _ = self.invoke_prepared(unknown)
        self.assertEqual(len(calls), 1)
        self.assertEqual([entry['status'] for entry in report['sessions']][1:], ['not_started_after_stop']*7)
        self.assertIn('stop_reason', report)

    def test_infrastructure_and_unknown_provider_error_abort_remaining_sessions(self):
        for mode in ['infrastructure', 'provider']:
            with self.subTest(mode=mode):
                def failure(controller, ledger, session, count):
                    if mode == 'infrastructure':
                        controller.halted = True
                    return {'session_id': session, 'status': 'completed' if mode == 'infrastructure' else 'error',
                            'model_error_type': None if mode == 'infrastructure' else 'ProviderError',
                            'controller': controller.summary()}
                report, calls, _ = self.invoke_prepared(failure)
                self.assertEqual(len(calls), 1)
                self.assertEqual([entry['status'] for entry in report['sessions']][1:], ['not_started_after_stop']*7)

    def test_existing_run_is_rejected_before_any_summary_can_be_rewritten(self):
        directory = self.root/'runs/paired-repair/immutable'
        directory.mkdir(parents=True)
        (directory/'summary.json').write_bytes(b'{"previous": "preserve these exact bytes"}\n')
        (directory/'raw-evidence.txt').write_bytes(b'old run evidence\r\n')
        before = {p.relative_to(self.root).as_posix(): p.read_bytes()
                  for p in self.root.rglob('*') if p.is_file()}
        output = io.StringIO()
        with patch.object(self.runner, 'ROOT', self.root), \
             patch.object(self.runner, 'source_provenance') as provenance, \
             contextlib.redirect_stdout(output):
            code = self.runner.main(['--run-id', 'immutable', '--prepare-only'])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())['error_type'], 'FileExistsError')
        self.assertEqual({p.relative_to(self.root).as_posix(): p.read_bytes()
                          for p in self.root.rglob('*') if p.is_file()}, before)
        provenance.assert_not_called()

    def test_missing_or_mismatched_pairs_abort_before_credentials_are_read(self):
        for mode in ('missing', 'mismatched'):
            with self.subTest(mode=mode):
                prepared = self.prepared()
                if mode == 'missing':
                    prepared.pop()
                else:
                    prepared[0][0].packet['metadata']['unexpected_difference'] = True
                agent = types.ModuleType('rsi_eval.compact_agent')
                agent.CompactStatePacketLLM = Mock()
                agent.compact_candidate_tool = object()
                agent.run_session = Mock()
                auth = types.ModuleType('scripts.configure_minimax')
                auth.auth_path = Mock()
                auth.read_key = Mock(return_value='fixture-secret-token')
                with patch.dict('sys.modules', {'rsi_eval.compact_agent': agent,
                                               'scripts.configure_minimax': auth}), \
                     self.assertRaises(ValueError):
                    self.runner._run_prepared(prepared, {}, FakeLedger(), {'model': 'frozen'}, self.root/'auth.json')
                auth.auth_path.assert_not_called()
                auth.read_key.assert_not_called()
                agent.CompactStatePacketLLM.assert_not_called()
                agent.run_session.assert_not_called()

    def test_unknown_usage_in_last_session_still_stops_run(self):
        def last_unknown(controller, ledger, session, count):
            if count == 8:
                ledger.value.update(usage_unknown_count=1, halted=True)
            return {'session_id': session, 'status': 'completed', 'model_error_type': None,
                    'controller': controller.summary()}
        report, calls, ledger = self.invoke_prepared(last_unknown)
        self.assertEqual(len(calls), 8)
        self.assertEqual(ledger.summary()['usage_unknown_count'], 1)
        self.assertEqual(report['status'], 'stopped')
        self.assertIn('stop_reason', report)
        self.assertNotEqual(report['status'], 'attempts_completed')


if __name__ == '__main__':
    unittest.main()
