"""Actual SDK lifecycle with an offline provider; never evaluates source."""
import copy
import importlib.util
import json
import logging
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
    from rsi_eval.pilot_budget import BudgetLedger
    try:
        import rsi_eval.state_generation_agent as adapter
    except ModuleNotFoundError as error:
        if error.name != 'rsi_eval.state_generation_agent':
            raise
        adapter = None


class Recorder:
    def __init__(self, output):
        self.output_dir = output
        self.packet = {'stage': 'generation', 'family': 'planning',
                       'task': 'Return a complete initial Python program.'}
        self.calls = []
        self.candidate = None
        self.halted = False
        self.infrastructure_error_type = None

    def task_packet(self):
        return copy.deepcopy(self.packet)

    def task_prompt(self):
        return json.dumps(self.task_packet())

    def submit(self, session_id, source, n_params):
        if self.candidate is not None:
            raise RuntimeError('Duplicate submission')
        self.calls.append(dict(session_id=session_id, source=source, n_params=n_params))
        with (self.output_dir/'source.py').open('xb') as stream:
            stream.write(source.encode('utf-8'))
        self.candidate = {'source': 'source.py', 'n_params': n_params}
        with (self.output_dir/'candidate.json').open('x') as stream:
            json.dump(self.candidate, stream)
        return {'status': 'recorded', 'candidate_executions': 0}

    def summary(self):
        return {'submissions': len(self.calls), 'halted': self.halted,
                'candidate': self.candidate, 'candidate_executions': 0}


