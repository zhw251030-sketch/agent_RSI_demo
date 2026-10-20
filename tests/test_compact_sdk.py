"""Real SDK tests for flat short-reference tools; all transport/evaluation is fake."""
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
    from rsi_eval.compact_agent import (CompactCandidateAction, CompactStatePacketLLM,
                                        compact_candidate_tool)
    from rsi_eval.pilot_agent import run_session
    from rsi_eval.pilot_budget import BudgetLedger


class RecordingController:
    """A recorder only: no candidate Python is imported or executed."""
    def __init__(self):
        self.submissions = []
        self.halted = False

    def task_prompt(self):
        return 'Synthetic SDK fixture: submit exactly one candidate; no real task.'

    def state_packet(self):
        return {'version': 'synthetic-short-sdk-fixture', 'task_text': self.task_prompt(),
                'fixture_only': True, 'candidate_count': len(self.submissions),
                'evidence_catalog': [{'id': 'e_fixture', 'kind': 'scalar', 'value': 1.0}]}

    def submit(self, source, n_params, rationale, **declaration):
        self.submissions.append({'source': source, 'n_params': n_params,
                                 'rationale': rationale, **copy.deepcopy(declaration)})
        return {'status': 'synthetic_recorded', 'fixture_only': True}

    def summary(self):
        return {'fixture_only': True, 'submissions_recorded': len(self.submissions)}


