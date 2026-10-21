"""Submission boundary tests; actual SDK execution uses a fake host callback only."""
import copy
import importlib.util
import json
import unittest

from extensions.symbolic_basis_v01 import sdk_adapter as adapter


def business():
    return {'feature_ids': ['m_0_0', 'm_1_0', 'm_0_1'], 'explanation': 'Choose constant and two linear terms.'}


def response(payload=None):
    return {'id': 'synthetic-response', 'choices': [{'finish_reason': 'tool_calls', 'message': {
        'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'synthetic-call',
        'type': 'function', 'function': {'name': 'submit_basis',
        'arguments': json.dumps(business() if payload is None else payload)}}]}}]}


class RawResponseTests(unittest.TestCase):
    def test_raw_text_and_provider_dict_agree_without_normalization(self):
        self.assertEqual(adapter.parse_tool_response(response()), business())
        self.assertEqual(adapter.parse_tool_response(json.dumps(response())), business())

    def test_duplicate_business_and_envelope_keys_are_rejected(self):
        duplicate = response()
        duplicate['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = (
            '{"feature_ids":["m_0_0"],"feature_ids":["m_1_0"],"explanation":"x"}')
        with self.assertRaises(ValueError):
            adapter.parse_tool_response(duplicate)
        with self.assertRaises(ValueError):
            adapter.parse_tool_response('{"choices":[],"choices":[]}')

    def test_no_python_parameters_tasks_or_sdk_metadata_in_business(self):
        for key in ('source', 'params', 'n_params', 'task_id', 'role', 'summary', 'security_risk'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                adapter.parse_tool_response(response(business() | {key: 'untrusted'}))

    def test_wrong_tool_multiple_calls_choices_and_end_markers_rejected(self):
        for mutation in ('tool', 'two_calls', 'no_calls', 'two_choices', 'finish', 'role'):
            value = response()
            choice = value['choices'][0]
            calls = choice['message']['tool_calls']
            if mutation == 'tool':
                calls[0]['function']['name'] = 'finish'
            elif mutation == 'two_calls':
                calls.append(copy.deepcopy(calls[0]))
            elif mutation == 'no_calls':
                calls.clear()
            elif mutation == 'two_choices':
                value['choices'].append(copy.deepcopy(choice))
            elif mutation == 'finish':
                choice['finish_reason'] = 'stop'
            else:
                choice['message']['role'] = 'tool'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                adapter.parse_tool_response(value)

    def test_no_coercion_repair_or_nonfinite_json(self):
        values = [business() | {'feature_ids': 'm_0_0'}, business() | {'feature_ids': [0, True]},
                  business() | {'explanation': 1}, business() | {'feature_ids': ['m_0_0', 'm_0_0']}]
        for payload in values:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                adapter.parse_tool_response(response(payload))
        for arguments in ('{"feature_ids":["m_0_0"],"explanation":NaN}', '{bad json}',
                          {'feature_ids': ['m_0_0'], 'explanation': 'already decoded'}):
            value = response()
            value['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = arguments
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                adapter.parse_tool_response(value)

    def test_oversized_and_invalid_utf8_payloads_rejected(self):
        for text in ('x' * 65537, '\ud800'):
            with self.subTest(text_length=len(text)), self.assertRaises(ValueError):
                adapter.parse_tool_response(text)


class HandlerTests(unittest.TestCase):
    def setUp(self):
        from extensions.symbolic_basis_v01.contract import make_spec
        self.spec = make_spec(2, 3)
        self.received = []
        self.handler = adapter.BasisSubmissionHandler(self.spec, self.receive)

    def receive(self, compiled):
        self.received.append(compiled)
        return {'status': 'synthetic_host_received', 'n_params': compiled['n_params']}

    def test_frozen_spec_and_parsed_submission_are_not_caller_mutable(self):
        self.spec['k'] = 1
        view = self.handler.spec
        view['feature_ids'].clear()
        prepared = self.handler.prepare_response(response())
        prepared['feature_ids'].clear()
        self.assertEqual(self.handler.spec['k'], 3)
        answer = self.handler.accept_action(business())
        self.assertEqual(answer['status'], 'synthetic_host_received')
        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.received[0]['n_params'], 3)

    def test_action_without_raw_validation_and_repeated_attempt_rejected(self):
        with self.assertRaises(ValueError):
            self.handler.accept_action(business())
        with self.assertRaises(ValueError):
            self.handler.prepare_response(response())
        self.assertEqual(self.received, [])

    def test_sdk_cannot_change_normalize_or_add_payload_fields(self):
        self.handler.prepare_response(response())
        with self.assertRaises(ValueError):
            self.handler.accept_action(business() | {'explanation': 'Repaired by SDK'})
        with self.assertRaises(ValueError):
            self.handler.accept_action(business())
        self.assertEqual(self.received, [])

    def test_successful_callback_and_failed_callback_are_both_once_only(self):
        self.handler.prepare_response(response())
        self.handler.accept_action(business())
        with self.assertRaises(ValueError):
            self.handler.accept_action(business())
        with self.assertRaises(ValueError):
            self.handler.prepare_response(response())
        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.handler.state, 'accepted')
        count = []
        def failed(compiled):
            count.append(compiled)
            raise RuntimeError('Synthetic callback failure')
        failed_handler = adapter.BasisSubmissionHandler(self.handler.spec, failed)
        failed_handler.prepare_response(response())
        with self.assertRaises(RuntimeError):
            failed_handler.accept_action(business())
        with self.assertRaises(ValueError):
            failed_handler.accept_action(business())
        self.assertEqual(len(count), 1)

    def test_invalid_contract_fails_before_callback_and_consumes_handler(self):
        invalid = business() | {'feature_ids': ['m_0_0', 'm_1_0', 'not_in_catalog']}
        with self.assertRaises(ValueError):
            self.handler.prepare_response(response(invalid))
        with self.assertRaises(ValueError):
            self.handler.prepare_response(response())
        self.assertEqual(self.received, [])


