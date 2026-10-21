"""Regression boundary: advertised SDK metadata must survive strict acceptance.

All SDK calls use a fake provider; socket access is forbidden. No candidate is
executed and no real policy is created. The measured response is an immutable
fixture, never a recovery or acceptance in its original experiment.
"""
import copy
import importlib.util
import json
import logging
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
ROOT = Path(__file__).resolve().parents[1]
from rsi_eval.strategy_pair_controller import StrategyPairController
from rsi_eval.strategy_learning import build_learning_package, render_update_packet
from tests.test_strategy_pair_agent import actor_packet

try:
    SDK = importlib.util.find_spec('openhands.sdk') is not None
except ModuleNotFoundError:
    SDK = False
if SDK:
    from litellm.types.utils import ModelResponse
    from rsi_eval import strategy_pair_agent as agent
    from rsi_eval.pilot_budget import BudgetLedger


class ContractFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packets = {'actor': actor_packet(),
            'update': render_update_packet(ROOT, build_learning_package(ROOT))}

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT/'tmp')
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        self.index = 0

    def controller(self, stage):
        self.index += 1
        slot = 'r1-update-updated' if stage == 'update' else 'r1-selection-P-select-1-fixed'
        return StrategyPairController(ROOT, self.packets[stage], slot,
            self.output/str(self.index))

    @staticmethod
    def business(stage):
        return (dict(rule_1='R01', rule_2='R02', rule_3='R05', rule_4='R08', explanation='')
            if stage == 'update' else dict(source='def get_plan(x): return []\n', n_params=0, explanation=''))


class RawContractTests(ContractFixtures):
    def test_metadata_is_validated_then_projected_out_of_business_for_both_stages(self):
        for stage in ('update', 'actor'):
            c, expected = self.controller(stage), self.business(stage)
            variants = [{}, {'summary': 'Archive one proposal'}, {'summary': None},
                {'security_risk': 'UNKNOWN'}, {'summary': '', 'security_risk': 'LOW'},
                {'summary': None, 'security_risk': 'MEDIUM'}, {'security_risk': 'HIGH'}]
            for metadata in variants:
                with self.subTest(stage=stage, metadata=metadata):
                    value = expected | metadata
                    self.assertEqual(c.validate_arguments(json.dumps(value)), expected)
                    self.assertEqual(c.validate_arguments(value), expected)
                    self.assertEqual(value, expected | metadata)

    def test_invalid_metadata_unknown_fields_and_coercions_are_rejected(self):
        invalid = [{'summary': 1}, {'summary': True}, {'summary': []},
            {'summary': {}}, {'security_risk': None}, {'security_risk': 0},
            {'security_risk': True}, {'security_risk': 'low'}, {'security_risk': 'INVALID'},
            {'security_risk': ['LOW']}, {'unexpected': 'never discard'}, {'kind': 'Action'}]
        for stage in ('update', 'actor'):
            c, expected = self.controller(stage), self.business(stage)
            for changes in invalid:
                with self.subTest(stage=stage, changes=changes), self.assertRaises(ValueError):
                    c.validate_arguments(json.dumps(expected | changes))

    def test_duplicate_business_and_metadata_keys_are_rejected_before_projection(self):
        for stage in ('update', 'actor'):
            c = self.controller(stage)
            raw = json.dumps(self.business(stage) | {'summary': None, 'security_risk': 'LOW'})
            for extra in ('"summary":"other"', '"security_risk":"HIGH"',
                          '"explanation":"other"'):
                with self.subTest(stage=stage, extra=extra), self.assertRaises(ValueError):
                    c.validate_arguments(raw[:-1]+','+extra+'}')

    def test_business_constraints_are_not_weakened_by_valid_metadata(self):
        for stage in ('update', 'actor'):
            c, expected = self.controller(stage), self.business(stage)
            bad = ([{'rule_1': True}, {'rule_1': 'R99'}, {'rule_2': 'R01'}]
                if stage == 'update' else [{'source': ' '}, {'source': 5}, {'n_params': True},
                    {'n_params': 0.0}, {'n_params': '0'}, {'n_params': 1}, {'source': '中'*5462}])
            bad += [{'explanation': '中'*1366}, {'explanation': None}]
            for changes in bad:
                with self.subTest(stage=stage, fields=list(changes)), self.assertRaises(ValueError):
                    c.validate_arguments(json.dumps(expected | changes | {'summary': 'Valid', 'security_risk': 'LOW'}))
            missing = dict(expected)
            del missing['rule_1' if stage == 'update' else 'source']
            with self.subTest(stage=stage, case='missing'), self.assertRaises(ValueError):
                c.validate_arguments(json.dumps(missing | {'summary': None}))

    def test_nonfinite_and_nonobject_json_cannot_be_hidden_as_metadata(self):
        for stage in ('update', 'actor'):
            c = self.controller(stage)
            for raw in ('[]', 'null', 'true', json.dumps(self.business(stage))[:-1]+',"summary":NaN}'):
                with self.subTest(stage=stage, raw=raw), self.assertRaises(ValueError):
                    c.validate_arguments(raw)


