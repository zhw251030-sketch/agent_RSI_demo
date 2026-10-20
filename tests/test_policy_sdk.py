"""Real SDK boundary for one policy update; model transport is always fake."""
import copy
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
    from jsonschema import Draft202012Validator
    from litellm.types.utils import ModelResponse
    from pydantic import ValidationError
    from rsi_eval.policy_agent import PolicyAction, PolicyStatePacketLLM, policy_tool, run_policy_session
    from rsi_eval.pilot_agent import (BoundedPilotLLM, POLICY_UPDATE_SYSTEM_PROMPT,
                                     create_conversation, run_session)
    from rsi_eval.pilot_budget import BudgetExceeded, BudgetLedger


class PolicyRecorder:
    def __init__(self):
        self.calls = []
        self.halted = False

    def state_packet(self):
        return {'version': 'synthetic-update-fixture', 'purpose': 'policy_update',
                'update_cases': [{'case_id': 'U-P'}, {'case_id': 'U-S'}],
                'rule_catalog': ['R'+str(i).zfill(2) for i in range(1, 9)]}

    def task_prompt(self):
        return json.dumps(self.state_packet())

    def submit_policy(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return {'status': 'synthetic_policy_recorded', 'candidate_executions': 0}

    def summary(self):
        return {'recorded_policies': len(self.calls), 'halted': self.halted, 'candidate_executions': 0}


@unittest.skipUnless(SDK_PRESENT, 'OpenHands SDK is not installed in this interpreter')
class PolicySDKTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    @staticmethod
    def arguments(**changes):
        return dict(rule_1='R01', rule_2='R02', rule_3='R03', rule_4='R04',
                    support_1='U-P', support_2='U-S', support_3='both', support_4='both',
                    rationale='Synthetic host-only explanation.', **changes)

    @staticmethod
    def response(arguments=None, *, tool='submit_policy', finish_reason='tool_calls', second=False):
        message = {'role': 'assistant', 'content': 'Synthetic offline policy response.'}
        if arguments is not None:
            call = {'id': 'synthetic-policy-call', 'type': 'function',
                    'function': {'name': tool, 'arguments': json.dumps(arguments)}}
            message['tool_calls'] = [call]
            if second:
                message['tool_calls'].append({**copy.deepcopy(call), 'id': 'second-policy-call'})
        return ModelResponse(id='synthetic-policy-response', model='minimax-m3',
            choices=[{'message': message, 'finish_reason': finish_reason}],
            usage={'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120})

    def bound(self, name):
        output = self.root/name
        output.mkdir()
        controller = PolicyRecorder()
        controller.output_dir = output
        ledger = BudgetLedger(output/'budget-ledger.json', session_ids=[name],
                              max_requests=1, max_requests_per_session=1)
        llm = PolicyStatePacketLLM(model='anthropic/minimax-m3',
            api_key='offline-placeholder-not-a-real-key', base_url='https://example.invalid',
            max_output_tokens=4096, num_retries=0, caching_prompt=False, api_mode='chat',
            stream=False, reasoning_effort='none', native_tool_calling=True,
            force_string_serializer=False, fallback_strategy=None, log_completions=False
        ).bind_pilot(ledger, name, output/'requests').bind_controller(controller)
        return controller, llm, ledger, output

    def test_flat_schema_and_strict_catalog_fields_exclude_source_capabilities(self):
        schema = PolicyAction.to_mcp_schema()
        self.assertEqual(set(schema['properties']), set(self.arguments()))
        self.assertEqual(set(schema['required']), set(self.arguments()))
        for field in schema['properties'].values():
            self.assertEqual(field['type'], 'string')
            self.assertFalse(set(field) & {'properties', 'items', 'anyOf', '$ref'})
        Draft202012Validator(schema).validate(self.arguments())
        self.assertEqual(PolicyAction.model_validate(self.arguments()).rule_1, 'R01')
        for change in [{'rule_1': 'R09'}, {'rule_1': True}, {'rule_1': ['R01']},
                       {'support_1': 'eval'}, {'support_1': 1}, {'rationale': 1},
                       {'rationale': 'x'*2001}, {'rationale': '\ud800'},
                       {'source': 'def solve(): pass'}, {'policy_text': 'answer'}, {'command': 'read_file'}]:
            with self.subTest(change=list(change)), self.assertRaises(ValidationError):
                PolicyAction.model_validate({**self.arguments(), **change})

    def test_one_update_uses_policy_tools_and_records_response_usage_events_without_task_execution(self):
        controller, llm, ledger, output = self.bound('one_update')
        arguments = {**self.arguments(), 'summary': 'SDK metadata', 'security_risk': 'LOW'}
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(arguments)) as fake, \
                patch('rsi_eval.executor.evaluate_candidate', side_effect=AssertionError('No evaluation')) as execute, \
                patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=AssertionError('No evaluation')) as diagnose:
            result = run_policy_session(controller, llm, 'one_update', output)
        execute.assert_not_called()
        diagnose.assert_not_called()
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(controller.calls, [self.arguments()])
        self.assertEqual(result['tools'], ['finish', 'submit_policy'])
        self.assertEqual(result['controller']['candidate_executions'], 0)
        self.assertEqual(ledger.summary()['known_total_tokens'], 120)
        request = json.loads((output/'requests/request-0001.request.json').read_text())
        self.assertEqual({t['function']['name'] for t in request['tools']}, {'submit_policy', 'finish'})
        self.assertIn(POLICY_UPDATE_SYSTEM_PROMPT, json.dumps(request['messages'][0], ensure_ascii=False)
                      .replace('\\n', '\n'))
        packet = json.loads(request['messages'][1]['content'])
        self.assertEqual(packet, controller.state_packet())
        self.assertNotIn('Synthetic host-only explanation', json.dumps(packet))
        audit = json.loads((output/'requests/input-audit-0001.json').read_text())
        self.assertEqual(audit['response_tool_validation'], {'status': 'valid_submission'})
        events = [json.loads(line) for line in (output/'events.jsonl').read_text().splitlines()]
        self.assertTrue(any(e.get('tool_name') == 'submit_policy' and e['type'] == 'ActionEvent' for e in events))
        self.assertTrue(any(e['type'] == 'ObservationEvent' for e in events))

    def test_policy_and_candidate_allowlists_are_separate_and_cannot_be_model_fields(self):
        self.assertEqual(BoundedPilotLLM._pilot_allowed_tools, frozenset({'submit_candidate', 'finish'}))
        self.assertEqual(PolicyStatePacketLLM._pilot_allowed_tools, frozenset({'submit_policy', 'finish'}))
        self.assertNotIn('_pilot_allowed_tools', PolicyStatePacketLLM.model_fields)
        c, llm, ledger, output = self.bound('wrong_purpose')
        with patch('openhands.sdk.llm.llm.litellm_completion') as fake:
            with self.assertRaises(ValueError):
                create_conversation(c, llm, 'wrong_purpose', output, tool_factory=policy_tool,
                                    max_iterations=1, purpose='candidate')
            with self.assertRaises(ValueError):
                create_conversation(c, llm, 'wrong_purpose', output, tool_factory=policy_tool,
                                    max_iterations=2, purpose='policy')
        fake.assert_not_called()
        self.assertEqual(ledger.summary()['request_count'], 0)

    def test_wrong_tool_and_multiple_calls_never_dispatch_policy(self):
        for name, tool, second in [('candidate_tool', 'submit_candidate', False),
                                   ('unknown_tool', 'read_file', False), ('multiple', 'submit_policy', True)]:
            with self.subTest(name=name):
                c, llm, ledger, output = self.bound(name)
                response = self.response(self.arguments(), tool=tool, second=second)
                with patch('openhands.sdk.llm.llm.litellm_completion', return_value=response) as fake:
                    result = run_policy_session(c, llm, name, output)
                self.assertEqual(fake.call_count, 1)
                self.assertEqual(c.calls, [])
                self.assertEqual(result['status'], 'error')
                self.assertIn('PilotResponseContractError', (result.get('cause_type'), result.get('model_error_type')))
                self.assertEqual(ledger.summary()['known_total_tokens'], 120)
                record = json.loads((output/'requests/request-0001.response.json').read_text())
                self.assertEqual(record['error_type'], 'PilotResponseContractError')

    def test_missing_tool_finish_and_unknown_usage_do_not_imply_policy_acceptance(self):
        cases = [('incomplete', None, 'tool_calls', 'submit_policy', True),
                 ('plain_stop', None, 'stop', 'submit_policy', False),
                 ('finish', {'message': 'Done.', 'summary': 'Done.', 'security_risk': 'LOW'},
                  'tool_calls', 'finish', False)]
        for name, arguments, reason, tool, malformed in cases:
            with self.subTest(name=name):
                c, llm, ledger, output = self.bound(name)
                with patch('openhands.sdk.llm.llm.litellm_completion',
                           return_value=self.response(arguments, tool=tool, finish_reason=reason)) as fake:
                    result = run_policy_session(c, llm, name, output)
                self.assertEqual(fake.call_count, 1)
                self.assertEqual(c.calls, [])
                self.assertEqual(result['status'], 'error' if malformed else 'completed')
                if malformed:
                    self.assertEqual(result['cause_type'], 'IncompleteToolResponseError')
                self.assertEqual(ledger.summary()['known_total_tokens'], 120)

    def test_unknown_usage_halts_ledger_and_prevents_any_second_transport(self):
        c, llm, ledger, output = self.bound('unknown_usage')
        response = self.response(self.arguments())
        response.usage = None
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=response) as fake:
            run_policy_session(c, llm, 'unknown_usage', output)
            with self.assertRaises(BudgetExceeded):
                llm._transport_call(messages=[], max_tokens=4096)
        self.assertEqual(fake.call_count, 1)
        self.assertTrue(ledger.summary()['halted'])
        self.assertEqual(ledger.summary()['usage_unknown_count'], 1)
        self.assertIsNone(ledger.summary()['actual_estimated_cost_cny'])

    def test_observer_and_sdk_reject_bad_rule_or_extra_fields_but_accept_metadata(self):
        cases = [('metadata', {'summary': 17, 'security_risk': None}, True),
                 ('invalid_rule', {'rule_1': 'R99'}, False), ('extra_code', {'source': 'pass'}, False)]
        for name, changes, accepted in cases:
            with self.subTest(name=name):
                c, llm, ledger, output = self.bound(name)
                response = self.response({**self.arguments(), **changes})
                with patch('openhands.sdk.llm.llm.litellm_completion', return_value=response) as fake:
                    run_policy_session(c, llm, name, output)
                self.assertEqual(fake.call_count, 1)
                self.assertEqual(len(c.calls), int(accepted))
                self.assertEqual(ledger.summary()['known_total_tokens'], 120)
                audit = json.loads((output/'requests/input-audit-0001.json').read_text())
                self.assertEqual(audit['response_tool_validation']['status'],
                                 'valid_submission' if accepted else 'invalid_request')

    def test_policy_storage_exception_marks_fatal_state_even_if_sdk_swallows_it(self):
        c, llm, ledger, output = self.bound('storage_failure')
        with patch('openhands.sdk.llm.llm.litellm_completion',
                   return_value=self.response(self.arguments())) as fake, \
                patch.object(c, 'submit_policy', side_effect=OSError('PRIVATE_STORAGE_BODY')):
            result = run_policy_session(c, llm, 'storage_failure', output)
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(result['status'], 'stopped')
        self.assertIsNone(result['model_error_type'])
        self.assertTrue(c.halted)
        failure = json.loads((output/'controller-error.json').read_text())
        self.assertEqual(failure, {'status': 'infrastructure_error',
            'error_kind': 'policy_executor_exception', 'error_type': 'OSError'})
        self.assertNotIn('PRIVATE_STORAGE_BODY', json.dumps(failure))
        self.assertEqual(ledger.summary()['known_total_tokens'], 120)

    def test_real_controller_freezes_policy_without_forwarding_rationale_or_evaluation_sources(self):
        from rsi_eval.policy_cases import load_update_bundle, load_evaluation_states
        from rsi_eval.revision_policy import (PolicyUpdateController, S0, freeze_policy,
                                              load_frozen_policy, render_policy)
        project = Path(__file__).resolve().parents[1]
        bundle = load_update_bundle(project)
        evaluation = load_evaluation_states(project)
        _, llm, ledger, output = self.bound('real_policy_controller')
        controller = PolicyUpdateController(bundle, S0, output)
        llm.bind_controller(controller)
        rationale = 'HOST_ONLY_SENTINEL def solve(state): return ["not a transferable answer"]'
        arguments = {**self.arguments(), 'rationale': rationale}
        with patch('openhands.sdk.llm.llm.litellm_completion',
                   return_value=self.response(arguments)) as fake, \
                patch('rsi_eval.executor.evaluate_candidate', side_effect=AssertionError('No evaluation')) as execute, \
                patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=AssertionError('No evaluation')) as diagnose:
            result = run_policy_session(controller, llm, 'real_policy_controller', output)
        fake.assert_called_once()
        execute.assert_not_called()
        diagnose.assert_not_called()
        self.assertEqual(result['controller']['status'], 'accepted')
        self.assertEqual(result['controller']['candidate_executions'], 0)
        self.assertFalse(controller.halted)
        self.assertEqual(ledger.summary()['usage_unknown_count'], 0)
        self.assertEqual(ledger.summary()['known_total_tokens'], 120)
        saved = json.loads((output/'policy-S1.json').read_text())
        submission = json.loads((output/'policy-submission.json').read_text())
        self.assertEqual(saved, controller.policy)
        self.assertEqual(submission['rationale'], rationale)
        self.assertNotIn('HOST_ONLY_SENTINEL', json.dumps(saved))
        frozen = freeze_policy(output, bundle, S0, 'request-0001')
        self.assertEqual(load_frozen_policy(output, bundle, S0), saved)
        self.assertEqual(frozen['request_id'], 'request-0001')
        rendered = render_policy(saved)
        self.assertEqual(set(rendered), {'version', 'rule_ids', 'instructions'})
        self.assertNotIn('HOST_ONLY_SENTINEL', json.dumps(rendered))
        self.assertNotIn('rule_support', rendered)
        request = json.loads((output/'requests/request-0001.request.json').read_text())
        packet = json.loads(request['messages'][1]['content'])
        self.assertEqual(packet, controller.state_packet())
        self.assertEqual([case['case_id'] for case in packet['experience_cases']], ['U-P', 'U-S'])
        request_text = json.dumps(request, ensure_ascii=False)
        self.assertNotIn('HOST_ONLY_SENTINEL', request_text)
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for child in value.values():
                    yield from strings(child)
            elif isinstance(value, list):
                for child in value:
                    yield from strings(child)
        visible_text = '\n'.join(strings(packet))
        for state in evaluation:
            self.assertNotIn(state['source'], visible_text)
            self.assertNotIn(state['record']['source_sha256'], request_text)
            self.assertNotIn(state['state_id'], [case['case_id'] for case in packet['experience_cases']])


if __name__ == '__main__':
    unittest.main()