@unittest.skipUnless(SDK_PRESENT, 'OpenHands SDK is not installed in this interpreter')
class CompactSDKTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)

    @staticmethod
    def arguments(**changes):
        return {'source': '# synthetic fixture; never executed\n', 'n_params': 0,
                'rationale': 'Synthetic interface test, not a model-generated scientific result.',
                'claim_id': 'e_fixture', 'claim_op': 'eq', 'claim_value_json': '1.0',
                'prediction_id': 'e_fixture', 'prediction_direction': 'decrease',
                'prediction_min_delta': 0.1, **changes}

    @staticmethod
    def response(arguments=None, *, finish_reason='tool_calls', tool_name='submit_candidate'):
        message = {'role': 'assistant', 'content': 'Synthetic offline fixture.'}
        if arguments is not None:
            message['tool_calls'] = [{'id': 'synthetic-call', 'type': 'function',
                'function': {'name': tool_name, 'arguments': json.dumps(arguments)}}]
        return ModelResponse(id='synthetic-response', model='minimax-m3',
            choices=[{'message': message, 'finish_reason': finish_reason}],
            usage={'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120})

    def bound_llm(self, controller, name):
        output = self.output / name
        output.mkdir()
        ledger = BudgetLedger(output / 'budget-ledger.json', session_ids=[name],
                              max_requests=1, max_requests_per_session=1)
        llm = CompactStatePacketLLM(model='anthropic/minimax-m3',
            api_key='offline-placeholder-not-a-real-key', base_url='https://example.invalid',
            max_output_tokens=4096, num_retries=0, caching_prompt=False, api_mode='chat',
            stream=False, reasoning_effort='none', native_tool_calling=True,
            force_string_serializer=False, fallback_strategy=None, log_completions=False
        ).bind_pilot(ledger, name, output / 'requests').bind_controller(controller)
        return llm, ledger, output

    def test_actual_advertised_action_schema_has_only_top_level_primitives(self):
        schema = CompactCandidateAction.to_mcp_schema()
        self.assertEqual(set(schema['properties']), set(self.arguments()))
        self.assertEqual(set(schema['required']), set(self.arguments()))
        for key, value in schema['properties'].items():
            with self.subTest(key=key):
                self.assertIn(value['type'], ('string', 'number', 'integer'))
                self.assertFalse(set(value) & {'items', 'properties', 'anyOf', 'oneOf', '$ref'})
        Draft202012Validator.check_schema(schema)
        for atom in ('1.0', '["edge","$0","$1"]'):
            value = self.arguments(claim_value_json=atom)
            Draft202012Validator(schema).validate(value)
            self.assertEqual(CompactCandidateAction.model_validate(value).claim_value_json, atom)

    def test_action_forwards_semantic_invalidity_without_attempting_to_repair(self):
        # The trusted controller records unavailable/schema_invalid evidence;
        # interface validation only limits transport types/size and capabilities.
        for value in ('{bad', '{"a":1,"a":2}', 'true', 'NaN', '1 2', '[1]', 'null'):
            with self.subTest(value=value):
                action = CompactCandidateAction.model_validate(self.arguments(
                    claim_id='unknown', claim_op='unknown', claim_value_json=value,
                    prediction_id='old', prediction_direction='unknown', prediction_min_delta=-1))
                self.assertEqual(action.claim_value_json, value)
                self.assertEqual(action.prediction_min_delta, -1)

    def test_action_rejects_transport_coercion_oversize_and_old_nested_capabilities(self):
        changes = [{'source': ' '}, {'source': '测' * 5462}, {'source': 1},
                   {'n_params': True}, {'n_params': '1'}, {'n_params': 17},
                   {'claim_id': []}, {'claim_value_json': [1]},
                   {'claim_value_json': '测' * 683}, {'claim_value_json': 'x' * 2049},
                   {'prediction_min_delta': True}, {'prediction_min_delta': '0.1'},
                   {'prediction_min_delta': float('inf')}, {'prediction_min_delta': float('nan')},
                   {'claims': [{}]}, {'prediction': {}}, {'task_id': 'sealed'}, {'command': 'read_file'}]
        for change in changes:
            with self.subTest(change=list(change)), self.assertRaises(ValidationError):
                CompactCandidateAction.model_validate(self.arguments(**change))

    def test_one_sdk_iteration_records_one_candidate_and_settles_one_request(self):
        controller = RecordingController()
        llm, ledger, output = self.bound_llm(controller, 'one_request')
        arguments = self.arguments(summary='SDK-owned metadata', security_risk='LOW')
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(arguments)) as fake:
            result = run_session(controller, llm, 'one_request', output,
                                 tool_factory=compact_candidate_tool, max_iterations=1)
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(controller.submissions, [self.arguments()])
        self.assertEqual(result['controller']['submissions_recorded'], 1)
        self.assertEqual(ledger.summary()['request_count'], 1)
        self.assertEqual(ledger.summary()['known_total_tokens'], 120)
        # Reaching the SDK iteration limit after execution is not evidence that
        # the candidate was absent or unevaluated; runner inspects both records.
        self.assertIn(result['status'], ('stopped', 'completed'))
        audit = json.loads((output / 'requests/input-audit-0001.json').read_text())
        self.assertEqual(audit['response_tool_validation'], {'status': 'valid_submission'})
        advertised = fake.call_args.kwargs['tools']
        candidate = next(tool['function'] for tool in advertised
                         if tool['function']['name'] == 'submit_candidate')
        for field in self.arguments():
            self.assertIn(candidate['parameters']['properties'][field]['type'], ('string', 'number', 'integer'))

    def test_observer_agrees_with_sdk_metadata_handling_and_rejection(self):
        cases = [('sdk_metadata', {'summary': 17, 'security_risk': None}, True),
                 ('old_nested', {'claims': [{}]}, False),
                 ('wrong_type', {'n_params': True}, False),
                 ('semantic_bad', {'claim_value_json': '{bad'}, True)]
        for name, change, accepted in cases:
            with self.subTest(name=name):
                controller = RecordingController()
                llm, ledger, output = self.bound_llm(controller, name)
                with patch('openhands.sdk.llm.llm.litellm_completion',
                           return_value=self.response(self.arguments(**change))) as fake:
                    run_session(controller, llm, name, output,
                                tool_factory=compact_candidate_tool, max_iterations=1)
                self.assertEqual(fake.call_count, 1)
                self.assertEqual(len(controller.submissions), int(accepted))
                self.assertEqual(ledger.summary()['known_total_tokens'], 120)
                audit = json.loads((output / 'requests/input-audit-0001.json').read_text())
                self.assertEqual(audit['response_tool_validation']['status'],
                                 'valid_submission' if accepted else 'invalid_request')

    def test_no_action_response_never_invents_a_candidate(self):
        cases = [('plain_stop', None, 'stop', 'submit_candidate', False),
                 ('incomplete', None, 'tool_calls', 'submit_candidate', True),
                 ('explicit_finish', {'message': 'Done.', 'summary': 'Finish.', 'security_risk': 'LOW'},
                  'tool_calls', 'finish', False)]
        for name, arguments, reason, tool_name, malformed in cases:
            with self.subTest(name=name):
                controller = RecordingController()
                llm, ledger, output = self.bound_llm(controller, name)
                response = self.response(arguments, finish_reason=reason, tool_name=tool_name)
                with patch('openhands.sdk.llm.llm.litellm_completion', return_value=response) as fake:
                    result = run_session(controller, llm, name, output,
                                         tool_factory=compact_candidate_tool, max_iterations=1)
                self.assertEqual(fake.call_count, 1)
                self.assertEqual(controller.submissions, [])
                self.assertEqual(ledger.summary()['known_total_tokens'], 120)
                self.assertEqual(result['status'], 'error' if malformed else 'completed')
                if malformed:
                    self.assertEqual(result['cause_type'], 'IncompleteToolResponseError')

    def test_swallowed_controller_and_feedback_errors_mark_fatal_host_state(self):
        for name, exception, feedback in [('controller_write', OSError('PRIVATE_IO_BODY'), None),
                                          ('invalid_feedback', None, {'value': float('nan')})]:
            with self.subTest(name=name):
                controller = RecordingController()
                llm, ledger, output = self.bound_llm(controller, name)
                controller.output_dir = output
                with patch('openhands.sdk.llm.llm.litellm_completion',
                           return_value=self.response(self.arguments())) as fake, \
                        patch.object(controller, 'submit', side_effect=exception, return_value=feedback):
                    result = run_session(controller, llm, name, output,
                                         tool_factory=compact_candidate_tool, max_iterations=1)
                self.assertEqual(fake.call_count, 1)
                self.assertEqual(result['status'], 'stopped')
                self.assertIsNone(result['model_error_type'])  # SDK swallowed the executor exception.
                self.assertTrue(controller.halted)  # Runner must stop subsequent independent sessions.
                self.assertEqual(ledger.summary()['known_total_tokens'], 120)
                error_record = json.loads((output / 'controller-error.json').read_text())
                self.assertEqual(error_record, {'status': 'infrastructure_error',
                    'error_kind': 'compact_executor_exception',
                    'error_type': 'OSError' if exception else 'ValueError'})
                self.assertNotIn('PRIVATE_IO_BODY', json.dumps(error_record))

    def test_failed_error_record_write_still_keeps_controller_halted(self):
        controller = RecordingController()
        llm, ledger, output = self.bound_llm(controller, 'failed_error_record')
        controller.output_dir = output
        with patch('openhands.sdk.llm.llm.litellm_completion',
                   return_value=self.response(self.arguments())) as fake, \
                patch.object(controller, 'submit', side_effect=OSError('PRIVATE_IO_BODY')), \
                patch('rsi_eval.compact_agent.write_json', side_effect=OSError('PRIVATE_SECOND_BODY')):
            run_session(controller, llm, 'failed_error_record', output,
                        tool_factory=compact_candidate_tool, max_iterations=1)
        self.assertEqual(fake.call_count, 1)
        self.assertTrue(controller.halted)
        self.assertEqual(controller.infrastructure_error_type, 'OSError')
        self.assertEqual(ledger.summary()['known_total_tokens'], 120)
        self.assertFalse((output / 'controller-error.json').exists())


if __name__ == '__main__':
    unittest.main()