@unittest.skipUnless(SDK, 'Requires installed server OpenHands SDK 1.55.1')
class SDKContractTests(ContractFixtures):
    def setUp(self):
        super().setUp()
        level = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, level)
        for target in ('socket.socket.connect', 'socket.create_connection'):
            p = patch(target, side_effect=AssertionError('Network forbidden in SDK contract tests'))
            p.start()
            self.addCleanup(p.stop)

    def bound(self, stage):
        c = self.controller(stage)
        ledger = BudgetLedger(c.output_dir/'ledger.json', session_ids=[c.slot_id], max_requests=1,
            max_requests_per_session=1, max_output_tokens=8192, max_input_bytes=98304,
            max_reserved_tokens=200000, max_cost_cny=2)
        llm = agent.make_llm(dict(model='anthropic/MiniMax-M3', api_key='offline-placeholder',
            base_url='https://example.invalid', reasoning_effort='none'), c, ledger)
        return c, llm, ledger

    def run_fake(self, stage, args, fixture=None):
        c, llm, ledger = self.bound(stage)
        name = 'submit_policy' if stage == 'update' else 'submit_candidate'
        response = fixture or ModelResponse(id='response-contract-fixture', model='minimax-m3',
            choices=[dict(finish_reason='tool_calls', message=dict(role='assistant', content='Offline only',
                tool_calls=[dict(id='call-contract', type='function', function=dict(name=name,
                    arguments=args if isinstance(args, str) else json.dumps(args)))]))],
            usage=dict(prompt_tokens=100, completion_tokens=20, total_tokens=120))
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=response):
            result = agent.run_session(c, llm, c.slot_id, c.output_dir)
        return c, ledger, result

    def test_actual_sdk_accepts_declared_metadata_and_preserves_business_both_stages(self):
        for stage in ('update', 'actor'):
            for metadata in ({}, {'summary': None}, {'security_risk': 'UNKNOWN'},
                             {'summary': 'Archive proposal', 'security_risk': 'HIGH'}):
                with self.subTest(stage=stage, metadata=metadata):
                    expected = self.business(stage)
                    c, ledger, result = self.run_fake(stage, expected | metadata)
                    self.assertEqual(result['status'], 'accepted', result)
                    receipt = json.loads((ROOT/result['sdk_submission']['path']).read_bytes())
                    self.assertEqual(receipt['business'], expected)
                    self.assertEqual(ledger.summary()['request_count'], 1)
                    self.assertEqual(c.summary()['candidate_executions'], 0)
                    if stage == 'actor':
                        self.assertEqual((c.output_dir/'source.py').read_bytes(), expected['source'].encode())
                    else:
                        self.assertEqual(result['policy']['rule_ids'], ['R01', 'R02', 'R05', 'R08'])

    def test_actual_sent_schema_resolves_metadata_references_and_preserves_constraints(self):
        from jsonschema import Draft202012Validator
        for stage in ('update', 'actor'):
            c, llm, ledger = self.bound(stage)
            with patch('openhands.sdk.llm.llm.litellm_completion', side_effect=AssertionError('Provider forbidden')):
                template = agent.prepare_request_template(c, llm, c.slot_id, c.output_dir)
            name = 'submit_policy' if stage == 'update' else 'submit_candidate'
            schema = next(t['function']['parameters'] for t in template['tools'] if t['function']['name'] == name)
            validator = Draft202012Validator(schema)
            validator.check_schema(schema)
            with self.subTest(stage=stage):
                self.assertNotIn('$ref', json.dumps(schema))
                self.assertEqual(schema['properties']['security_risk']['enum'], ['UNKNOWN', 'LOW', 'MEDIUM', 'HIGH'])
                self.assertNotIn('summary', schema['required'])
                self.assertNotIn('security_risk', schema['required'])
                self.assertNotIn('kind', schema['properties'])
                self.assertFalse(schema['additionalProperties'])
                for metadata in ({}, {'summary': None}, {'summary': 'Archive', 'security_risk': 'LOW'}):
                    validator.validate(self.business(stage) | metadata)
                for changes in ({'summary': 7}, {'security_risk': 'INVALID'}, {'extra': 1},
                                {'explanation': 'x'*4097}):
                    self.assertFalse(validator.is_valid(self.business(stage) | changes))
                self.assertEqual(ledger.summary()['request_count'], 0)

    def test_actual_measured_response_replays_as_synthetic_acceptance_without_editing_it(self):
        path = ROOT/'artifacts/strategy-measured/2026-10-21/v01/raw/experiment/sessions/r1-update-updated/requests/request-0001.response.json'
        original = path.read_bytes()
        saved = json.loads(original)
        fixture = ModelResponse(id=saved['response_id'], model='minimax-m3',
            choices=copy.deepcopy(saved['choices']), usage=saved['usage'])
        c, ledger, result = self.run_fake('update', None, fixture)
        self.assertEqual(result['status'], 'accepted', result)
        self.assertEqual(result['policy']['rule_ids'], ['R01', 'R02', 'R05', 'R08'])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(c.summary()['candidate_executions'], 0)
        self.assertEqual(ledger.summary()['request_count'], 1)

    def test_invalid_raw_metadata_is_stopped_before_sdk_acceptance_for_both_stages(self):
        for stage in ('update', 'actor'):
            base = self.business(stage)
            cases = [json.dumps(base | changes) for changes in
                ({'summary': 42}, {'security_risk': None}, {'security_risk': 'invalid'},
                 {'unexpected': 1}, {'kind': 'Action'})]
            cases += [json.dumps(base | {'summary': None})[:-1]+',"summary":"duplicate"}',
                      json.dumps(base | {'security_risk': 'LOW'})[:-1]+',"security_risk":"HIGH"}']
            for raw in cases:
                with self.subTest(stage=stage, raw=raw):
                    c, ledger, result = self.run_fake(stage, raw)
                    self.assertEqual(result['status'], 'error')
                    self.assertIsNotNone(result['response'])
                    self.assertFalse((c.output_dir/'sdk-submission.json').exists())
                    self.assertFalse((c.output_dir/'acceptance-attempt.json').exists())
                    self.assertEqual(ledger.summary()['request_count'], 1)
                    self.assertEqual(c.summary()['candidate_executions'], 0)


if __name__ == '__main__':
    unittest.main()
