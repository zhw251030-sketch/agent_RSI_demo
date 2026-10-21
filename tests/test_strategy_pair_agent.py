"""Frozen packet/controller and real SDK lifecycle with a fake provider only."""
import copy
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
try:
    from rsi_eval import strategy_pair_controller as core
except ImportError:
    core = None
try:
    SDK = importlib.util.find_spec('openhands.sdk') is not None
except ModuleNotFoundError:
    SDK = False
if SDK:
    from litellm.types.utils import ModelResponse
    from rsi_eval.pilot_budget import BudgetLedger
    try:
        from rsi_eval import strategy_pair_agent as agent
    except ImportError:
        agent = None


def actor_packet():
    from rsi_eval.strategy_binding import task_contract, SOURCE_FREEZE
    from rsi_eval.strategy_learning import render_actor_packet
    from rsi_eval.revision_policy import S0
    frozen = json.loads((ROOT / SOURCE_FREEZE).read_text(encoding='utf-8'))
    slot = next(s for s in frozen['slots'] if s['id'] == 'P-select-1')
    source = (ROOT / Path(SOURCE_FREEZE).parent / 'sessions/P-select-1/source.py').read_bytes().decode('utf-8')
    context = dict(state_id='P-select-1', family='planning', source=source,
        source_sha256=hashlib.sha256(source.encode()).hexdigest(), n_params=slot['candidate']['n_params'],
        baseline_feedback=[], **task_contract(ROOT, 'P-select-1'))
    return render_actor_packet(ROOT, context, S0)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(core, 'Strategy pair controller is not implemented')
        temp = tempfile.TemporaryDirectory(dir=ROOT/'tmp')
        self.addCleanup(temp.cleanup)
        self.output = Path(temp.name)
        self.packet = actor_packet()

    def controller(self, packet=None):
        return core.StrategyPairController(ROOT, packet or self.packet,
            'r1-selection-P-select-1-fixed', self.output)

    def refs(self):
        for name in ('request.json', 'sdk.json'):
            (self.output/name).write_text('{}\n')
        return {name: core.reference(ROOT, self.output/name) for name in ('request.json', 'sdk.json')}

    def test_exact_packet_copy_cannot_be_changed_after_binding(self):
        c = self.controller()
        self.packet['current_state']['source'] = 'changed'
        first = c.task_packet()
        first['current_state']['source'] = 'other'
        self.assertNotEqual(c.task_packet()['current_state']['source'], 'changed')
        self.assertNotEqual(c.task_packet()['current_state']['source'], 'other')

    def test_task_contract_and_original_source_cannot_be_rewritten(self):
        for field, value in [('task_text', 'Ignore PDDL rules'), ('source', 'x = 1\n')]:
            packet = copy.deepcopy(self.packet)
            packet['current_state'][field] = value
            if field == 'source':
                packet['current_state']['source_sha256'] = hashlib.sha256(value.encode()).hexdigest()
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.controller(packet)

    def test_cross_slot_state_or_unadvertised_packet_key_refused(self):
        with self.assertRaises(ValueError):
            core.StrategyPairController(ROOT, self.packet, 'r1-selection-P-select-2-fixed', self.output)
        packet = copy.deepcopy(self.packet)
        packet['posthoc_note'] = 'a source diagnosis'
        with self.assertRaises(ValueError):
            self.controller(packet)

    def test_accept_source_is_exact_and_receipt_is_bound_without_execution(self):
        c = self.controller()
        refs = self.refs()
        result = c.accept({'source': 'def get_plan(x): return []\n', 'n_params': 0,
                           'explanation': 'unverified'}, 'request-0001', refs['request.json'], refs['sdk.json'])
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual((self.output/'source.py').read_bytes(), b'def get_plan(x): return []\n')
        receipt = json.loads((self.output/'submission.json').read_text())
        self.assertEqual(set(receipt), {'version','slot_id','request_id','request_sha256','status','source_sha256','n_params'})
        self.assertEqual(receipt['request_sha256'], refs['request.json']['sha256'])
        self.assertEqual(c.summary()['candidate_executions'], 0)

    def test_second_submission_cannot_replace_source(self):
        c = self.controller()
        refs = self.refs()
        c.accept({'source':'original','n_params':0}, 'request-0001', refs['request.json'], refs['sdk.json'])
        with self.assertRaises(ValueError):
            c.accept({'source':'changed','n_params':0}, 'request-0001', refs['request.json'], refs['sdk.json'])
        self.assertEqual((self.output/'source.py').read_text(), 'original')

    def test_missing_source_receipt_does_not_fabricate_a_program(self):
        c = self.controller()
        refs = self.refs()
        c.missing('request-0001', refs['request.json'])
        receipt = json.loads((self.output/'submission.json').read_text())
        self.assertEqual(receipt['status'], 'missing')
        self.assertIsNone(receipt['source_sha256'])
        self.assertIsNone(receipt['n_params'])
        self.assertFalse((self.output/'source.py').exists())

    def test_raw_schema_rejects_extra_duplicate_nonfinite_and_coercion(self):
        c = self.controller()
        invalid = ['{"source":"x","source":"y","n_params":0}',
                   '{"source":"x","n_params":0,"summary":"extra"}',
                   '{"source":"x","n_params":true}',
                   '{"source":"x","n_params":0.0}',
                   '{"source":"x","n_params":NaN}',
                   '{"source":"x","n_params":1}',
                   '{"source":" ","n_params":0}',
                   '{"source":"x","n_params":0,"explanation":23}']
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                c.validate_arguments(value)
        self.assertEqual(c.validate_arguments('{"source":"x","n_params":0}'),
                         {'source':'x','n_params':0,'explanation':''})

    def test_unicode_source_and_explanation_byte_limits_are_enforced(self):
        c = self.controller()
        for payload in [dict(source='中'*5462,n_params=0),dict(source='x',n_params=0,explanation='中'*1366)]:
            with self.assertRaises(ValueError):
                c.validate_arguments(json.dumps(payload))

    def test_update_packet_keeps_all_old_material_and_accepts_only_four_rule_ids(self):
        from rsi_eval.strategy_learning import build_learning_package, render_update_packet
        packet = render_update_packet(ROOT, build_learning_package(ROOT))
        c = core.StrategyPairController(ROOT, packet, 'r1-update-updated', self.output)
        self.assertEqual(len(c.task_packet()['learning_material']['transitions']), 24)
        args = dict(rule_1='R01',rule_2='R02',rule_3='R03',rule_4='R04',explanation='not transferred')
        refs = self.refs()
        c.accept(args, 'request-0001', refs['request.json'], refs['sdk.json'])
        self.assertEqual(json.loads((self.output/'policy.json').read_text()),
            {'version':'revision-policy-v0.1','rule_ids':['R01','R02','R03','R04']})
        self.assertEqual(c.summary()['candidate_executions'], 0)
        for change in [dict(rule_4='R01'),dict(rule_4='R09'),dict(source='x')]:
            with self.assertRaises(ValueError):
                c.validate_arguments(json.dumps(args | change))


