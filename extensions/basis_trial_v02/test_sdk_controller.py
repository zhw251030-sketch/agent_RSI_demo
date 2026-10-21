"""IDs-only SDK boundary, with assistant prose isolated from business decisions."""
import copy
import importlib.util
import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from extensions.basis_trial_v02 import sdk_controller as controller
from extensions.symbolic_basis_v01.contract import make_spec
from rsi_eval.pilot_budget import BudgetLedger


def business():
    return {'feature_ids': ['m_0_0', 'm_0_1', 'm_1_0']}


def policy():
    return {'rule_ids': ['R02', 'R01', 'R05', 'R08']}


def envelope(payload=None, name='submit_basis', **message_fields):
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
        **message_fields, 'tool_calls': [{'index': 0, 'id': 'call-1', 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(business() if payload is None else payload)}}]}}]}


class ContractTests(unittest.TestCase):
    def test_ids_only_policy_and_basis_accepted(self):
        self.assertEqual(controller.validate_policy_business(policy()), policy())
        self.assertEqual(controller.validate_basis_business(business(), make_spec(2, 3)), business())

    def test_absent_empty_null_and_long_content_do_not_change_decision(self):
        for content in ({}, {'content': None}, {'content': ''}, {'content': '中文 reasoning ' * 600}):
            self.assertEqual(controller.parse_policy_response(envelope(policy(), 'submit_policy', **content)), policy())
            self.assertEqual(controller.parse_basis_response(envelope(**content), make_spec(2, 3)), business())

    def test_explanation_tool_field_still_rejected_without_rewriting(self):
        old = envelope(policy() | {'explanation': 'a' * 4223}, 'submit_policy')
        original = copy.deepcopy(old)
        with self.assertRaises(ValueError): controller.parse_policy_response(old)
        self.assertEqual(old, original)
        with self.assertRaises(ValueError):
            controller.parse_basis_response(envelope(business() | {'explanation': 'x'}), make_spec(2, 3))

    def test_duplicate_raw_json_is_rejected(self):
        for key, name, parse in [('rule_ids', 'submit_policy', controller.parse_policy_response),
                ('feature_ids', 'submit_basis', lambda value: controller.parse_basis_response(value, make_spec(2, 3)))]:
            original = policy() if key == 'rule_ids' else business()
            args = json.dumps(original)
            raw = args[:-1] + ',"' + key + '":' + json.dumps(original[key]) + '}'
            value = envelope(original, name)
            value['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = raw
            with self.assertRaises(ValueError): parse(value)

    def test_invalid_ids_types_and_unknown_fields_rejected(self):
        for value in ({'rule_ids':['R01'] * 4}, {'rule_ids':['R01','R02','R03','R99']},
                {'rule_ids':tuple(policy()['rule_ids'])}, policy() | {'summary':'extra'}):
            with self.assertRaises(ValueError): controller.validate_policy_business(value)
        for value in ({'feature_ids':['m_0_0'] * 3}, {'feature_ids':['m_0_1','m_1_0','m_1_1']},
                {'feature_ids':['m_0_0', True, 'm_1_0']}, {'feature_ids':['m_0_0','m_9_9','m_1_0']},
                {'feature_ids':tuple(business()['feature_ids'])}, business() | {'summary':'extra'}):
            with self.assertRaises(ValueError): controller.validate_basis_business(value, make_spec(2, 3))

    def test_envelope_index_is_checked_before_projection(self):
        original = envelope()
        normalized = controller.normalize_envelope(original, 'submit_basis')
        self.assertNotIn('index', normalized['choices'][0]['message']['tool_calls'][0])
        self.assertEqual(original['choices'][0]['message']['tool_calls'][0]['index'], 0)
        for key, value in [('index', True), ('index', 1), ('unexpected', None)]:
            altered = copy.deepcopy(original)
            altered['choices'][0]['message']['tool_calls'][0][key] = value
            with self.assertRaises(ValueError): controller.normalize_envelope(altered, 'submit_basis')

    def test_multiple_choices_calls_or_wrong_finish_rejected(self):
        for change in ('choices', 'calls', 'finish'):
            value = envelope()
            if change == 'choices': value['choices'] *= 2
            elif change == 'calls': value['choices'][0]['message']['tool_calls'] *= 2
            else: value['choices'][0]['finish_reason'] = 'stop'
            with self.assertRaises(ValueError): controller.normalize_envelope(value, 'submit_basis')

    def test_total_response_bound_applies_to_archive_content(self):
        with self.assertRaises(ValueError):
            controller.parse_policy_response(envelope(policy(), 'submit_policy', content='a' * 65536))

    def test_nontext_content_and_nonfinite_json_rejected(self):
        for content in (12, True, [], {}):
            with self.assertRaises(ValueError): controller.parse_policy_response(envelope(policy(), 'submit_policy', content=content))
        value = envelope(policy(), 'submit_policy')
        value['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = '{"rule_ids":NaN}'
        with self.assertRaises(ValueError): controller.parse_policy_response(value)

    def test_execution_payload_explicitly_marks_host_metadata(self):
        result = controller.execution_conversion(business(), make_spec(2, 3))
        self.assertEqual(result['business'], business())
        self.assertEqual(result['receipt']['explanation_author'], 'host_authored')
        self.assertEqual(result['receipt']['model_explanation_used'], False)
        self.assertEqual(set(result['execution_payload']), {'feature_ids', 'explanation'})
        self.assertEqual(result['compiled']['feature_ids'], business()['feature_ids'])


try:
    SDK = importlib.util.find_spec('openhands.sdk') is not None
except ModuleNotFoundError:
    SDK = False


@unittest.skipUnless(SDK, 'Requires server OpenHands SDK 1.55.1')
class SDKTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = controller.public_settings() | {'api_key':'synthetic-no-network-key'}
        self.ledger = BudgetLedger(self.root/'ledger.json', max_requests=13,
            max_requests_per_session=1, max_output_tokens=8192, max_reserved_tokens=2000000,
            max_cost_cny=4, session_ids=['slot-a','slot-b','slot-c','slot-d'])
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def run_slot(self, stage='actor', reply=None, slot='slot-a', **kwargs):
        provider = controller.FakeProvider([reply or {'tool':'submit_basis','arguments':business()}])
        with patch('openhands.sdk.llm.llm.litellm_completion', provider):
            result = controller.run_session(self.root, self.root/slot, slot,
                {'task':'synthetic', 'repair_policy':{'rule_ids':['R01','R02','R03','R04']}},
                self.ledger, self.settings, stage=stage, spec=make_spec(2,3) if stage=='actor' else None, **kwargs)
        return result, provider

    def test_actual_basis_acceptance_preserves_raw_ids_and_records_host_conversion(self):
        result, provider = self.run_slot()
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(result['business'], business())
        self.assertEqual(result['compiled']['n_params'], 3)
        self.assertEqual(result['execution_payload']['feature_ids'], business()['feature_ids'])
        receipt = json.loads((self.root/'slot-a/host-conversion.json').read_bytes())
        self.assertEqual(receipt['explanation_author'], 'host_authored')
        self.assertEqual(receipt['model_explanation_used'], False)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.ledger.summary()['request_count'], 1)
        self.assertTrue((self.root/'slot-a/sdk-dispatch.json').is_file())
        request = json.loads((self.root/result['request']['path']).read_bytes())
        self.assertEqual(set(request['tools'][0]['function']['parameters']['properties']), {'feature_ids'})

    def test_actual_policy_accepts_absent_empty_and_long_assistant_content(self):
        for slot, text in [('slot-a', None), ('slot-b', ''), ('slot-c', 'q' * 4223), ('slot-d', '中文' * 5000)]:
            result, provider = self.run_slot(stage='update', slot=slot,
                reply={'tool':'submit_policy','arguments':policy(),'content':text})
            self.assertEqual(result['status'], 'accepted')
            self.assertEqual(result['business'], policy())
            self.assertEqual(provider.calls, 1)
            raw = json.loads((self.root/result['response']['path']).read_bytes())
            self.assertEqual(raw['choices'][0]['message'].get('content'), text)
            request = json.loads((self.root/result['request']['path']).read_bytes())
            self.assertEqual(set(request['tools'][0]['function']['parameters']['properties']), {'rule_ids'})

    def test_actual_actor_accepts_absent_empty_and_long_assistant_content(self):
        hashes=[]
        for slot, text in [('slot-a', None), ('slot-b', ''), ('slot-c', 'q' * 4223), ('slot-d', '中文' * 5000)]:
            result, _ = self.run_slot(slot=slot, reply={'tool':'submit_basis','arguments':business(),'content':text})
            self.assertEqual(result['status'], 'accepted')
            hashes.append(result['compiled']['source_sha256'])
            raw = json.loads((self.root/result['response']['path']).read_bytes())
            self.assertEqual(raw['choices'][0]['message'].get('content'), text)
            self.assertNotEqual(result['compiled']['explanation'], text)
        self.assertEqual(len(set(hashes)), 1)

    def test_old_explanation_argument_is_rejected_and_preserved(self):
        for stage, slot, args in [('actor','slot-a',business()),('update','slot-b',policy())]:
            args = args | {'explanation':'x' * 4223}
            result, provider = self.run_slot(stage=stage, slot=slot,
                reply={'tool':'submit_basis' if stage=='actor' else 'submit_policy','arguments':args})
            self.assertEqual(result['status'],'error')
            self.assertIsNone(result['compiled'])
            self.assertIsNone(result['policy'])
            self.assertEqual(provider.calls,1)
            raw=json.loads((self.root/result['response']['path']).read_bytes())
            self.assertEqual(json.loads(raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']),args)

    def test_bad_ids_are_not_sent_to_callback(self):
        seen=[]
        result,_=self.run_slot(reply={'tool':'submit_basis','arguments':{'feature_ids':['m_0_0','m_1_0','invalid']}},accept_callback=lambda x: seen.append(x) or {})
        self.assertEqual(result['status'],'error')
        self.assertEqual(seen,[])

    def test_template_capture_uses_actual_sdk_without_reservation(self):
        provider = controller.FakeProvider([])
        with patch('openhands.sdk.llm.llm.litellm_completion',provider):
            payload = controller.capture_request_template(self.root,self.root/'template','slot-a',
                {'task':'fixture'},self.ledger,self.settings,stage='actor',spec=make_spec(2,3))
        self.assertEqual(provider.calls,0)
        self.assertEqual(self.ledger.summary()['request_count'],0)
        self.assertEqual(payload['messages'][-1],{'role':'user','content':'{"task":"fixture"}'})

    def test_unknown_usage_stops_before_acceptance(self):
        result,provider=self.run_slot(reply={'tool':'submit_basis','arguments':business(),'usage':None})
        self.assertEqual(result['status'],'error')
        self.assertIsNone(result['compiled'])
        self.assertEqual(provider.calls,1)
        self.assertEqual(self.ledger.summary()['usage_unknown_count'],1)

    def test_duplicate_business_keys_rejected_before_sdk_action(self):
        raw = '{"feature_ids":["m_0_0","m_0_1","m_1_0"],"feature_ids":["m_0_0","m_0_1","m_1_0"]}'
        result,provider=self.run_slot(reply={'tool':'submit_basis','arguments':raw})
        self.assertEqual(result['status'],'error')
        self.assertIsNone(result['compiled'])
        self.assertEqual(provider.calls,1)

    def test_provider_failure_is_once_and_usage_unknown(self):
        result,provider=self.run_slot(reply={'raise':RuntimeError('Synthetic transport failure')})
        self.assertEqual(result['status'],'error')
        self.assertEqual(provider.calls,1)
        self.assertEqual(self.ledger.summary()['usage_unknown_count'],1)

    def test_callback_failure_consumes_session_without_repair(self):
        count=[]
        def fail(value):
            count.append(value)
            raise RuntimeError('Synthetic host failure')
        result,provider=self.run_slot(accept_callback=fail)
        self.assertEqual(result['status'],'error')
        self.assertEqual(len(count),1)
        self.assertEqual(provider.calls,1)

    def test_response_over_byte_bound_stops_without_callback(self):
        seen=[]
        result,provider=self.run_slot(reply={'tool':'submit_basis','arguments':business(),'content':'a' * 65536},
            accept_callback=lambda x: seen.append(x) or {})
        self.assertEqual(result['status'],'error')
        self.assertEqual(provider.calls,1)
        self.assertEqual(seen,[])

    def test_existing_output_and_wrong_settings_refuse_before_call(self):
        (self.root/'slot-a').mkdir()
        with self.assertRaises(FileExistsError): self.run_slot()
        self.assertEqual(self.ledger.summary()['request_count'],0)
        settings=self.settings | {'num_retries':1}
        with self.assertRaises(ValueError):
            controller.run_session(self.root,self.root/'other','slot-a',{},self.ledger,settings,stage='actor',spec=make_spec(2,3))
        self.assertEqual(self.ledger.summary()['request_count'],0)


if __name__ == '__main__':
    unittest.main()
