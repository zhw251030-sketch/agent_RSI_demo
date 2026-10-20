"""Real SDK boundaries with every provider completion replaced in process."""
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
    from rsi_eval.inference_policy_agent import (
        InferencePolicyAction, InferencePolicyStatePacketLLM,
        inference_policy_tool, run_inference_policy_session,
    )
    from rsi_eval.pilot_agent import create_conversation
    from rsi_eval.pilot_budget import BudgetExceeded, BudgetLedger
    from rsi_eval.revision_policy import validate_policy


class InferenceRecorder:
    """No evidence semantics: isolate SDK preservation and core-owned policy gates."""
    def __init__(self, output_dir, feedback=None):
        self.output_dir = output_dir
        self.calls = []
        self.policy = None
        self.halted = False
        self.feedback = copy.deepcopy(feedback)

    def state_packet(self):
        return {'version': 'inference-sdk-fixture', 'proposal': {'rules': ['R01', 'R02']},
                'inference_feedback': copy.deepcopy(self.feedback)}

    def task_prompt(self):
        return json.dumps(self.state_packet())

    def submit_policy(self, **values):
        self.calls.append(copy.deepcopy(values))
        try:
            self.policy = validate_policy({'version': 'revision-policy-v0.1',
                'rule_ids': [values[f'rule_{i}'] for i in range(1, 5)]})
        except ValueError:
            return {'status': 'invalid_request', 'error_kind': 'policy_structure'}
        return {'status': 'accepted', 'inferences_certified': False}

    def summary(self):
        return {'policies_recorded': len(self.calls), 'halted': self.halted,
                'candidate_executions': 0, 'policy_available': self.policy is not None}


