"""Actual SDK action boundaries; all provider transport is replaced locally."""
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
    from rsi_eval.grounded_policy_agent import (
        GroundedPolicyAction, GroundedPolicyStatePacketLLM,
        grounded_policy_tool, run_grounded_policy_session,
    )
    from rsi_eval.pilot_agent import create_conversation
    from rsi_eval.pilot_budget import BudgetExceeded, BudgetLedger


class GroundedRecorder:
    def __init__(self, output_dir, feedback=None):
        self.output_dir = output_dir
        self.calls = []
        self.policy = None
        self.halted = False
        self.feedback = copy.deepcopy(feedback)

    def state_packet(self):
        return {'version': 'grounded-sdk-fixture', 'shared_proposal': {'rules': ['R01', 'R02']},
                'premise_feedback': copy.deepcopy(self.feedback)}

    def task_prompt(self):
        return json.dumps(self.state_packet())

    def submit_policy(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        self.policy = {'version': 'revision-policy-v0.1',
                       'rule_ids': [kwargs['rule_'+str(i)] for i in range(1, 5)]}
        return {'status': 'accepted', 'premises_all_supported': False}

    def summary(self):
        return {'policies_recorded': len(self.calls), 'halted': self.halted,
                'candidate_executions': 0}


@unittest.skipUnless(SDK_PRESENT, 'OpenHands SDK is not installed in this interpreter')
class GroundedPolicySDKTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    @staticmethod
    def arguments(**changes):
        values = {}
        for i in range(1, 5):
            values.update({f'rule_{i}': f'R0{i}', f'parent_{i}': False,
                f'quote_{i}': 'This is a deliberately incorrect catalog quote.',
                f'support_{i}': 'F1' if i % 2 else 'F2',
                f'hypothesis_{i}': 'A hypothesis, not a verified explanation.',
                f'edit_{i}': 'Inspect the stated failure before selecting an edit.'})
        for i in (1, 2):
            values.update({f'fact_{i}_id': f'fixture-fact-{i}', f'fact_{i}_value': '999',
                           f'fact_{i}_scope': 'deliberately_wrong_scope'})
        return {**values, **changes}

    @staticmethod
    def response(arguments=None, *, tool='submit_policy', reason='tool_calls', second=False):
        message = {'role': 'assistant', 'content': 'Offline synthetic response.'}
        if arguments is not None:
            call = {'id': 'grounded-call', 'type': 'function',
                    'function': {'name': tool, 'arguments': json.dumps(arguments)}}
            message['tool_calls'] = [call]
            if second:
                message['tool_calls'].append({**copy.deepcopy(call), 'id': 'second-call'})
        return ModelResponse(id='grounded-response', model='minimax-m3',
            choices=[{'message': message, 'finish_reason': reason}],
            usage={'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120})

    def bound(self, name, feedback=None):
        output = self.root/name
        output.mkdir()
        controller = GroundedRecorder(output, feedback)
        ledger = BudgetLedger(output/'budget-ledger.json', session_ids=[name],
                              max_requests=1, max_requests_per_session=1)
        llm = GroundedPolicyStatePacketLLM(model='anthropic/minimax-m3',
            api_key='offline-placeholder-not-a-real-key', base_url='https://example.invalid',
            max_output_tokens=4096, num_retries=0, caching_prompt=False, api_mode='chat',
            stream=False, reasoning_effort='none', native_tool_calling=True,
            force_string_serializer=False, fallback_strategy=None, log_completions=False,
        ).bind_pilot(ledger, name, output/'requests').bind_controller(controller)
        return controller, llm, ledger, output

    def test_schema_is_closed_flat_thirty_fields_with_all_bounds_preserved(self):
        schema = GroundedPolicyAction.to_mcp_schema()
        self.assertEqual(len(schema['properties']), 30)
        self.assertEqual(set(schema['properties']), set(self.arguments()))
        self.assertEqual(set(schema['required']), set(self.arguments()))
        self.assertIs(schema['additionalProperties'], False)
        for name, value in schema['properties'].items():
            self.assertEqual(value['type'], 'boolean' if name.startswith('parent_') else 'string')
            self.assertFalse(set(value) & {'properties', 'items', 'anyOf', '$ref'})
        for prefix, limit in [('quote_', 1000), ('fact_1_id', 80), ('fact_2_id', 80),
                              ('fact_1_value', 160), ('fact_2_value', 160),
                              ('fact_1_scope', 160), ('fact_2_scope', 160),
                              ('hypothesis_', 240), ('edit_', 180)]:
            for name in schema['properties']:
                if name.startswith(prefix):
                    self.assertEqual(schema['properties'][name]['maxLength'], limit)
        Draft202012Validator(schema).validate(self.arguments())

    def test_strict_schema_rejects_coercion_unknown_fields_bounds_and_invalid_utf8(self):
        for change in [{'parent_1': 1}, {'parent_1': 'false'}, {'rule_1': 'R99'},
                       {'rule_1': ['R01']}, {'fact_1_id': 1}, {'fact_1_id': 'x'*81},
                       {'fact_1_value': 1.0}, {'fact_1_value': 'x'*161},
                       {'fact_1_scope': 'x'*161}, {'quote_1': 'x'*1001},
                       {'quote_1': '\ud800'}, {'support_1': 'U-P'},
                       {'hypothesis_1': 'x'*241}, {'edit_1': 'x'*181},
                       {'rationale': 'Forbidden legacy field'}, {'source': 'pass'},
                       {'command': 'read_file'}]:
            with self.subTest(change=list(change)), self.assertRaises(ValidationError):
                GroundedPolicyAction.model_validate(self.arguments(**change))
        for field in self.arguments():
            missing = self.arguments()
            del missing[field]
            with self.subTest(missing=field), self.assertRaises(ValidationError):
                GroundedPolicyAction.model_validate(missing)

    def test_non_ascii_aggregate_uses_exact_core_canonical_business_field_limit(self):
        values = self.arguments()
        for i in range(1, 5):
            values[f'quote_{i}'] = '\u6c49'*1000
            values[f'hypothesis_{i}'] = '\u6c49'*240
            values[f'edit_{i}'] = '\u6c49'*180
        self.assertGreater(len(json.dumps(values, ensure_ascii=False, sort_keys=True,
                                         separators=(',', ':')).encode('utf-8')), 16384)
        with self.assertRaises(ValidationError):
            GroundedPolicyAction.model_validate(values)

    def test_real_controller_archives_false_premises_and_freezes_only_rule_ids(self):
        from rsi_eval.grounded_policy import GroundedPolicyController, freeze_policy, load_frozen_policy
        from rsi_eval.policy_cases import load_update_bundle
        from rsi_eval.revision_policy import S0
        bundle = load_update_bundle(Path(__file__).resolve().parents[1])
        _, llm, ledger, output = self.bound('real_grounded')
        controller = GroundedPolicyController(bundle, S0, output, pair_id='same_pair')
        llm.bind_controller(controller)
        arguments = self.arguments()
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(arguments)), \
                patch('rsi_eval.executor.evaluate_candidate', side_effect=AssertionError('No evaluation')):
            result = run_grounded_policy_session(controller, llm, 'real_grounded', output)
        self.assertEqual(result['controller']['status'], 'accepted')
        self.assertFalse(controller.halted)
        self.assertFalse(controller.checks['all_checked_pass'])
        self.assertEqual(json.loads((output/'submission.json').read_text()), arguments)
        policy = json.loads((output/'policy.json').read_text())
        self.assertEqual(set(policy), {'version', 'rule_ids'})
        self.assertEqual(ledger.summary()['usage_unknown_count'], 0)
        freeze_policy(output, bundle, S0, 'request-0001', pair_id='same_pair')
        self.assertEqual(load_frozen_policy(output, bundle, S0, pair_id='same_pair'), policy)

    def test_semantically_false_premises_reach_controller_without_execution_or_gate(self):
        controller, llm, ledger, output = self.bound('false_premises')
        args = self.arguments(summary=17, security_risk=None)
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(args)) as fake, \
                patch('rsi_eval.executor.evaluate_candidate', side_effect=AssertionError('No evaluation')) as execute, \
                patch('rsi_eval.diagnostic_controller.evaluate_candidate', side_effect=AssertionError('No evaluation')) as diagnose:
            result = run_grounded_policy_session(controller, llm, 'false_premises', output)
        self.assertEqual(fake.call_count, 1)
        execute.assert_not_called()
        diagnose.assert_not_called()
        self.assertEqual(controller.calls, [self.arguments()])
        self.assertFalse(controller.halted)
        self.assertIsNotNone(controller.policy)
        self.assertEqual(result['tools'], ['finish', 'submit_policy'])
        self.assertEqual(ledger.summary()['known_total_tokens'], 120)
        audit = json.loads((output/'requests/input-audit-0001.json').read_text())
        self.assertEqual(audit['response_tool_validation'], {'status': 'valid_submission'})

    def test_actual_review_requests_differ_only_in_premise_feedback(self):
        payloads = []
        for name, feedback in [('hidden', None), ('checked', {'status': 'contradicted'})]:
            controller, llm, ledger, output = self.bound(name, feedback)
            with patch('openhands.sdk.llm.llm.litellm_completion',
                       return_value=self.response(self.arguments())):
                run_grounded_policy_session(controller, llm, name, output)
            payload = json.loads((output/'requests/request-0001.request.json').read_text())
            packet = json.loads(payload['messages'][1]['content'])
            self.assertEqual(packet['premise_feedback'], feedback)
            del packet['premise_feedback']
            payload['messages'][1]['content'] = json.dumps(packet, sort_keys=True, separators=(',', ':'))
            payloads.append(payload)
        self.assertEqual(payloads[0], payloads[1])

    def test_observer_and_sdk_reject_schema_errors_without_rewriting_response(self):
        for name, changes in [('extra', {'rationale': 'old contract'}),
                              ('bad_rule', {'rule_1': 'R99'}),
                              ('oversized_quote', {'quote_1': 'x'*1001})]:
            with self.subTest(name=name):
                c, llm, ledger, output = self.bound(name)
                args = self.arguments(**changes)
                with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(args)):
                    run_grounded_policy_session(c, llm, name, output)
                self.assertEqual(c.calls, [])
                audit = json.loads((output/'requests/input-audit-0001.json').read_text())
                self.assertEqual(audit['response_tool_validation']['status'], 'invalid_request')
                record = json.loads((output/'requests/request-0001.response.json').read_text())
                received = json.loads(record['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
                self.assertEqual(received, args)
                self.assertEqual(ledger.summary()['known_total_tokens'], 120)

    def test_wrong_tool_and_multiple_calls_never_dispatch(self):
        for name, tool, second in [('candidate', 'submit_candidate', False),
                                   ('unknown', 'read_file', False), ('multiple', 'submit_policy', True)]:
            with self.subTest(name=name):
                c, llm, ledger, output = self.bound(name)
                with patch('openhands.sdk.llm.llm.litellm_completion',
                           return_value=self.response(self.arguments(), tool=tool, second=second)):
                    result = run_grounded_policy_session(c, llm, name, output)
                self.assertEqual(c.calls, [])
                self.assertIn('PilotResponseContractError', (result.get('cause_type'), result.get('model_error_type')))
                self.assertEqual(ledger.summary()['known_total_tokens'], 120)

    def test_incomplete_stop_and_finish_are_not_policy_submissions(self):
        for name, args, tool, reason in [('incomplete', None, 'submit_policy', 'tool_calls'),
            ('plain_stop', None, 'submit_policy', 'stop'),
            ('finish', {'message': 'Done.', 'summary': 'Done.', 'security_risk': 'LOW'}, 'finish', 'tool_calls')]:
            with self.subTest(name=name):
                c, llm, ledger, output = self.bound(name)
                with patch('openhands.sdk.llm.llm.litellm_completion',
                           return_value=self.response(args, tool=tool, reason=reason)):
                    result = run_grounded_policy_session(c, llm, name, output)
                self.assertIsNone(c.policy)
                self.assertEqual(c.calls, [])
                if name == 'incomplete':
                    self.assertEqual(result.get('cause_type'), 'IncompleteToolResponseError')

    def test_unknown_usage_blocks_another_transport_even_after_submission(self):
        c, llm, ledger, output = self.bound('unknown_usage')
        response = self.response(self.arguments())
        response.usage = None
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=response) as fake:
            run_grounded_policy_session(c, llm, 'unknown_usage', output)
            with self.assertRaises(BudgetExceeded):
                llm._transport_call(messages=[], max_tokens=4096)
        self.assertEqual(fake.call_count, 1)
        self.assertTrue(ledger.summary()['halted'])
        self.assertEqual(ledger.summary()['usage_unknown_count'], 1)

    def test_executor_storage_failure_marks_fatal_state_without_private_text(self):
        c, llm, ledger, output = self.bound('storage_failure')
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(self.arguments())), \
                patch.object(c, 'submit_policy', side_effect=OSError('PRIVATE_STORAGE_DETAIL')):
            result = run_grounded_policy_session(c, llm, 'storage_failure', output)
        self.assertTrue(c.halted)
        self.assertEqual(result['status'], 'stopped')
        failure = json.loads((output/'controller-error.json').read_text())
        self.assertEqual(failure, {'status': 'infrastructure_error',
            'error_kind': 'grounded_policy_executor_exception', 'error_type': 'OSError'})
        self.assertNotIn('PRIVATE_STORAGE_DETAIL', json.dumps(failure))

    def test_policy_purpose_remains_single_iteration_and_rejects_candidate_purpose(self):
        c, llm, ledger, output = self.bound('purpose')
        with patch('openhands.sdk.llm.llm.litellm_completion') as fake:
            for purpose, iterations in [('policy', 2), ('candidate', 1)]:
                with self.assertRaises(ValueError):
                    create_conversation(c, llm, 'purpose', output,
                        tool_factory=grounded_policy_tool, max_iterations=iterations, purpose=purpose)
        fake.assert_not_called()
        self.assertEqual(ledger.summary()['request_count'], 0)


if __name__ == '__main__':
    unittest.main()