try:
    SDK = importlib.util.find_spec('openhands.sdk') is not None
except ModuleNotFoundError:
    SDK = False


@unittest.skipUnless(SDK, 'Requires installed server OpenHands SDK')
class ActualSDKTests(unittest.TestCase):
    def setUp(self):
        from extensions.symbolic_basis_v01.contract import make_spec
        self.received = []
        self.handler = adapter.BasisSubmissionHandler(make_spec(2, 3), self.receive)
        self.tool = adapter.build_tool_definition(self.handler)

    def receive(self, compiled):
        self.received.append(compiled)
        return {'status': 'synthetic_host_received', 'n_params': compiled['n_params']}

    def test_actual_sdk_schema_action_executor_roundtrip(self):
        self.assertEqual(self.tool.name, 'submit_basis')
        schema = self.tool.action_type.to_mcp_schema()
        self.assertEqual(set(schema['properties']), {'feature_ids', 'explanation'})
        self.assertEqual(set(schema['required']), {'feature_ids', 'explanation'})
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(schema['properties']['feature_ids']['minItems'], 3)
        self.assertEqual(schema['properties']['feature_ids']['maxItems'], 3)
        self.handler.prepare_response(response())
        action = self.tool.action_type.model_validate(business())
        observation = self.tool.executor(action, conversation=None)
        self.assertEqual(observation.feedback['status'], 'synthetic_host_received')
        self.assertEqual(len(self.received), 1)
        with self.assertRaises(ValueError):
            self.tool.executor(action, conversation=None)
        self.assertEqual(len(self.received), 1)

    def test_sdk_action_rejects_coercion_extras_and_wrong_catalog(self):
        invalid = [business() | {'feature_ids': ('m_0_0', 'm_1_0', 'm_0_1')},
                   business() | {'explanation': 42}, business() | {'source': 'x'},
                   business() | {'security_risk': 'LOW'},
                   business() | {'feature_ids': ['m_0_0', 'm_1_0', 'unknown']}]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.tool.action_type.model_validate(payload)
        self.assertEqual(self.received, [])

    def test_sdk_executor_requires_validated_raw_response(self):
        action = self.tool.action_type.model_validate(business())
        with self.assertRaises(ValueError):
            self.tool.executor(action, conversation=None)
        self.assertEqual(self.received, [])


if __name__ == '__main__':
    unittest.main()
