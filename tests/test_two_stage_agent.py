"""Real SDK boundaries with every provider call replaced by an offline response."""
import copy
import importlib.util
import json
import logging
from pathlib import Path
import tempfile
import unittest
import warnings
from unittest.mock import patch

try:
    SDK_PRESENT = importlib.util.find_spec('openhands.sdk') is not None
except ModuleNotFoundError:
    SDK_PRESENT = False

if SDK_PRESENT:
    from jsonschema import Draft202012Validator
    from litellm.types.utils import ModelResponse
    from pydantic import ValidationError
    from rsi_eval.pilot_budget import BudgetExceeded, BudgetLedger
    from rsi_eval.two_stage_agent import (
        ProbeAction, RevisionAction, ProbeStatePacketLLM, RevisionStatePacketLLM,
        run_two_stage_session, PROBE_SYSTEM_PROMPT, REVISION_SYSTEM_PROMPT,
    )


class Recorder:
    def __init__(self, output, feedback=None):
        self.output_dir = output
        self.feedback = copy.deepcopy(feedback)
        self.calls = []
        self.halted = False

    def task_packet(self):
        return {'version': 'two-stage-sdk-fixture', 'pair_id': 'same-pair',
                'source': 'def solve(): return []',
                'registration': {'probe_id': 'P1', 'target_id': 'T1'},
                'probe_feedback': copy.deepcopy(self.feedback)}

    def task_prompt(self):
        return json.dumps(self.task_packet())

    def submit_probe(self, session_id, probe_id, target_id, auxiliary):
        self.calls.append({'session_id': session_id, 'probe_id': probe_id,
                           'target_id': target_id, 'auxiliary': copy.deepcopy(auxiliary)})
        return {'status': 'registered', 'candidate_executions': 0}

    def submit(self, session_id, source, n_params, rationale, auxiliary):
        self.calls.append({'session_id': session_id, 'source': source,
                           'n_params': n_params, 'rationale': rationale,
                           'auxiliary': copy.deepcopy(auxiliary)})
        return {'status': 'recorded', 'candidate_executions': 0}

    def summary(self):
        return {'submissions': len(self.calls), 'halted': self.halted,
                'candidate_executions': 0}