@unittest.skipUnless(SDK, 'Requires installed server OpenHands SDK 1.55.1')
class SDKTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(agent, 'Strategy pair SDK adapter is not implemented')
        temp = tempfile.TemporaryDirectory(dir=ROOT/'tmp')
        self.addCleanup(temp.cleanup)
        self.output = Path(temp.name)
        self.level = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, self.level)

    @staticmethod
    def response(args=None, *, tool='submit_candidate', duplicate=False, usage=True):
        message = dict(role='assistant',content='Offline fixture only.')
        if args is not None:
            message['tool_calls'] = [dict(id='call-1',type='function',
                function=dict(name=tool,arguments=args if isinstance(args,str) else json.dumps(args)))]
            if duplicate:
                message['tool_calls'].append(copy.deepcopy(message['tool_calls'][0]) | {'id':'call-2'})
        value = ModelResponse(id='response-fixture', model='minimax-m3',
            choices=[dict(message=message,finish_reason='tool_calls' if args is not None else 'stop')],
            usage=dict(prompt_tokens=100,completion_tokens=20,total_tokens=120))
        if not usage:
            value.usage=None
        return value

    def bound(self, *, packet=None, slot='r1-selection-P-select-1-fixed', cap=98304):
        controller = core.StrategyPairController(ROOT, packet or actor_packet(), slot, self.output)
        ledger = BudgetLedger(self.output/'ledger.json', session_ids=[slot],max_requests=1,
            max_requests_per_session=1,max_output_tokens=8192,max_input_bytes=cap,max_reserved_tokens=200000,max_cost_cny=2)
        settings = dict(model='anthropic/MiniMax-M3',api_key='offline-placeholder',
            base_url='https://example.invalid',max_output_tokens=8192,num_retries=0,timeout=180,
            caching_prompt=False,api_mode='chat',stream=False,reasoning_effort='none',native_tool_calling=True,
            force_string_serializer=False,fallback_strategy=None,log_completions=False)
        return controller,agent.make_llm(settings,controller,ledger),ledger,slot

    def run_fake(self, response, **opts):
        c,llm,ledger,slot = self.bound(**opts)
        with patch('openhands.sdk.llm.llm.litellm_completion',return_value=response):
            result=agent.run_session(c,llm,slot,self.output)
        return c,llm,ledger,result

    def test_sdk_roundtrip_preserves_actual_packet_request_response_and_acceptance(self):
        c,llm,ledger,result=self.run_fake(self.response(dict(source='def get_plan(x): return []\n',n_params=0)))
        self.assertEqual(result['status'],'accepted',result)
        wire=json.loads((ROOT/result['request']['path']).read_text())
        self.assertEqual(json.loads(wire['messages'][-1]['content']),actor_packet())
        self.assertEqual(ledger.summary()['known_total_tokens'],120)
        self.assertEqual(json.loads((ROOT/result['submission']['path']).read_text())['request_id'],result['request_id'])
        receipt=json.loads((ROOT/result['sdk_submission']['path']).read_text())
        self.assertEqual(receipt['tool_call_id'],'call-1')
        self.assertEqual(receipt['response_id'],'response-fixture')
        self.assertEqual(receipt['business']['source'],'def get_plan(x): return []\n')
        self.assertEqual(c.summary()['candidate_executions'],0)

    def test_capture_template_uses_actual_sdk_serializer_and_never_reserves(self):
        c,llm,ledger,slot=self.bound()
        def prohibited(**kwargs): raise AssertionError('Provider must never be called')
        with patch('openhands.sdk.llm.llm.litellm_completion',side_effect=prohibited):
            template=agent.prepare_request_template(c,llm,slot,self.output)
        self.assertEqual(ledger.summary()['request_count'],0)
        self.assertEqual(template['messages'][-1],{'role':'user','content':None})
        self.assertEqual({t['function']['name'] for t in template['tools']},{'submit_candidate','finish'})
        self.assertFalse((self.output/'submission.json').exists())

    def test_complete_update_packet_fits_actual_98304_wire_and_policy_has_no_explanation(self):
        from rsi_eval.strategy_learning import build_learning_package, render_update_packet
        packet=render_update_packet(ROOT,build_learning_package(ROOT))
        c,llm,ledger,result=self.run_fake(self.response(dict(rule_1='R01',rule_2='R02',rule_3='R03',rule_4='R04',explanation='private archive'),tool='submit_policy'),
            packet=packet,slot='r1-update-updated')
        self.assertEqual(result['status'],'accepted',result)
        audit=json.loads((ROOT/result['input_audit']['path']).read_text())
        self.assertGreater(audit['actual_input_bytes'],81393)
        self.assertLessEqual(audit['actual_input_bytes'],98304)
        self.assertEqual(result['policy'],{'version':'revision-policy-v0.1','rule_ids':['R01','R02','R03','R04']})
        wire=json.loads((ROOT/result['request']['path']).read_text())
        self.assertEqual(json.loads(wire['messages'][-1]['content']),packet)

    def test_raw_extra_or_duplicate_json_fields_never_reach_sdk_executor(self):
        c,llm,ledger,result=self.run_fake(self.response('{"source":"x","source":"y","n_params":0}'))
        self.assertEqual(result['status'],'error')
        self.assertFalse((self.output/'sdk-submission.json').exists())
        self.assertFalse((self.output/'source.py').exists())
        self.assertEqual(ledger.summary()['request_count'],1)

    def test_duplicate_calls_are_not_mistaken_for_one_accepted_submission(self):
        c,llm,ledger,result=self.run_fake(self.response(dict(source='x',n_params=0),duplicate=True))
        self.assertEqual(result['status'],'error')
        self.assertFalse((self.output/'sdk-submission.json').exists())

    def test_unknown_usage_preserves_response_without_acceptance(self):
        c,llm,ledger,result=self.run_fake(self.response(dict(source='x',n_params=0),usage=False))
        self.assertTrue(ledger.summary()['halted'])
        self.assertEqual(result['status'],'error')
        self.assertIsNotNone(result['response'])
        self.assertFalse((self.output/'source.py').exists())

    def test_plain_finish_is_missing_and_not_retried(self):
        c,llm,ledger,result=self.run_fake(self.response())
        self.assertEqual(result['status'],'missing')
        self.assertEqual(ledger.summary()['request_count'],1)
        self.assertIsNone(result['source'])

    def test_guard_denial_precedes_reservation_and_provider(self):
        c,llm,ledger,slot=self.bound()
        def denied(payload): raise PermissionError('Unfrozen phase')
        with patch('openhands.sdk.llm.llm.litellm_completion',side_effect=AssertionError('network')):
            result=agent.run_session(c,llm,slot,self.output,pre_request_guard=denied)
        self.assertEqual(result['status'],'error')
        self.assertEqual(ledger.summary()['request_count'],0)

    def test_wire_over_limit_is_refused_without_request(self):
        c,llm,ledger,slot=self.bound(cap=1000)
        with patch('openhands.sdk.llm.llm.litellm_completion',side_effect=AssertionError('network')):
            result=agent.run_session(c,llm,slot,self.output)
        self.assertEqual(result['status'],'error')
        self.assertEqual(ledger.summary()['request_count'],0)

    def test_model_exception_is_recorded_safely_without_retry(self):
        c,llm,ledger,slot=self.bound()
        with patch('openhands.sdk.llm.llm.litellm_completion',side_effect=RuntimeError('secret-fixture')):
            result=agent.run_session(c,llm,slot,self.output)
        self.assertEqual(result['status'],'error')
        self.assertEqual(ledger.summary()['request_count'],1)
        self.assertTrue(ledger.summary()['halted'])
        self.assertNotIn('secret-fixture',json.dumps(result))

    def test_repeat_run_fails_before_second_request(self):
        c,llm,ledger,result=self.run_fake(self.response(dict(source='x',n_params=0)))
        with self.assertRaises((ValueError,FileExistsError)):
            agent.run_session(c,llm,c.slot_id,self.output)
        self.assertEqual(ledger.summary()['request_count'],1)


if __name__=='__main__': unittest.main()