@unittest.skipUnless(SDK_PRESENT, 'OpenHands SDK is absent; run these tests in the server SDK 1.55.1 environment')
class GenerationSDKTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(adapter, 'The generation adapter has not been implemented')
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        level = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, level)

    @staticmethod
    def arguments(**changes):
        return dict(source='def solve(): return []\n', n_params=0) | changes

    @staticmethod
    def response(args=None, *, tool='submit_candidate', second=False,
                 reason='tool_calls', unknown_usage=False):
        message = {'role': 'assistant', 'content': 'Offline fixture.'}
        if args is not None:
            call = {'id': 'call-1', 'type': 'function',
                    'function': {'name': tool, 'arguments': json.dumps(args)}}
            message['tool_calls'] = [call]
            if second:
                message['tool_calls'].append({**copy.deepcopy(call), 'id': 'call-2'})
        response = ModelResponse(id='response-fixture', model='minimax-m3',
            choices=[{'message': message, 'finish_reason': reason}],
            usage={'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120})
        if unknown_usage:
            response.usage = None
        return response

    def bound(self, name, **budgets):
        output = self.root/name
        output.mkdir()
        controller = Recorder(output)
        limits = dict(max_requests=1, max_requests_per_session=1, max_output_tokens=8192,
                      max_input_bytes=65536, max_reserved_tokens=1000000, max_cost_cny=5)
        limits.update(budgets)
        ledger = BudgetLedger(output/'budget-ledger.json', session_ids=[name], **limits)
        llm = adapter.GenerationStatePacketLLM(model='anthropic/minimax-m3',
            api_key='offline-placeholder', base_url='https://example.invalid',
            max_output_tokens=8192, num_retries=0, caching_prompt=False,
            api_mode='chat', stream=False, reasoning_effort='none',
            native_tool_calling=True, force_string_serializer=False,
            fallback_strategy=None, log_completions=False).bind_controller(controller).bind_pilot(
                ledger, name, output/'requests')
        return controller, llm, ledger, output

    def run_mock(self, name, args=None, **options):
        controller, llm, ledger, output = self.bound(name)
        with patch('openhands.sdk.llm.llm.litellm_completion',
                   return_value=self.response(args, **options)) as provider:
            result = adapter.run_generation_session(controller, llm, name, output)
        self.assertEqual(provider.call_count, 1)
        return controller, llm, ledger, output, result

    def test_schema_has_only_two_required_fields_and_bounds(self):
        schema = adapter.GenerationAction.to_mcp_schema()
        self.assertEqual(set(schema['properties']), {'source', 'n_params'})
        self.assertEqual(set(schema['required']), {'source', 'n_params'})
        self.assertIs(schema['additionalProperties'], False)
        self.assertEqual(schema['properties']['source']['maxLength'], 16384)
        self.assertEqual(schema['properties']['n_params']['maximum'], 16)
        Draft202012Validator(schema).validate(self.arguments())

    def test_strict_source_parameter_and_extra_field_validation(self):
        for changes in [dict(source=''), dict(source=' \n'), dict(source='中'*5462),
                        dict(source='\ud800'), dict(source=1), dict(n_params=True),
                        dict(n_params=1.0), dict(n_params=-1), dict(n_params=17),
                        dict(rationale='no'), dict(auxiliary={})]:
            with self.subTest(fields=list(changes)), self.assertRaises(ValidationError):
                adapter.GenerationAction.model_validate(self.arguments(**changes))
        self.assertEqual(adapter.GenerationAction.model_validate(self.arguments()).n_params, 0)

    def test_roundtrip_archives_without_execution_and_binds_actual_request(self):
        c, llm, ledger, output, result = self.run_mock('roundtrip', self.arguments())
        self.assertEqual(c.calls, [dict(session_id='roundtrip', **self.arguments())])
        self.assertEqual(result['tools'], ['finish', 'submit_candidate'])
        self.assertEqual(result['stage'], 'generation')
        self.assertEqual(result['controller']['candidate_executions'], 0)
        self.assertEqual((output/'source.py').read_text(), self.arguments()['source'])
        self.assertEqual(ledger.summary()['known_total_tokens'], 120)
        payload = json.loads((output/'requests/request-0001.request.json').read_text())
        self.assertEqual(json.loads(payload['messages'][1]['content']), c.task_packet())
        self.assertEqual(payload['max_output_tokens'], 8192)
        self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                           separators=(',', ':')).encode()), 65536)
        system = payload['messages'][0]['content']
        if not isinstance(system, str):
            system = ''.join(item.get('text', '') for item in system)
        self.assertIn(adapter.GENERATION_SYSTEM_PROMPT, system)
        self.assertEqual({tool['function']['name'] for tool in payload['tools']},
                         {'submit_candidate', 'finish'})

    def test_receipt_is_durable_before_core_submit(self):
        c, llm, _, output = self.bound('durable')
        original = c.submit
        def observe(session_id, source, n_params):
            self.assertEqual(json.loads((output/'sdk-submission.json').read_text()),
                {'stage': 'generation', 'session_id': 'durable', 'tool': 'submit_candidate',
                 'business': self.arguments()})
            return original(session_id, source, n_params)
        with patch.object(c, 'submit', side_effect=observe), \
             patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(self.arguments())), \
             patch('rsi_eval.state_generation_agent.os.fsync', wraps=__import__('os').fsync) as fsync:
            adapter.run_generation_session(c, llm, 'durable', output)
        self.assertEqual(len(c.calls), 1)
        self.assertGreaterEqual(fsync.call_count, 1)

    def test_raw_metadata_is_preserved_separately_from_sdk_business(self):
        args = self.arguments(security_risk=None, summary=42)
        c, _, _, output, _ = self.run_mock('metadata', args)
        self.assertEqual(c.calls, [dict(session_id='metadata', **self.arguments())])
        raw = json.loads((output/'requests/request-0001.response.json').read_text())
        self.assertEqual(json.loads(raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']), args)
        self.assertEqual(json.loads((output/'sdk-submission.json').read_text())['business'], self.arguments())

    def test_malformed_business_never_creates_a_candidate_or_receipt(self):
        bad = [dict(source='x'), self.arguments(rationale='x'), self.arguments(auxiliary={}),
               self.arguments(n_params=True), self.arguments(source='中'*5462)]
        for index, args in enumerate(bad):
            c, _, _, output, _ = self.run_mock('malformed_'+str(index), args)
            self.assertEqual(c.calls, [])
            self.assertFalse((output/'sdk-submission.json').exists())
            self.assertFalse((output/'candidate.json').exists())

    def test_finish_plain_text_and_empty_tool_calls_are_missing_results(self):
        cases = [('finish', {'message': 'Done'}, {'tool': 'finish'}),
                 ('plain', None, {'reason': 'stop'}), ('empty', None, {})]
        for name, args, options in cases:
            c, _, ledger, output, _ = self.run_mock(name, args, **options)
            self.assertEqual(c.calls, [])
            self.assertEqual(ledger.summary()['request_count'], 1)
            self.assertFalse((output/'sdk-submission.json').exists())

    def test_forbidden_or_duplicate_tool_calls_never_dispatch(self):
        for name, options in [('forbidden', {'tool': 'terminal'}), ('double', {'second': True})]:
            c, _, _, output, _ = self.run_mock(name, self.arguments(), **options)
            self.assertEqual(c.calls, [])
            self.assertFalse((output/'sdk-submission.json').exists())

    def test_packet_change_before_run_is_rejected_before_provider(self):
        c, llm, _, output = self.bound('packet_before')
        c.packet['task'] = 'Another task'
        with patch('openhands.sdk.llm.llm.litellm_completion') as provider:
            with self.assertRaises(ValueError):
                adapter.run_generation_session(c, llm, 'packet_before', output)
        provider.assert_not_called()
        self.assertIsNone(c.candidate)

    def test_packet_change_after_transport_preserves_response_but_rejects_dispatch(self):
        c, llm, _, output = self.bound('packet_after')
        def changed(**kwargs):
            c.packet['task'] = 'Changed after transport'
            return self.response(self.arguments())
        with patch('openhands.sdk.llm.llm.litellm_completion', side_effect=changed):
            adapter.run_generation_session(c, llm, 'packet_after', output)
        self.assertTrue((output/'requests/request-0001.response.json').exists())
        self.assertEqual(c.calls, [])
        self.assertTrue(c.halted)

    def test_packet_and_full_wire_have_separate_64k_limits(self):
        c, llm, _, output = self.bound('packet_big')
        c.packet['padding'] = 'x'*65536
        with self.assertRaises(ValueError):
            llm.bind_controller(c)
        c, llm, ledger, output = self.bound('wire_big')
        c.packet['padding'] = 'x'*64500
        llm.bind_controller(c)
        with patch('openhands.sdk.llm.llm.litellm_completion') as provider:
            adapter.run_generation_session(c, llm, 'wire_big', output)
        provider.assert_not_called()
        self.assertEqual(ledger.summary()['request_count'], 0)
        self.assertIsNone(c.candidate)

    def test_unknown_usage_halts_without_accepting_source(self):
        c, _, ledger, output, _ = self.run_mock('unknown_usage', self.arguments(), unknown_usage=True)
        self.assertTrue(ledger.summary()['halted'])
        self.assertTrue((output/'requests/request-0001.response.json').exists())
        self.assertEqual(c.calls, [])
        self.assertIsNone(c.candidate)

    def test_existing_receipt_is_never_overwritten_or_redispatched(self):
        c, llm, _, output = self.bound('receipt')
        (output/'sdk-submission.json').write_bytes(b'original')
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(self.arguments())):
            adapter.run_generation_session(c, llm, 'receipt', output)
        self.assertEqual((output/'sdk-submission.json').read_bytes(), b'original')
        self.assertEqual(c.calls, [])
        self.assertTrue(c.halted)

    def test_second_session_run_refuses_before_another_model_request(self):
        c, llm, _, output, _ = self.run_mock('once', self.arguments())
        with patch('openhands.sdk.llm.llm.litellm_completion') as provider:
            with self.assertRaises((ValueError, FileExistsError)):
                adapter.run_generation_session(c, llm, 'once', output)
        provider.assert_not_called()
        self.assertEqual(len(c.calls), 1)

    def test_invalid_caps_or_controller_binding_refuse_before_provider(self):
        for name, caps in [('two_requests', {'max_requests_per_session': 2}),
                           ('wide_input', {'max_input_bytes': 65537}),
                           ('wide_output', {'max_output_tokens': 8193})]:
            c, llm, _, output = self.bound(name, **caps)
            with patch('openhands.sdk.llm.llm.litellm_completion') as provider:
                with self.assertRaises(ValueError):
                    adapter.run_generation_session(c, llm, name, output)
            provider.assert_not_called()
        c, llm, _, output = self.bound('mismatch')
        with self.assertRaises(ValueError):
            adapter.run_generation_session(Recorder(output), llm, 'mismatch', output)

    def test_controller_exception_is_halted_and_private_text_is_not_reported(self):
        c, llm, _, output = self.bound('failure')
        with patch.object(c, 'submit', side_effect=OSError('private-secret-fixture')), \
             patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(self.arguments())):
            result = adapter.run_generation_session(c, llm, 'failure', output)
        self.assertTrue(c.halted)
        self.assertEqual(c.infrastructure_error_type, 'OSError')
        self.assertTrue((output/'sdk-submission.json').exists())
        self.assertNotIn('private-secret-fixture', json.dumps(result))
        self.assertNotIn('private-secret-fixture', (output/'controller-error.json').read_text())


if __name__ == '__main__':
    unittest.main()
