"""One-step strategy SDK interface: one advertised and accepted business tool.

Only provider responses are fabricated; SDK construction, dispatch and strict
acceptance remain real. No candidate execution or real network is permitted.
"""
import copy
import json
import logging
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
from tests import test_strategy_sdk_contract as contract
from tests import test_strategy_pair_audit as audit_fixture

ROOT = Path(__file__).resolve().parents[1]
if contract.SDK:
    from litellm.types.utils import ModelResponse
    from rsi_eval import strategy_pair_agent as agent


@unittest.skipUnless(contract.SDK, 'Requires installed server OpenHands SDK 1.55.1')
class SingleToolSDKTests(contract.ContractFixtures):
    bound = contract.SDKContractTests.bound

    def setUp(self):
        super().setUp()
        level = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, level)
        for target in ('socket.socket.connect', 'socket.create_connection'):
            block = patch(target, side_effect=AssertionError('No network in single-tool tests'))
            block.start()
            self.addCleanup(block.stop)

    @staticmethod
    def call(name, value, identifier='business-call'):
        return dict(id=identifier, type='function', function=dict(name=name, arguments=json.dumps(value)))

    def response(self, calls):
        return ModelResponse(id='single-tool-response', model='minimax-m3',
            choices=[dict(finish_reason='tool_calls', message=dict(role='assistant', content='Offline only', tool_calls=calls))],
            usage=dict(prompt_tokens=100, completion_tokens=20, total_tokens=120))

    def run_calls(self, stage, calls):
        c, llm, ledger = self.bound(stage)
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=self.response(calls)):
            result = agent.run_session(c, llm, c.slot_id, c.output_dir)
        return c, ledger, result

    def assert_rejected_without_partial_acceptance(self, c, ledger, result):
        self.assertEqual(result['status'], 'error', result)
        self.assertEqual(ledger.summary()['request_count'], 1)
        self.assertIsNotNone(result['response'])
        self.assertEqual(c.status, 'pending')
        for name in ('sdk-submission.json', 'acceptance-attempt.json', 'submission.json', 'source.py', 'policy.json'):
            self.assertFalse((c.output_dir/name).exists(), name)
        events = [json.loads(line) for line in (c.output_dir/'events.jsonl').read_text().splitlines()]
        self.assertFalse(any(event['type'] in ('ActionEvent', 'ObservationEvent') for event in events))
        self.assertEqual(c.summary()['candidate_executions'], 0)

    def test_actual_sdk_capture_advertises_only_the_stage_business_tool(self):
        for stage, name in (('update','submit_policy'), ('actor','submit_candidate')):
            with self.subTest(stage=stage):
                c, llm, ledger = self.bound(stage)
                with patch('openhands.sdk.llm.llm.litellm_completion', side_effect=AssertionError('No provider in capture')):
                    template = agent.prepare_request_template(c, llm, c.slot_id, c.output_dir)
                self.assertEqual([t['function']['name'] for t in template['tools']], [name])
                self.assertEqual(llm._pilot_allowed_tools, {name})
                self.assertIsNone(template['tool_choice'])
                self.assertEqual(ledger.summary()['request_count'], 0)

    def test_single_business_call_accepts_with_optional_metadata_and_no_finish(self):
        for stage, name in (('update','submit_policy'), ('actor','submit_candidate')):
            for metadata in ({}, {'summary': None}, {'summary':'Archive only', 'security_risk':'LOW'}):
                with self.subTest(stage=stage, metadata=metadata):
                    business = self.business(stage)
                    c, ledger, result = self.run_calls(stage, [self.call(name, business | metadata)])
                    self.assertEqual(result['status'], 'accepted', result)
                    self.assertEqual(result['version'], 'strategy-pair-agent-v0.2')
                    request = json.loads((ROOT/result['request']['path']).read_bytes())
                    self.assertEqual([t['function']['name'] for t in request['tools']], [name])
                    receipt = json.loads((ROOT/result['sdk_submission']['path']).read_bytes())
                    self.assertEqual(receipt['business'], business)
                    events = [json.loads(line) for line in (c.output_dir/'events.jsonl').read_text().splitlines()]
                    self.assertEqual([e['tool_name'] for e in events if e['type']=='ActionEvent'], [name])
                    self.assertEqual([e['tool_name'] for e in events if e['type']=='ObservationEvent'], [name])
                    self.assertEqual(ledger.summary()['request_count'], 1)
                    self.assertEqual(c.summary()['candidate_executions'], 0)

    def test_finish_only_is_refused_without_partial_acceptance(self):
        for stage in ('update','actor'):
            with self.subTest(stage=stage):
                self.assert_rejected_without_partial_acceptance(*self.run_calls(stage,
                    [self.call('finish', {'message':'Done', 'summary':'End'})]))

    def test_business_finish_orders_two_business_calls_and_wrong_tool_are_refused(self):
        for stage, name, wrong in (('update','submit_policy','submit_candidate'), ('actor','submit_candidate','submit_policy')):
            business = self.call(name, self.business(stage))
            finish = self.call('finish', {'message':'Done'}, 'finish-call')
            cases = {'business_then_finish':[business,finish], 'finish_then_business':[finish,business],
                'two_business':[business, business | {'id':'second-business'}],
                'wrong_tool':[self.call(wrong, self.business(stage))]}
            for case, calls in cases.items():
                with self.subTest(stage=stage, case=case):
                    self.assert_rejected_without_partial_acceptance(*self.run_calls(stage, calls))

    def test_malformed_metadata_remains_fatal_before_sdk_dispatch(self):
        for stage, name in (('update','submit_policy'), ('actor','submit_candidate')):
            for malformed in ({'summary':True}, {'security_risk':None}, {'security_risk':'invalid'}):
                with self.subTest(stage=stage, malformed=malformed):
                    self.assert_rejected_without_partial_acceptance(*self.run_calls(stage,
                        [self.call(name, self.business(stage) | malformed)]))

    def test_tampered_capture_or_send_tool_table_is_refused_before_reservation(self):
        original = agent.wire_payload
        def extra_tool(*args, **kwargs):
            payload = original(*args, **kwargs)
            payload['tools'] = copy.deepcopy(payload['tools']) + [dict(type='function',function=dict(name='finish'))]
            return payload
        for stage in ('update','actor'):
            for capture in (True, False):
                with self.subTest(stage=stage, capture=capture):
                    c, llm, ledger = self.bound(stage)
                    with patch.object(agent, 'wire_payload', side_effect=extra_tool), \
                         patch('openhands.sdk.llm.llm.litellm_completion', side_effect=AssertionError('Provider must not run')):
                        if capture:
                            with self.assertRaises(Exception):
                                agent.prepare_request_template(c, llm, c.slot_id, c.output_dir)
                            self.assertIsNone(llm._captured_payload)
                        else:
                            result = agent.run_session(c, llm, c.slot_id, c.output_dir)
                            self.assertEqual(result['status'], 'error')
                    self.assertEqual(ledger.summary()['request_count'], 0)
                    self.assertFalse((c.output_dir/'acceptance-attempt.json').exists())

    def test_original_measured_v02_seventh_response_still_rejects_without_retroactive_acceptance(self):
        directory = ROOT/'artifacts/strategy-measured/2026-10-21/v02/raw/experiment/sessions/r1-selection-S-select-1-updated'
        response_path = directory/'requests/request-0007.response.json'
        packet_path = directory/'requests/packet.json'
        before = {p:p.read_bytes() for p in (response_path,packet_path)}
        saved = json.loads(before[response_path])
        c, llm, ledger = self.bound('actor')
        # The original two-call response is rejected before source/state semantics;
        # retain its full bytes as the transport fixture and never execute it.
        response = ModelResponse(id=saved['response_id'], model='minimax-m3',
            choices=copy.deepcopy(saved['choices']), usage=saved['usage'])
        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=response):
            result = agent.run_session(c, llm, c.slot_id, c.output_dir)
        self.assert_rejected_without_partial_acceptance(c, ledger, result)
        self.assertEqual(result['sdk_error_codes'], ['PilotResponseContractError'])
        self.assertEqual({p:p.read_bytes() for p in before}, before)


class SingleToolAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        audit_fixture.SessionAuditTests.setUpClass()

    def fixture(self, stage, version, single_tool=True):
        fixture = audit_fixture.SessionAuditTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        original_reserve = audit_fixture.StrategyPairBudgetLedger.reserve
        original_write = fixture.write
        def reserve(ledger, slot, request, output):
            if single_tool and 'tools' in request:
                request['tools'] = [t for t in request['tools'] if t['function']['name']!='finish']
            return original_reserve(ledger, slot, request, output)
        def write(name, value):
            if name=='transport-settings.json':
                value = value | {'version':version}
            return original_write(name,value)
        with patch.object(audit_fixture.StrategyPairBudgetLedger,'reserve',new=reserve), \
             patch.object(fixture,'write',side_effect=write):
            business = fixture.metadata_fixture(stage, 'single-tool')
        fixture.result['version'] = version
        fixture.write('session-summary.json', fixture.result)
        return fixture, business

    @staticmethod
    def verify_current(fixture):
        # Current mode is a host default, never inferred from mutable records.
        return audit_fixture.audit.verify_session(ROOT,fixture.slot,fixture.packet,
            fixture.result,fixture.ledger_path)

    def test_new_single_tool_bound_audit_accepts_legal_metadata_without_execution(self):
        for stage in ('update','actor'):
            with self.subTest(stage=stage):
                fixture, business = self.fixture(stage,'strategy-pair-agent-v0.2')
                fixture.rebind_raw_arguments(json.dumps(business | {'summary':None,'security_risk':'LOW'}))
                self.assertEqual(self.verify_current(fixture)['status'],'passed')
                self.assertEqual(fixture.result['controller']['candidate_executions'],0)

    def test_audit_rejects_version_tool_table_mismatch_and_unknown_version(self):
        for stage in ('update','actor'):
            for version,single in (('strategy-pair-agent-v0.2',False),
                    ('strategy-pair-agent-v0.1',True),('strategy-pair-agent-v0.1',False),
                    ('strategy-pair-agent-v99',True)):
                with self.subTest(stage=stage, version=version, single=single):
                    fixture,_ = self.fixture(stage,version,single)
                    with self.assertRaises(ValueError):
                        self.verify_current(fixture)

    def test_new_single_tool_audit_rejects_invalid_metadata_with_rebound_hashes(self):
        for stage in ('update','actor'):
            for metadata in ({'summary':7},{'security_risk':None}):
                with self.subTest(stage=stage, metadata=metadata):
                    fixture,business = self.fixture(stage,'strategy-pair-agent-v0.2')
                    fixture.rebind_raw_arguments(json.dumps(business | metadata))
                    with self.assertRaisesRegex(ValueError,'SDK summary|SDK security_risk'):
                        self.verify_current(fixture)


if __name__=='__main__':
    unittest.main()