@unittest.skipUnless(SDK_PRESENT, 'OpenHands SDK is not installed in this interpreter')
class InferencePolicySDKTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    @staticmethod
    def arguments(**changes):
        values = {f'rule_{i}': f'R0{i}' for i in range(1, 5)}
        values.update({f'{prefix}_{i}': '' for prefix in ('verdict', 'evidence')
                       for i in range(1, 5)})
        return {**values, 'notes': '', **changes}

    @staticmethod
    def response(arguments=None, *, tool='submit_policy', reason='tool_calls', second=False):
        message = {'role': 'assistant', 'content': 'Offline synthetic response.'}
        if arguments is not None:
            call = {'id': 'inference-call', 'type': 'function',
                    'function': {'name': tool, 'arguments': json.dumps(arguments)}}
            message['tool_calls'] = [call]
            if second:
                message['tool_calls'].append({**copy.deepcopy(call), 'id': 'second-call'})
        return ModelResponse(id='inference-response', model='minimax-m3',
            choices=[{'message': message, 'finish_reason': reason}],
            usage={'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120})

    def bound(self, name, feedback=None):
        output = self.root/name
        output.mkdir()
        controller = InferenceRecorder(output, feedback)
        ledger = BudgetLedger(output/'budget-ledger.json', session_ids=[name],
                              max_requests=1, max_requests_per_session=1)
        llm = InferencePolicyStatePacketLLM(model='anthropic/minimax-m3',
            api_key='offline-placeholder-not-a-real-key', base_url='https://example.invalid',
            max_output_tokens=4096, num_retries=0, caching_prompt=False, api_mode='chat',
            stream=False, reasoning_effort='none', native_tool_calling=True,
            force_string_serializer=False, fallback_strategy=None, log_completions=False,
        ).bind_pilot(ledger, name, output/'requests').bind_controller(controller)
        return controller, llm, ledger, output

    def test_schema_advertises_thirteen_flat_strings_but_only_rules_are_required(self):
        schema = InferencePolicyAction.to_mcp_schema()
        self.assertEqual(set(schema['properties']), set(self.arguments()))
        self.assertEqual(set(schema['required']), {f'rule_{i}' for i in range(1, 5)})
        self.assertIs(schema['additionalProperties'], False)
        for field in schema['properties'].values():
            self.assertEqual(field['type'], 'string')
            self.assertFalse(set(field) & {'maxLength', 'properties', 'items', 'anyOf', '$ref'})
        Draft202012Validator(schema).validate(self.arguments())

    def test_auxiliary_values_are_soft_and_defaults_preserve_rule_only_submission(self):
        action = InferencePolicyAction.model_validate({f'rule_{i}': f'R0{i}' for i in range(1, 5)})
        self.assertEqual(action.notes, '')
        for change in ({'verdict_1': 'invented_label'}, {'verdict_1': {'wrong': ['type']}},
                       {'evidence_2': None}, {'notes': [1, False, 'kept']}):
            value = InferencePolicyAction.model_validate(self.arguments(**change))
            for key, expected in change.items():
                self.assertEqual(getattr(value, key), expected)

    def test_whole_submission_cap_is_65536_utf8_bytes_not_16384(self):
        values = self.arguments(notes='x'*20000)
        self.assertEqual(InferencePolicyAction.model_validate(values).notes, values['notes'])
        empty_size = len(json.dumps(self.arguments(), ensure_ascii=False, allow_nan=False,
                                    sort_keys=True, separators=(',', ':')).encode('utf-8'))
        exact = self.arguments(notes='x'*(65536-empty_size))
        self.assertEqual(InferencePolicyAction.model_validate(exact).notes, exact['notes'])
        for change in ({'notes': exact['notes']+'x'}, {'notes': '\u6c49'*22000},
                       {'notes': '\ud800'}, {'notes': float('nan')},
                       {'evidence_1': {'value': float('inf')}}):
            with self.subTest(change=list(change)), self.assertRaises(ValidationError):
                InferencePolicyAction.model_validate(self.arguments(**change))

    def test_hard_rule_types_and_extra_fields_reject_before_controller(self):
        for change in ({'rule_1': 'R99'}, {'rule_1': ['R01']}, {'rule_1': 1},
                       {'source': 'pass'}, {'rationale': 'Not a business field'}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                InferencePolicyAction.model_validate(self.arguments(**change))

    def test_long_unicode_notes_and_wrong_auxiliary_values_reach_controller_unchanged(self):
        for name, changes in [('long_notes', {'notes': 'a'*280+'\u6c49'*2000}),
                              ('wrong_label', {'verdict_1': 'not_a_label'}),
                              ('wrong_type', {'verdict_3': {'x': [1, False]}, 'evidence_2': 42}),
                              ('long_soft_notes', {'notes': 'x'*9000})]:
            with self.subTest(name=name):
                c, llm, ledger, output = self.bound(name)
                args = self.arguments(**changes)
                with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(args)) as fake, \
                        patch('rsi_eval.executor.evaluate_candidate', side_effect=AssertionError('No execution')) as execute:
                    result = run_inference_policy_session(c, llm, name, output)
                self.assertEqual(fake.call_count, 1)
                execute.assert_not_called()
                self.assertEqual(c.calls, [args])
                self.assertIsNotNone(c.policy)
                self.assertFalse(c.halted)
                self.assertEqual(result['tools'], ['finish', 'submit_policy'])
                self.assertEqual(ledger.summary()['known_total_tokens'], 120)
                audit = json.loads((output/'requests/input-audit-0001.json').read_text())
                self.assertEqual(audit['response_tool_validation'], {'status': 'valid_submission'})
                raw = json.loads((output/'requests/request-0001.response.json').read_text())
                self.assertEqual(json.loads(raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']), args)

    def test_sdk_metadata_is_excluded_from_business_fields(self):
        c, llm, ledger, output = self.bound('metadata')
        args = self.arguments(summary=17, security_risk=None)
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(args)):
            run_inference_policy_session(c, llm, 'metadata', output)
        self.assertEqual(c.calls, [self.arguments()])

    def test_duplicate_rules_are_core_rejection_without_infrastructure_halt(self):
        c, llm, ledger, output = self.bound('duplicate')
        args = self.arguments(rule_2='R01')
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(args)):
            run_inference_policy_session(c, llm, 'duplicate', output)
        self.assertEqual(c.calls, [args])
        self.assertIsNone(c.policy)
        self.assertFalse(c.halted)
        self.assertEqual(ledger.summary()['known_total_tokens'], 120)

    def test_real_core_archives_soft_invalid_auxiliary_values_and_freezes_legal_policy(self):
        from rsi_eval.inference_cases import load_inference_bundle
        from rsi_eval.inference_policy import InferencePolicyController, freeze_policy, load_frozen_policy
        from rsi_eval.revision_policy import S0
        bundle = load_inference_bundle(Path(__file__).resolve().parents[1])
        _, llm, ledger, output = self.bound('real_core')
        c = InferencePolicyController(bundle, S0, output, pair_id='same_pair')
        llm.bind_controller(c)
        args = self.arguments(verdict_1={'wrong': ['type']}, verdict_2='invented',
                              evidence_3=None, notes='\u6c49'*3000)
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(args)):
            result = run_inference_policy_session(c, llm, 'real_core', output)
        self.assertEqual(result['controller']['status'], 'accepted')
        self.assertFalse(c.halted)
        self.assertIsNotNone(c.policy)
        self.assertEqual(c.checks['notes_status'], 'oversize')
        self.assertTrue(all(row['status'] == 'invalid' for row in c.checks['assessments']))
        # SDK 1.55.1 drops top-level nulls before Action defaults are applied.
        # The raw response must preserve null; the core receives its default.
        normalized = {**args, 'evidence_3': ''}
        self.assertEqual(json.loads((output/'submission.json').read_bytes()), normalized)
        raw = json.loads((output/'requests/request-0001.response.json').read_bytes())
        self.assertEqual(json.loads(raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']), args)
        self.assertEqual(set(c.policy), {'version', 'rule_ids'})
        freeze_policy(output, bundle, S0, 'request-0001', pair_id='same_pair')
        self.assertEqual(load_frozen_policy(output, bundle, S0, pair_id='same_pair'), c.policy)
        self.assertEqual(ledger.summary()['usage_unknown_count'], 0)

    def test_real_core_duplicate_rejection_remains_a_known_missing_policy(self):
        from rsi_eval.inference_cases import load_inference_bundle
        from rsi_eval.inference_policy import InferencePolicyController
        from rsi_eval.revision_policy import S0
        bundle = load_inference_bundle(Path(__file__).resolve().parents[1])
        _, llm, ledger, output = self.bound('real_duplicate')
        c = InferencePolicyController(bundle, S0, output, pair_id='same_pair')
        llm.bind_controller(c)
        with patch('openhands.sdk.llm.llm.litellm_completion',
                   return_value=self.response(self.arguments(rule_2='R01'))):
            result = run_inference_policy_session(c, llm, 'real_duplicate', output)
        self.assertEqual(result['controller']['status'], 'rejected')
        self.assertFalse(c.halted)
        self.assertIsNone(c.policy)
        self.assertTrue((output/'rejection.json').is_file())
        self.assertFalse((output/'freeze.json').exists())
        self.assertEqual(ledger.summary()['known_total_tokens'], 120)

    def test_observer_and_sdk_reject_unknown_fields_without_rewriting_response(self):
        for name, change in [('extra', {'unexpected': 'original'}), ('bad_rule', {'rule_1': 'R99'}),
                             ('too_large', {'notes': 'x'*65536})]:
            c, llm, ledger, output = self.bound(name)
            args = self.arguments(**change)
            with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(args)):
                run_inference_policy_session(c, llm, name, output)
            self.assertEqual(c.calls, [])
            self.assertIsNone(c.policy)
            audit = json.loads((output/'requests/input-audit-0001.json').read_text())
            self.assertEqual(audit['response_tool_validation']['status'], 'invalid_request')
            raw = json.loads((output/'requests/request-0001.response.json').read_text())
            self.assertEqual(json.loads(raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']), args)

    def test_actual_review_requests_differ_only_in_inference_feedback(self):
        payloads = []
        for name, feedback in [('self_review', None), ('checked_review', {'status': 'unknown'})]:
            c, llm, ledger, output = self.bound(name, feedback)
            with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(self.arguments())):
                run_inference_policy_session(c, llm, name, output)
            payload = json.loads((output/'requests/request-0001.request.json').read_text())
            packet = json.loads(payload['messages'][1]['content'])
            self.assertEqual(packet.pop('inference_feedback'), feedback)
            payload['messages'][1]['content'] = json.dumps(packet, sort_keys=True, separators=(',', ':'))
            payloads.append(payload)
        self.assertEqual(*payloads)

    def test_disallowed_tools_and_multiple_calls_never_dispatch(self):
        for name, tool, second in [('candidate', 'submit_candidate', False),
                                   ('unknown', 'read_file', False), ('multiple', 'submit_policy', True)]:
            c, llm, ledger, output = self.bound(name)
            with patch('openhands.sdk.llm.llm.litellm_completion',
                       return_value=self.response(self.arguments(), tool=tool, second=second)):
                result = run_inference_policy_session(c, llm, name, output)
            self.assertEqual(c.calls, [])
            self.assertIn('PilotResponseContractError', (result.get('cause_type'), result.get('model_error_type')))

    def test_unknown_usage_blocks_another_transport(self):
        c, llm, ledger, output = self.bound('unknown_usage')
        response = self.response(self.arguments())
        response.usage = None
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=response) as fake:
            run_inference_policy_session(c, llm, 'unknown_usage', output)
            with self.assertRaises(BudgetExceeded):
                llm._transport_call(messages=[], max_tokens=4096)
        self.assertEqual(fake.call_count, 1)
        self.assertTrue(ledger.summary()['halted'])
        self.assertEqual(ledger.summary()['usage_unknown_count'], 1)

    def test_storage_failure_halts_controller_without_preserving_private_error_text(self):
        c, llm, ledger, output = self.bound('storage_failure')
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(self.arguments())), \
                patch.object(c, 'submit_policy', side_effect=OSError('PRIVATE_STORAGE_DETAIL')):
            run_inference_policy_session(c, llm, 'storage_failure', output)
        self.assertTrue(c.halted)
        saved = json.loads((output/'controller-error.json').read_text())
        self.assertEqual(saved, {'status': 'infrastructure_error',
            'error_kind': 'inference_policy_executor_exception', 'error_type': 'OSError'})
        self.assertNotIn('PRIVATE_STORAGE_DETAIL', json.dumps(saved))

    def test_policy_purpose_enforces_one_iteration(self):
        c, llm, ledger, output = self.bound('purpose')
        with patch('openhands.sdk.llm.llm.litellm_completion') as fake:
            for purpose, iterations in [('policy', 2), ('candidate', 1)]:
                with self.assertRaises(ValueError):
                    create_conversation(c, llm, 'purpose', output,
                        tool_factory=inference_policy_tool, max_iterations=iterations, purpose=purpose)
        fake.assert_not_called()
        self.assertEqual(ledger.summary()['request_count'], 0)


if __name__ == '__main__':
    unittest.main()
