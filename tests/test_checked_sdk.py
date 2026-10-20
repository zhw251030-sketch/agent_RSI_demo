"""Real SDK tool/transport boundary tests; model transport and task execution are fake."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    SDK_PRESENT = importlib.util.find_spec('openhands.sdk') is not None
except ModuleNotFoundError:
    SDK_PRESENT = False

if SDK_PRESENT:
    from litellm.types.utils import ModelResponse
    from pydantic import ValidationError
    from rsi_eval.checked_agent import CheckedCandidateAction, StatePacketLLM, checked_candidate_tool
    from rsi_eval.checked_controller import CheckedController
    from rsi_eval.pilot_agent import run_session
    from rsi_eval.pilot_budget import BudgetExceeded, BudgetLedger
    from rsi_eval.planning_trace import CandidateTrace
    from rsi_eval.symbolic_diagnostics import summarize_residuals


@unittest.skipUnless(SDK_PRESENT, 'OpenHands SDK is not installed in this interpreter')
class CheckedSDKTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'fixtures').mkdir()
        (self.root / 'prompts').mkdir()
        (self.root / 'fixtures/initial.py').write_bytes(b'# baseline\n')
        (self.root / 'prompts/task.md').write_text(
            'Use the public task contract.\n## Fixed revision procedure\nOriginal policy.', encoding='utf-8')

    def controller(self, family, condition, suffix=''):
        tasks = ([f'spannerlearning/seed0/problem{i}' for i in range(10)]
                 if family == 'planning' else ['oscillator1'])
        config = {'session_id': family, 'family': family,
            'prompt_file': 'prompts/task.md', 'initial_candidate': 'fixtures/initial.py',
            'initial_candidate_sha256': hashlib.sha256(b'# baseline\n').hexdigest(),
            'initial_n_params': 0 if family == 'planning' else 1,
            'task_ids': tasks, 'prompt_task_ids': tasks[:2] if family == 'planning' else [],
            'strategy_version': 'fixed-revision-v0.1', 'max_generated_candidates': 3}
        output = self.root / (family + '_' + condition + suffix)
        with patch('rsi_eval.checked_controller.public_contract_facts', return_value={
                'action.move.preconditions.positive': [['edge', '$0', '$1']]}), \
                patch('rsi_eval.checked_controller.planning.prepare_task',
                      side_effect=lambda task, root: {'task_id': task, 'objects': []}):
            return CheckedController(self.root, config, output, condition=condition,
                session_id='checked-test-run:' + family + '_' + condition,
                policy_text='Submit a measured claim and a prediction, then revise.')

    @staticmethod
    def evaluate(family, task_id, source, **kwargs):
        digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
        result = {'status': 'task_failure' if family == 'planning' else 'success',
                  'candidate_hash': digest, 'run_id': 'a' * 32}
        diagnostic = {'version': 'diagnostics-v0.1', 'task_id': task_id,
                      'candidate_sha256': digest,
                      'scope': 'public_prompt' if family == 'planning' else 'train'}
        if family == 'planning':
            if task_id not in [f'spannerlearning/seed0/problem{i}' for i in range(2)]:
                return result
            diagnostic.update(trace=CandidateTrace().snapshot(), plan_replay={
                'status': 'goal_unsatisfied', 'executed_actions': 0, 'plan_length': 0,
                'first_failed_action': None, 'missing_preconditions': [],
                'missing_preconditions_truncated': False,
                'unsatisfied_goals': [['done', 'target']], 'unsatisfied_goals_truncated': False})
        else:
            # The second proposed source is rejected; the third is selected.
            score = (0.9 if 'LONG_SOURCE_1' in source else 1.3 if 'LONG_SOURCE_2' in source
                     else 0.8 if 'LONG_SOURCE_3' in source else 1.0)
            result['metrics'] = {'mse': score, 'nmse': score}
            diagnostic['residuals'] = summarize_residuals(
                [[0.0], [1.0], [2.0], [3.0]], [0.0, 1.0, 2.0, 3.0],
                [1.0, 2.0, 3.0, 4.0], ['x'])
        result['diagnostics'] = diagnostic
        return result

    @staticmethod
    def source(index):
        # Long strings include UTF-8 and JSON escaping overhead but fit 16 KiB.
        return '# LONG_SOURCE_' + str(index) + '\n# ' + ('测\\"' * 2400) + '\n'

    @staticmethod
    def hypothesis(controller):
        selected = controller.summary()['best']
        snapshot = controller.evidence_for(selected)[0]
        key = 'nmse' if controller.family == 'symbolic' else 'total_successes'
        ref = {**snapshot['binding'], 'key': key}
        return ([{'kind': 'scalar', 'reference': ref, 'op': 'ge', 'value': 100.0}],
                {'reference': ref, 'direction': 'decrease', 'min_delta': 0.5})

    @staticmethod
    def response(index, arguments=None):
        message = {'role': 'assistant', 'content': 'REVISION_REASON'}
        if arguments is not None:
            message['tool_calls'] = [{'id': 'call-' + str(index), 'type': 'function',
                'function': {'name': 'submit_candidate', 'arguments': json.dumps(arguments)}}]
        return ModelResponse(id='response-' + str(index), model='minimax-m3', choices=[{
            'message': message, 'finish_reason': 'tool_calls' if arguments is not None else 'stop'}],
            usage={'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120})

    def llm(self, controller, **limits):
        output = controller.output_dir / 'sdk'
        session_id = controller.family + '_' + controller.condition
        ledger = BudgetLedger(output / 'budget-ledger.json', max_requests=4,
                              session_ids=[session_id], **limits)
        llm = StatePacketLLM(model='anthropic/minimax-m3', api_key='fake-checked-sdk-key',
            base_url='https://example.invalid', max_output_tokens=4096, num_retries=0,
            caching_prompt=False, api_mode='chat', stream=False, reasoning_effort='none'
        ).bind_pilot(ledger, session_id, output / 'requests').bind_controller(controller)
        return llm, ledger, output, session_id

    def test_four_sdk_requests_replace_history_and_hide_check_outcomes(self):
        for family in ('planning', 'symbolic'):
            for condition in ('hidden', 'checked'):
                with self.subTest(family=family, condition=condition):
                    controller = self.controller(family, condition)
                    llm, ledger, output, session_id = self.llm(controller)
                    dispatched = []

                    def transport(**kwargs):
                        dispatched.append(copy.deepcopy(kwargs))
                        index = len(dispatched)
                        if index == 4:
                            return self.response(index)
                        claims, prediction = self.hypothesis(controller)
                        return self.response(index, {'source': self.source(index),
                            'n_params': 0 if family == 'planning' else 1,
                            'rationale': 'REVISION_REASON', 'claims': claims, 'prediction': prediction})

                    with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate), \
                            patch('openhands.sdk.llm.llm.litellm_completion', side_effect=transport), \
                            patch('openhands.sdk.conversation.impl.local_conversation.load_available_plugins',
                                  side_effect=AssertionError('ambient plugin discovery')):
                        controller.baseline()
                        report = run_session(controller, llm, session_id, output,
                                             tool_factory=checked_candidate_tool)
                    self.assertEqual(report['status'], 'completed', report)
                    self.assertEqual(ledger.summary()['request_count'], 4)
                    self.assertEqual(ledger.summary()['known_total_tokens'], 480)
                    self.assertEqual(len(controller.records), 4)
                    self.assertEqual(len(dispatched), 4)
                    self.assertEqual(report['tools'], ['finish', 'submit_candidate'])
                    self.assertEqual(len(controller.audits), 3)
                    self.assertTrue(all(a['claim_results'][0]['status'] == 'contradicted'
                                        for a in controller.audits))
                    packets = []
                    for index, call in enumerate(dispatched, 1):
                        requests = output / 'requests'
                        request = json.loads((requests / f'request-{index:04d}.request.json').read_text())
                        audit = json.loads((requests / f'input-audit-{index:04d}.json').read_text())
                        packet = json.loads((requests / f'packet-{index:04d}.json').read_text())
                        packets.append(packet)
                        # No accumulated assistant/tool/user messages reach the provider.
                        self.assertEqual([m['role'] for m in request['messages']], ['system', 'user'])
                        self.assertEqual(json.loads(request['messages'][-1]['content']), packet)
                        self.assertEqual(call['messages'], request['messages'])
                        self.assertEqual({t['function']['name'] for t in request['tools']},
                                         {'finish', 'submit_candidate'})
                        self.assertEqual(call['max_retries'], 0)
                        encoded = json.dumps(request, ensure_ascii=False, sort_keys=True,
                                             separators=(',', ':'), allow_nan=False).encode('utf-8')
                        self.assertEqual(audit['actual_input_bytes'], len(encoded))
                        self.assertEqual(audit['payload_sha256'], hashlib.sha256(encoded).hexdigest())
                        self.assertEqual(audit['excess_bytes'], 0)
                        self.assertTrue(audit['request_reserved'])
                        self.assertTrue(audit['network_dispatch_attempted'])
                        self.assertTrue(audit['transport_called'])
                        self.assertLessEqual(len(encoded), 98304)
                        if condition == 'hidden':
                            self.assertNotIn('audits', packet)
                            self.assertNotIn('audits_sha256', packet['metadata'])
                            self.assertNotIn('claim_results', json.dumps(packet))
                            self.assertNotIn('prediction_result', json.dumps(packet))
                        else:
                            self.assertEqual(len(packet['audits']), index - 1)
                    self.assertEqual([len(p['history']) for p in packets], [1, 2, 3, 4])
                    self.assertEqual(packets[-1]['generated_candidates_remaining'], 0)
                    if family == 'symbolic':
                        self.assertEqual([p['incumbent']['candidate_id'] for p in packets],
                                         ['symbolic-000', 'symbolic-001', 'symbolic-001', 'symbolic-003'])
                        self.assertNotIn('LONG_SOURCE_2', json.dumps(packets[-1]))
                        self.assertEqual(packets[-1]['incumbent']['source'], self.source(3))
                    for path in output.rglob('*.json'):
                        self.assertNotIn('fake-checked-sdk-key', path.read_text())

    def test_oversize_complete_payload_is_recorded_before_reservation_or_network(self):
        controller = self.controller('symbolic', 'hidden', 'oversize')
        llm, ledger, output, _ = self.llm(controller)
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate):
            controller.baseline()
        tools = [{'type': 'function', 'function': {'name': 'submit_candidate',
                  'description': 'large tool schema ' * 7000}}]
        original = [{'role': 'system', 'content': 'fixed'},
                    {'role': 'assistant', 'content': 'stale secret ' * 10000}]
        with patch('openhands.sdk.llm.llm.litellm_completion') as network:
            with self.assertRaises(BudgetExceeded):
                llm._transport_call(messages=original, tools=tools, max_tokens=4096)
        self.assertEqual(network.call_count, 0)
        self.assertEqual(ledger.summary()['request_count'], 0)
        audit = json.loads((output / 'requests/input-audit-0001.json').read_text())
        self.assertEqual(audit['reason'], 'input_byte_cap_exceeded')
        self.assertGreater(audit['actual_input_bytes'], 98304)
        packet = json.loads((output / 'requests/packet-0001.json').read_text(encoding='utf-8'))
        expected = {'model': 'anthropic/minimax-m3',
            'messages': [{'role': 'system', 'content': 'fixed'}, {'role': 'user',
                'content': json.dumps(packet, ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':'), allow_nan=False)}],
            'tools': tools, 'tool_choice': None, 'max_output_tokens': 4096}
        expected_bytes = json.dumps(expected, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')
        self.assertEqual(audit['actual_input_bytes'], len(expected_bytes))
        self.assertEqual(audit['payload_sha256'], hashlib.sha256(expected_bytes).hexdigest())
        self.assertEqual(audit['excess_bytes'], audit['actual_input_bytes'] - 98304)
        self.assertFalse(audit['request_reserved'])
        self.assertFalse(audit['transport_called'])
        self.assertFalse(audit['network_dispatch_attempted'])
        self.assertNotIn('stale secret', (output / 'requests/packet-0001.json').read_text())
        self.assertFalse(list((output / 'requests').glob('*.request.json')))

    def test_packet_contract_failure_keeps_safe_denial_without_partial_payload(self):
        controller = self.controller('symbolic', 'hidden', 'packeterror')
        llm, ledger, output, _ = self.llm(controller)
        with patch.object(controller, 'state_packet', side_effect=ValueError('PRIVATE_ERROR_BODY')), \
                patch('openhands.sdk.llm.llm.litellm_completion') as network:
            with self.assertRaises(ValueError):
                llm._transport_call(messages=[], max_tokens=4096)
        audit = json.loads((output / 'requests/input-audit-0001.json').read_text(encoding='utf-8'))
        self.assertEqual(audit['reason'], 'state_packet_contract')
        self.assertIsNone(audit['actual_input_bytes'])
        self.assertIsNone(audit['payload_sha256'])
        self.assertFalse(audit['request_reserved'])
        self.assertFalse(audit['network_dispatch_attempted'])
        self.assertEqual(ledger.summary()['request_count'], 0)
        self.assertEqual(network.call_count, 0)
        self.assertNotIn('PRIVATE_ERROR_BODY', json.dumps(audit))

    def test_request_log_failure_records_reservation_without_claiming_dispatch(self):
        controller = self.controller('symbolic', 'hidden', 'logerror')
        llm, ledger, output, _ = self.llm(controller)
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate):
            controller.baseline()
        # This failure is after reserve but before the parent's transport-start hook.
        with patch('rsi_eval.pilot_agent.write_json', side_effect=OSError('PRIVATE_IO_BODY')), \
                patch('openhands.sdk.llm.llm.litellm_completion') as network:
            with self.assertRaises(OSError):
                llm._transport_call(messages=[], max_tokens=4096)
        audit = json.loads((output / 'requests/input-audit-0001.json').read_text(encoding='utf-8'))
        self.assertEqual(audit['reason'], 'pretransport_error')
        self.assertTrue(audit['request_reserved'])
        self.assertFalse(audit['network_dispatch_attempted'])
        self.assertFalse(audit['transport_called'])
        self.assertEqual(ledger.summary()['request_count'], 1)
        self.assertEqual(ledger.summary()['reserved_count'], 1)
        self.assertEqual(network.call_count, 0)
        self.assertNotIn('PRIVATE_IO_BODY', json.dumps(audit))

    def test_cumulative_budget_denial_does_not_claim_network_dispatch(self):
        controller = self.controller('symbolic', 'hidden', 'budget')
        llm, ledger, output, _ = self.llm(controller, max_reserved_tokens=1)
        with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate):
            controller.baseline()
        with patch('openhands.sdk.llm.llm.litellm_completion') as network:
            with self.assertRaises(BudgetExceeded):
                llm._transport_call(messages=[{'role': 'system', 'content': 'fixed'}], max_tokens=4096)
        audit = json.loads((output / 'requests/input-audit-0001.json').read_text())
        self.assertEqual(audit['reason'], 'reserved_token_cap_exceeded')
        self.assertEqual(ledger.summary()['request_count'], 0)
        self.assertEqual(network.call_count, 0)
        self.assertFalse(audit['transport_called'])
        self.assertFalse(audit['network_dispatch_attempted'])
        self.assertFalse(audit['request_reserved'])

    def test_schema_rejection_survives_replacement_then_clears_after_valid_submission(self):
        for condition in ('hidden', 'checked'):
            with self.subTest(condition=condition):
                controller = self.controller('symbolic', condition, 'schema-recovery')
                llm, ledger, output, session_id = self.llm(controller)
                dispatched = []

                def transport(**kwargs):
                    dispatched.append(copy.deepcopy(kwargs))
                    index = len(dispatched)
                    if index == 3:
                        return self.response(index)
                    claims, prediction = self.hypothesis(controller)
                    return self.response(index, {'source': 'BAD_SOURCE_MUST_NOT_REAPPEAR' if index == 1
                                                 else self.source(1),
                        'n_params': True if index == 1 else 1,
                        'rationale': 'BAD_REASON_MUST_NOT_REAPPEAR' if index == 1 else 'valid revision',
                        'claims': claims, 'prediction': prediction})

                with patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=self.evaluate), \
                        patch('openhands.sdk.llm.llm.litellm_completion', side_effect=transport):
                    controller.baseline()
                    report = run_session(controller, llm, session_id, output,
                                         tool_factory=checked_candidate_tool)
                self.assertEqual(report['status'], 'completed', report)
                self.assertEqual(ledger.summary()['request_count'], 3)
                self.assertEqual(ledger.summary()['known_total_tokens'], 360)
                self.assertEqual(len(controller.records), 2)  # Only the valid submission executes.
                packets = [json.loads((output / f'requests/packet-{i:04d}.json').read_text(encoding='utf-8'))
                           for i in range(1, 4)]
                self.assertNotIn('last_tool_validation', packets[0])
                self.assertEqual(packets[1]['last_tool_validation'],
                                 {'status': 'invalid_request', 'error_kind': 'submission_schema'})
                self.assertNotIn('last_tool_validation', packets[2])
                self.assertEqual(packets[1]['generated_candidates_remaining'], 3)
                self.assertEqual(packets[2]['generated_candidates_remaining'], 2)
                for packet in packets[1:]:
                    self.assertNotIn('BAD_SOURCE_MUST_NOT_REAPPEAR', json.dumps(packet))
                    self.assertNotIn('BAD_REASON_MUST_NOT_REAPPEAR', json.dumps(packet))
                audit = json.loads((output / 'requests/input-audit-0001.json').read_text(encoding='utf-8'))
                self.assertEqual(audit['response_tool_validation'],
                                 {'status': 'invalid_request', 'error_kind': 'submission_schema'})
                self.assertNotIn('BAD_SOURCE_MUST_NOT_REAPPEAR', json.dumps(audit))

    def test_declaration_bound_counts_complete_json_at_2048_bytes(self):
        # Hand-calculated framing: 43 bytes around the ASCII padding value.
        prefix = {'source': 'pass', 'n_params': 0, 'rationale': '', 'prediction': {}}
        declaration = {'claims': [{'pad': 'x' * 2005}], 'prediction': {}}
        self.assertEqual(len(json.dumps(declaration, allow_nan=False).encode('utf-8')), 2048)
        accepted = CheckedCandidateAction(**prefix, claims=declaration['claims'])
        self.assertEqual(len(accepted.claims[0]['pad']), 2005)
        with self.assertRaises(ValidationError):
            CheckedCandidateAction(**prefix, claims=[{'pad': 'x' * 2006}])

    def test_action_rejects_coercion_oversize_and_extra_capabilities(self):
        base = {'source': 'pass', 'n_params': 0, 'rationale': '', 'claims': [{}], 'prediction': {}}
        invalid = [{'source': '测' * 5462}, {'source': ' '}, {'source': 123},
            {'n_params': True}, {'n_params': '1'}, {'n_params': 17}, {'n_params': -1},
            {'rationale': 'x' * 2001}, {'claims': []}, {'claims': [{}, {}, {}]},
            {'claims': ({},)}, {'claims': ['x']}, {'prediction': []},
            {'claims': [{'value': float('nan')}]}, {'claims': [{'pad': 'x' * 2048}]},
            {'root': '/'}, {'task_id': 'sealed'}, {'command': 'read_file'}]
        for change in invalid:
            with self.subTest(change=list(change)), self.assertRaises(ValidationError):
                CheckedCandidateAction(**{**base, **change})
        accepted = CheckedCandidateAction(**{**base, 'source': 'x' * 16384,
                                            'n_params': 16, 'rationale': 'x' * 2000})
        self.assertEqual(len(accepted.source.encode('utf-8')), 16384)
        # Incorrect semantics remain the controller's feedback, not an SDK gate.
        self.assertEqual(accepted.claims, [{}])


if __name__ == '__main__':
    unittest.main()