@unittest.skipUnless(SDK_PRESENT, 'OpenHands SDK is not installed in this interpreter')
class TwoStageSDKTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        previous_disable = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, previous_disable)
        warning_context = warnings.catch_warnings()
        warning_context.__enter__()
        warnings.simplefilter('ignore')
        self.addCleanup(warning_context.__exit__, None, None, None)

    @staticmethod
    def arguments(stage, **changes):
        args = ({'probe_id': 'P1', 'target_id': 'T1', 'auxiliary': {}}
                if stage == 'probe' else {'source': 'def solve(): return []',
                    'n_params': 0, 'rationale': 'One scoped revision.', 'auxiliary': {}})
        return {**args, **changes}

    @staticmethod
    def response(args=None, *, tool='submit_probe', reason='tool_calls', second=False):
        message = {'role': 'assistant', 'content': 'Offline fixture.'}
        if args is not None:
            call = {'id': 'call-1', 'type': 'function',
                    'function': {'name': tool, 'arguments': json.dumps(args)}}
            message['tool_calls'] = [call]
            if second:
                message['tool_calls'].append({**copy.deepcopy(call), 'id': 'call-2'})
        return ModelResponse(id='response-fixture', model='minimax-m3',
            choices=[{'message': message, 'finish_reason': reason}],
            usage={'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120})

    def bound(self, name, stage, feedback=None, **budgets):
        output = self.root/name
        output.mkdir()
        controller = Recorder(output, feedback)
        ledger = BudgetLedger(output/'budget-ledger.json', session_ids=[name],
            max_requests=1, max_requests_per_session=1, **budgets)
        cls = ProbeStatePacketLLM if stage == 'probe' else RevisionStatePacketLLM
        llm = cls(model='anthropic/minimax-m3', api_key='offline-placeholder',
            base_url='https://example.invalid', max_output_tokens=4096,
            num_retries=0, caching_prompt=False, api_mode='chat', stream=False,
            reasoning_effort='none', native_tool_calling=True,
            force_string_serializer=False, fallback_strategy=None,
            log_completions=False,
        ).bind_controller(controller).bind_pilot(ledger, name, output/'requests')
        return controller, llm, ledger, output

    def run_mock(self, name, stage, args=None, **response_options):
        c, llm, ledger, output = self.bound(name, stage)
        response_options.setdefault('tool', 'submit_probe' if stage == 'probe' else 'submit_candidate')
        with patch('openhands.sdk.llm.llm.litellm_completion',
                   return_value=self.response(args, **response_options)) as provider:
            result = run_two_stage_session(c, llm, name, output, stage=stage)
        self.assertEqual(provider.call_count, 1)
        return c, llm, ledger, output, result

    def test_schemas_require_only_business_identity_and_keep_auxiliary_semantics_soft(self):
        for stage, action in [('probe', ProbeAction), ('revision', RevisionAction)]:
            schema = action.to_mcp_schema()
            self.assertEqual(set(schema['properties']), set(self.arguments(stage)))
            self.assertIs(schema['additionalProperties'], False)
            self.assertNotIn('session_id', schema['properties'])
            self.assertNotIn('auxiliary', schema['required'])
            Draft202012Validator(schema).validate(self.arguments(stage))
            auxiliary = {'expected': {'wrong': [None, True, 9]}, 'reason': 'x'*9000}
            self.assertEqual(action.model_validate(self.arguments(stage, auxiliary=auxiliary)).auxiliary,
                             auxiliary)

    def test_required_fields_and_source_bounds_reject_unsafe_structure(self):
        for change in [{'probe_id': 1}, {'target_id': ''}, {'target_id': ['T1']},
                       {'session_id': 'injected'}, {'source': 'pass'}, {'auxiliary': []}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                ProbeAction.model_validate(self.arguments('probe', **change))
        for change in [{'source': ' '}, {'source': '\u6c49'*5462}, {'source': '\ud800'},
                       {'n_params': True}, {'n_params': 17}, {'rationale': 7},
                       {'rationale': 'x'*4001}, {'task_id': 'sealed'}]:
            with self.subTest(change=list(change)), self.assertRaises(ValidationError):
                RevisionAction.model_validate(self.arguments('revision', **change))
        self.assertEqual(len(RevisionAction.model_validate(
            self.arguments('revision', source='x'*16384)).source), 16384)

    def test_auxiliary_nonfinite_or_oversized_json_is_rejected_without_semantic_coercion(self):
        for action, stage in [(ProbeAction, 'probe'), (RevisionAction, 'revision')]:
            for auxiliary in [{'x': float('nan')}, {'x': float('inf')},
                              {'x': '\ud800'}, {'x': 'x'*65536}]:
                with self.subTest(action=stage, key=list(auxiliary)), self.assertRaises(ValidationError):
                    action.model_validate(self.arguments(stage, auxiliary=auxiliary))

    def test_each_stage_makes_one_real_sdk_tool_roundtrip_with_trusted_session(self):
        for stage in ('probe', 'revision'):
            name = 'roundtrip_'+stage
            args = self.arguments(stage, auxiliary={'prediction': 'malformed-but-archived'})
            c, llm, ledger, output, result = self.run_mock(name, stage, args)
            self.assertEqual(c.calls, [{'session_id': name, **args}])
            self.assertFalse(c.halted)
            tool = 'submit_probe' if stage == 'probe' else 'submit_candidate'
            self.assertEqual(result['tools'], ['finish', tool])
            self.assertEqual(result['controller']['candidate_executions'], 0)
            self.assertEqual(ledger.summary()['known_total_tokens'], 120)
            payload = json.loads((output/'requests/request-0001.request.json').read_text())
            self.assertEqual(json.loads(payload['messages'][1]['content']), c.task_packet())
            prompt = PROBE_SYSTEM_PROMPT if stage == 'probe' else REVISION_SYSTEM_PROMPT
            system_content = payload['messages'][0]['content']
            system_text = (system_content if isinstance(system_content, str) else
                           ''.join(block['text'] for block in system_content if block['type'] == 'text'))
            self.assertIn(prompt, system_text)
            self.assertNotIn('three candidate submissions', json.dumps(payload))
            self.assertNotIn('submit_policy', json.dumps(payload))
            audit = json.loads((output/'requests/input-audit-0001.json').read_text())
            self.assertEqual(audit['response_tool_validation']['status'], 'valid_submission')

    def test_sdk_metadata_and_top_level_null_preserve_raw_response_separately(self):
        args = self.arguments('probe', auxiliary=None, summary=42, security_risk=None)
        c, _, _, output, _ = self.run_mock('metadata', 'probe', args)
        self.assertEqual(c.calls, [{'session_id': 'metadata', **self.arguments('probe')}])
        raw = json.loads((output/'requests/request-0001.response.json').read_text())
        self.assertEqual(json.loads(raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']), args)
        normalized = json.loads((output/'sdk-submission.json').read_text())
        self.assertEqual(normalized, {'stage': 'probe', 'tool': 'submit_probe',
            'session_id': 'metadata', 'business': self.arguments('probe')})

    def test_sdk_normalized_submission_is_written_before_controller_dispatch(self):
        for stage in ('probe', 'revision'):
            name = 'before_'+stage
            c, llm, _, output = self.bound(name, stage)
            tool = 'submit_probe' if stage == 'probe' else 'submit_candidate'
            method = 'submit_probe' if stage == 'probe' else 'submit'
            original = getattr(c, method)
            args = self.arguments(stage, auxiliary={'prediction': {'invalid': True}})
            def observe(*values):
                stored = json.loads((output/'sdk-submission.json').read_text())
                self.assertEqual(stored, {'stage': stage, 'tool': tool,
                    'session_id': name, 'business': args})
                return original(*values)
            with patch('openhands.sdk.llm.llm.litellm_completion',
                       return_value=self.response(args, tool=tool)), \
                    patch.object(c, method, side_effect=observe):
                run_two_stage_session(c, llm, name, output, stage=stage)
            self.assertEqual(len(c.calls), 1)
            self.assertFalse(c.halted)

    def test_existing_sdk_submission_is_never_overwritten_or_dispatched(self):
        c, llm, _, output = self.bound('existing_submission', 'probe')
        original = b'{"previous":"untouched"}\n'
        (output/'sdk-submission.json').write_bytes(original)
        with patch('openhands.sdk.llm.llm.litellm_completion',
                   return_value=self.response(self.arguments('probe'))):
            run_two_stage_session(c, llm, 'existing_submission', output, stage='probe')
        self.assertEqual((output/'sdk-submission.json').read_bytes(), original)
        self.assertEqual(c.calls, [])
        self.assertTrue(c.halted)
        self.assertEqual(c.infrastructure_error_type, 'FileExistsError')

    def test_invalid_required_business_fields_never_reach_controller(self):
        for name, stage, changes in [('bad_probe', 'probe', {'probe_id': 17}),
                                    ('extra_probe', 'probe', {'command': 'read_file'}),
                                    ('bad_revision', 'revision', {'n_params': True})]:
            c, _, ledger, output, _ = self.run_mock(name, stage, self.arguments(stage, **changes))
            self.assertEqual(c.calls, [])
            self.assertEqual(ledger.summary()['known_total_tokens'], 120)
            audit = json.loads((output/'requests/input-audit-0001.json').read_text())
            self.assertEqual(audit['response_tool_validation']['status'], 'invalid_request')

    def test_multiple_or_wrong_tools_never_dispatch(self):
        for name, tool, second in [('multiple', 'submit_probe', True),
                                   ('wrong_stage', 'submit_candidate', False),
                                   ('ambient', 'read_file', False)]:
            c, _, ledger, _, result = self.run_mock(name, 'probe', self.arguments('probe'),
                                                   tool=tool, second=second)
            self.assertEqual(c.calls, [])
            self.assertIn('PilotResponseContractError', (result.get('cause_type'), result.get('model_error_type')))
            self.assertEqual(ledger.summary()['known_total_tokens'], 120)

    def test_finish_plain_text_and_missing_tool_call_do_not_fabricate_submission(self):
        for name, args, tool, reason in [
            ('finish', {'message': 'Done.'}, 'finish', 'tool_calls'),
            ('text', None, 'submit_probe', 'stop'),
            ('incomplete', None, 'submit_probe', 'tool_calls')]:
            c, _, ledger, _, result = self.run_mock(name, 'probe', args, tool=tool, reason=reason)
            self.assertEqual(c.calls, [])
            self.assertEqual(result['controller']['submissions'], 0)
            self.assertEqual(ledger.summary()['request_count'], 1)
            if name == 'incomplete':
                self.assertIn('IncompleteToolResponseError', (result.get('cause_type'), result.get('model_error_type')))

    def test_unknown_usage_halts_ledger_and_denies_second_transport(self):
        c, llm, ledger, output = self.bound('unknown', 'probe')
        response = self.response(self.arguments('probe'))
        response.usage = None
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=response) as provider:
            run_two_stage_session(c, llm, 'unknown', output, stage='probe')
            with self.assertRaises(BudgetExceeded):
                llm._transport_call(messages=[], max_tokens=4096)
        self.assertEqual(provider.call_count, 1)
        self.assertTrue(ledger.summary()['halted'])
        self.assertEqual(ledger.summary()['usage_unknown_count'], 1)

    def test_tool_storage_failure_marks_fatal_state_even_when_sdk_swallows_exception(self):
        for stage in ('probe', 'revision'):
            name = 'storage_'+stage
            c, llm, ledger, output = self.bound(name, stage)
            method = 'submit_probe' if stage == 'probe' else 'submit'
            tool = 'submit_probe' if stage == 'probe' else 'submit_candidate'
            with patch('openhands.sdk.llm.llm.litellm_completion',
                       return_value=self.response(self.arguments(stage), tool=tool)), \
                    patch.object(c, method, side_effect=OSError('PRIVATE_STORAGE_BODY')):
                run_two_stage_session(c, llm, name, output, stage=stage)
            self.assertTrue(c.halted)
            self.assertEqual(c.infrastructure_error_type, 'OSError')
            saved = json.loads((output/'controller-error.json').read_text())
            self.assertEqual(saved['error_type'], 'OSError')
            self.assertNotIn('PRIVATE_STORAGE_BODY', json.dumps(saved))
            self.assertEqual(ledger.summary()['known_total_tokens'], 120)

    def test_actual_revision_requests_differ_only_in_probe_feedback(self):
        requests = []
        for name, feedback in [('self_arm', None), ('checked_arm', {'verdict': 'unknown'})]:
            c, llm, _, output = self.bound(name, 'revision', feedback)
            with patch('openhands.sdk.llm.llm.litellm_completion',
                       return_value=self.response(self.arguments('revision'), tool='submit_candidate')):
                run_two_stage_session(c, llm, name, output, stage='revision')
            payload = json.loads((output/'requests/request-0001.request.json').read_text())
            packet = json.loads(payload['messages'][1]['content'])
            self.assertEqual(packet.pop('probe_feedback'), feedback)
            payload['messages'][1]['content'] = json.dumps(packet, sort_keys=True, separators=(',', ':'))
            requests.append(payload)
        self.assertEqual(*requests)

    def test_input_limit_denies_before_provider_or_reservation(self):
        c, llm, ledger, output = self.bound('input_cap', 'probe', max_input_bytes=32)
        with patch('openhands.sdk.llm.llm.litellm_completion') as provider:
            run_two_stage_session(c, llm, 'input_cap', output, stage='probe')
        provider.assert_not_called()
        self.assertEqual(ledger.summary()['request_count'], 0)
        self.assertEqual(c.calls, [])

    def test_invalid_stage_binding_and_repeated_output_refuse_before_network(self):
        c, llm, ledger, output = self.bound('wrong_binding', 'probe')
        with patch('openhands.sdk.llm.llm.litellm_completion') as provider:
            for stage in ('invalid', 'revision'):
                with self.assertRaises(ValueError):
                    run_two_stage_session(c, llm, 'wrong_binding', output, stage=stage)
        provider.assert_not_called()
        self.assertEqual(ledger.summary()['request_count'], 0)
        c, llm, _, output, _ = self.run_mock('repeat', 'probe', self.arguments('probe'))
        with patch('openhands.sdk.llm.llm.litellm_completion') as provider:
            with self.assertRaises(FileExistsError):
                run_two_stage_session(c, llm, 'repeat', output, stage='probe')
        provider.assert_not_called()


if __name__ == '__main__':
    unittest.main()
