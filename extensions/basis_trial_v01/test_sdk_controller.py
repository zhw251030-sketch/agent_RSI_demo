"""Controller contracts and actual one-step SDK with an artificial provider."""
import copy
import importlib.util
import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from extensions.basis_trial_v01 import sdk_controller as controller
from extensions.symbolic_basis_v01.contract import make_spec
from rsi_eval.pilot_budget import BudgetLedger


def business():
    return {'feature_ids': ['m_0_0', 'm_0_1', 'm_1_0'], 'explanation': 'Synthetic fixture only.'}


def envelope(payload=None, name='submit_basis'):
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
        'tool_calls': [{'index': 0, 'id': 'call-1', 'type': 'function',
                        'function': {'name': name, 'arguments': json.dumps(payload or business())}}]}}]}


class ContractTests(unittest.TestCase):
    def test_envelope_index_is_checked_before_projection(self):
        original = envelope()
        normalized = controller.normalize_envelope(original, 'submit_basis')
        self.assertNotIn('index', normalized['choices'][0]['message']['tool_calls'][0])
        self.assertEqual(original['choices'][0]['message']['tool_calls'][0]['index'], 0)
        for key, value in [('index', True), ('index', 1), ('unexpected', None)]:
            altered = copy.deepcopy(original)
            altered['choices'][0]['message']['tool_calls'][0][key] = value
            with self.assertRaises(ValueError):
                controller.normalize_envelope(altered, 'submit_basis')

    def test_multiple_choices_calls_or_wrong_finish_rejected(self):
        for change in ('choices', 'calls', 'finish'):
            value = envelope()
            if change == 'choices': value['choices'] *= 2
            elif change == 'calls': value['choices'][0]['message']['tool_calls'] *= 2
            else: value['choices'][0]['finish_reason'] = 'stop'
            with self.assertRaises(ValueError): controller.normalize_envelope(value, 'submit_basis')

    def test_policy_requires_exact_distinct_rule_ids_and_explanation(self):
        good = {'rule_ids': ['R01','R02','R03','R04'], 'explanation': 'Archive only.'}
        self.assertEqual(controller.validate_policy_business(good), good)
        for update in ({'rule_ids':['R01']*4}, {'rule_ids':['R01','R02','R03','R99']},
                       {'explanation': ''}, {'security_risk':'LOW'}, {'rule_ids':('R01','R02','R03','R04')}):
            with self.assertRaises(ValueError): controller.validate_policy_business(good | update)

    def test_duplicate_raw_policy_json_is_rejected(self):
        value = envelope(name='submit_policy')
        value['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = '{"rule_ids":["R01","R02","R03","R04"],"explanation":"a","explanation":"b"}'
        with self.assertRaises(ValueError): controller.parse_policy_response(value)

    def test_public_settings_do_not_contain_authentication(self):
        settings = controller.public_settings()
        self.assertNotIn('api_key', settings)
        self.assertEqual(settings['timeout'], 180)
        self.assertEqual(settings['num_retries'], 0)


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
            max_cost_cny=4, session_ids=['slot-a','slot-b'])
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def run_actor(self, reply=None, **kwargs):
        provider = controller.FakeProvider([reply or {'tool':'submit_basis','arguments':business()}])
        with patch('openhands.sdk.llm.llm.litellm_completion', provider):
            result = controller.run_session(self.root, self.root/'actor', 'slot-a',
                {'task':'synthetic', 'repair_policy':{'rule_ids':['R01','R02','R03','R04']}},
                self.ledger, self.settings, stage='actor', spec=make_spec(2,3), **kwargs)
        return result, provider

    def test_actual_conversation_basis_accepts_once_and_records_dispatch(self):
        result, provider = self.run_actor()
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(result['business'], business())
        self.assertEqual(result['compiled']['n_params'], 3)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.ledger.summary()['request_count'], 1)
        self.assertEqual(self.ledger.summary()['usage_unknown_count'], 0)
        self.assertTrue((self.root/'actor/sdk-dispatch.json').is_file())
        self.assertEqual(result['candidate_executions'], 0)
        request = json.loads((self.root/result['request']['path']).read_text())
        self.assertEqual(len(request['tools']), 1)
        self.assertEqual(set(request['tools'][0]['function']['parameters']['properties']), {'feature_ids','explanation'})

    def test_actual_conversation_policy_returns_only_frozen_library_rules(self):
        policy = {'rule_ids':['R02','R01','R05','R08'],'explanation':'Synthetic policy.'}
        provider = controller.FakeProvider([{'tool':'submit_policy','arguments':policy}])
        with patch('openhands.sdk.llm.llm.litellm_completion', provider):
            result = controller.run_session(self.root,self.root/'update','slot-a',{'history':'fixture'},
                self.ledger,self.settings,stage='update')
        self.assertEqual(result['status'],'accepted')
        self.assertEqual(result['business'],policy)
        self.assertEqual(result['policy']['rule_ids'],policy['rule_ids'])
        self.assertEqual(provider.calls,1)

    def test_template_capture_uses_actual_sdk_without_reservation(self):
        provider = controller.FakeProvider([])
        with patch('openhands.sdk.llm.llm.litellm_completion',provider):
            payload = controller.capture_request_template(self.root,self.root/'template','slot-a',
                {'task':'fixture'},self.ledger,self.settings,stage='actor',spec=make_spec(2,3))
        self.assertEqual(provider.calls,0)
        self.assertEqual(self.ledger.summary()['request_count'],0)
        self.assertEqual(payload['messages'][-1],{'role':'user','content':'{"task":"fixture"}'})

    def test_unadvertised_metadata_never_becomes_accepted(self):
        result,provider=self.run_actor({'tool':'submit_basis','arguments':business() | {'summary':'extra'}})
        self.assertEqual(result['status'],'error')
        self.assertIsNone(result['compiled'])
        self.assertEqual(provider.calls,1)

    def test_unknown_usage_stops_before_acceptance(self):
        result,provider=self.run_actor({'tool':'submit_basis','arguments':business(),'usage':None})
        self.assertEqual(result['status'],'error')
        self.assertIsNone(result['compiled'])
        self.assertEqual(provider.calls,1)
        self.assertEqual(self.ledger.summary()['usage_unknown_count'],1)

    def test_duplicate_business_keys_rejected_before_sdk_action(self):
        raw = '{"feature_ids":["m_0_0","m_0_1","m_1_0"],"explanation":"x","explanation":"y"}'
        result,provider=self.run_actor({'tool':'submit_basis','arguments':raw})
        self.assertEqual(result['status'],'error')
        self.assertIsNone(result['compiled'])
        self.assertEqual(provider.calls,1)

    def test_provider_failure_is_once_and_usage_unknown(self):
        result,provider=self.run_actor({'raise':RuntimeError('Synthetic transport failure')})
        self.assertEqual(result['status'],'error')
        self.assertEqual(provider.calls,1)
        self.assertEqual(self.ledger.summary()['usage_unknown_count'],1)

    def test_callback_failure_consumes_session_without_repair(self):
        count=[]
        def fail(value):
            count.append(value)
            raise RuntimeError('Synthetic host failure')
        result,provider=self.run_actor(accept_callback=fail)
        self.assertEqual(result['status'],'error')
        self.assertEqual(len(count),1)
        self.assertEqual(provider.calls,1)

    def test_existing_output_and_wrong_settings_refuse_before_call(self):
        (self.root/'actor').mkdir()
        with self.assertRaises(FileExistsError): self.run_actor()
        self.assertEqual(self.ledger.summary()['request_count'],0)
        settings=self.settings | {'num_retries':1}
        with self.assertRaises(ValueError):
            controller.run_session(self.root,self.root/'other','slot-a',{},self.ledger,settings,stage='actor',spec=make_spec(2,3))
        self.assertEqual(self.ledger.summary()['request_count'],0)


if __name__ == '__main__':
    unittest.main()
