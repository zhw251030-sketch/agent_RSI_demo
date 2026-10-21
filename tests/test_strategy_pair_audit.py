"""Trusted-client record binding under independently fabricated SDK receipts."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rsi_eval import strategy_binding as binding
from rsi_eval.strategy_learning import build_learning_package, render_update_packet
from rsi_eval.strategy_pair_budget import StrategyPairBudgetLedger
from rsi_eval.strategy_pair_controller import StrategyPairController
try:
    from rsi_eval import strategy_pair_audit as audit
except ImportError:
    audit = None

ROOT = Path(__file__).resolve().parents[1]


class SessionAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = render_update_packet(ROOT, build_learning_package(ROOT))
        cls.slots = json.loads((ROOT / binding.FUTURE_ALLOCATION).read_text())['slots']

    def setUp(self):
        self.assertIsNotNone(audit, 'Strategy SDK evidence audit missing')
        temp = tempfile.TemporaryDirectory(dir=ROOT/'tmp', prefix='strategy-audit-')
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.fixture_root = self.directory
        self.ledger_path = self.directory/'budget-ledger.json'
        self.ledger = StrategyPairBudgetLedger(self.ledger_path, [s['id'] for s in self.slots])
        self.slot = self.slots[0]
        self.result = self.fixture()

    def write(self, name, value):
        path = self.directory/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else binding.canonical(value)+b'\n')
        return binding.file_ref(ROOT, path.relative_to(ROOT).as_posix())

    def fixture(self):
        stage = 'update' if self.slot['phase'] == 'update' else 'actor'
        tool = 'submit_policy' if stage == 'update' else 'submit_candidate'
        request = dict(model='anthropic/MiniMax-M3',messages=[dict(role='system',content='Synthetic fixture'),
            dict(role='user',content=binding.canonical(self.packet).decode())],tools=[
                dict(type='function',function=dict(name=name)) for name in (tool,'finish')],
            tool_choice=None,max_output_tokens=8192)
        # Actor slots follow update slots in the global ledger. Fabricated prior
        # reservations satisfy its order contract; none represents a provider call.
        for earlier in self.slots[:self.slots.index(self.slot)]:
            prior = self.ledger.reserve(earlier['id'], {'fixture': earlier['id']}, 8192)
            self.ledger.settle(prior, dict(prompt_tokens=1, completion_tokens=1, total_tokens=2))
        request_id = self.ledger.reserve(self.slot['id'], request, 8192)
        usage = dict(prompt_tokens=100,completion_tokens=20,total_tokens=120)
        self.ledger.settle(request_id,usage)
        request_ref = self.write('requests/'+request_id+'.request.json',request)
        business = (dict(rule_1='R01',rule_2='R02',rule_3='R03',rule_4='R04',explanation='Unverified.')
            if stage == 'update' else dict(source='def get_plan(x): return []\n',n_params=0,explanation='Unverified.'))
        response = dict(response_id='response-1',usage=usage,usage_details={},choices=[dict(
            message=dict(role='assistant',content='fixture',tool_calls=[dict(id='call-1',type='function',
                function=dict(name=tool,arguments=json.dumps(business)))]),finish_reason='tool_calls')])
        response_ref = self.write('requests/'+request_id+'.response.json',response)
        sdk = dict(version='strategy-sdk-submission-v0.1',stage=stage,slot_id=self.slot['id'],
            tool=tool,request_id=request_id,request=request_ref,response=response_ref,
            response_id='response-1',tool_call_id='call-1',business=business)
        sdk_ref = self.write('sdk-submission.json',sdk)
        controller = StrategyPairController(ROOT,self.packet,self.slot['id'],self.directory)
        controller.accept(business,request_id,request_ref,sdk_ref)
        input_ref = self.write('requests/input-audit.json',dict(version='strategy-pair-input-audit-v0.1',
            request_id=request_id,slot_id=self.slot['id'],actual_input_bytes=len(binding.canonical(request)),
            max_input_bytes=98304,payload_sha256=binding.digest(request),request_reserved=True,
            transport_called=True,status='completed',error_type=None))
        events = [dict(type='ActionEvent',tool_name=tool,tool_call_id='call-1',llm_response_id='response-1'),
                  dict(type='ObservationEvent',tool_name=tool,tool_call_id='call-1')]
        self.write('events.jsonl',b''.join(binding.canonical(e)+b'\n' for e in events))
        self.write('transport-settings.json',dict(version='strategy-pair-agent-v0.1',timeout=180,num_retries=0,
            provider_max_retries=0,stream=False,max_output_tokens=8192))
        transport = self.write('transport-request.json',dict(version='state-generation-transport-v0.1',
            expected_timeout_seconds=180,timeout_seconds=180,max_retries=0,stream_present=False,stream=False,
            num_retries_present=False,num_retries=None,request_file='requests/'+request_id+'.request.json',
            request_sha256=request_ref['sha256']))
        self.write('transport-result.json',dict(version='state-generation-transport-v0.1',
            request_receipt_sha256=transport['sha256'],elapsed_seconds=0.01,status='returned',error_type=None))
        safe_settings=dict(model='anthropic/MiniMax-M3',base_url='https://api.minimax.cn/anthropic',
            temperature=1.0,max_output_tokens=8192,timeout=180,num_retries=0,caching_prompt=False,
            reasoning_effort='none',litellm_extra_body={'thinking':{'type':'disabled'}},seed=None,drop_params=True)
        self.write('sdk-dispatch.json',dict(version='strategy-pair-dispatch-v0.1',
            request_file='requests/'+request_id+'.request.json',request_sha256=request_ref['sha256'],
            request_payload_sha256=binding.digest(request),settings_sha256=binding.digest(safe_settings),
            observed=dict(model='MiniMax-M3',custom_llm_provider='anthropic',public_endpoint_matches=True,
                max_completion_tokens=8192,tool_choice=None,temperature=1.0,seed=None,drop_params=True,
                extra_body={'thinking':{'type':'disabled'}},reasoning_effort_present=False,
                messages_sha256=binding.digest(request['messages']),tools_sha256=binding.digest(request['tools']))))
        result = dict(version='strategy-pair-agent-v0.1',slot_id=self.slot['id'],stage=stage,status='accepted',
            request_id=request_id,request=request_ref,response=response_ref,sdk_submission=sdk_ref,input_audit=input_ref,
            submission=controller.submission,source=controller.source,policy=controller.policy,error_type=None,
            sdk_error_codes=[],controller=controller.summary())
        self.write('session-summary.json',result)
        return result

    def verify(self, result=None):
        return audit.verify_session(ROOT,self.slot,self.packet,result or self.result,self.ledger_path)

    def replace_ref(self, field, mutate):
        old = self.result[field]
        path = ROOT/old['path']
        value = json.loads(path.read_text())
        mutate(value)
        path.write_bytes(binding.canonical(value)+b'\n')
        self.result[field] = binding.file_ref(ROOT,old['path'])
        self.write('session-summary.json',self.result)

    def metadata_fixture(self, stage, case):
        from tests.test_strategy_pair_agent import actor_packet
        self.directory = self.fixture_root / ('metadata-'+stage+'-'+str(case))
        self.ledger_path = self.directory/'budget-ledger.json'
        self.ledger = StrategyPairBudgetLedger(self.ledger_path, [s['id'] for s in self.slots])
        self.slot = (self.slots[0] if stage == 'update' else
            next(s for s in self.slots if s['id'] == 'r1-selection-P-select-1-fixed'))
        self.packet = type(self).packet if stage == 'update' else actor_packet()
        self.result = self.fixture()
        sdk = json.loads((ROOT/self.result['sdk_submission']['path']).read_bytes())
        return sdk['business']

    def rebind_raw_arguments(self, raw):
        """Rehash the entire affected chain so rejection tests semantic checks."""
        self.replace_ref('response', lambda v: v['choices'][0]['message']['tool_calls'][0]['function'].update(arguments=raw))
        self.replace_ref('sdk_submission', lambda v: v.update(response=self.result['response']))
        attempt = json.loads((self.directory/'acceptance-attempt.json').read_bytes())
        attempt['sdk_submission'] = self.result['sdk_submission']
        self.write('acceptance-attempt.json', attempt)
        self.assertEqual(binding.file_ref(ROOT,self.result['response']['path']), self.result['response'])
        self.assertEqual(binding.file_ref(ROOT,self.result['sdk_submission']['path']), self.result['sdk_submission'])
        sdk = json.loads((ROOT/self.result['sdk_submission']['path']).read_bytes())
        self.assertEqual(sdk['response'], self.result['response'])
        self.assertEqual(attempt['sdk_submission'], self.result['sdk_submission'])

    def test_valid_sdk_metadata_passes_full_bound_audit_for_update_and_actor(self):
        for stage in ('update', 'actor'):
            for number, metadata in enumerate(({}, {'summary': None}, {'security_risk': 'UNKNOWN'},
                    {'summary': 'Archive only', 'security_risk': 'HIGH'})):
                with self.subTest(stage=stage, metadata=metadata):
                    business = self.metadata_fixture(stage, number)
                    self.rebind_raw_arguments(json.dumps(business | metadata))
                    result = self.verify()
                    self.assertEqual(result['status'], 'passed')
                    self.assertEqual(result['tool'], 'submit_policy' if stage == 'update' else 'submit_candidate')
                    sdk = json.loads((ROOT/self.result['sdk_submission']['path']).read_bytes())
                    self.assertEqual(sdk['business'], business)

    def test_invalid_metadata_cannot_pass_audit_after_rehashing_entire_chain(self):
        changes = ({'summary': 1}, {'summary': []}, {'security_risk': None},
            {'security_risk': 'invalid'}, {'security_risk': True}, {'unexpected': 'not metadata'},
            {'kind': 'Action'})
        for stage in ('update', 'actor'):
            for number, metadata in enumerate(changes):
                with self.subTest(stage=stage, metadata=metadata):
                    business = self.metadata_fixture(stage, number)
                    self.rebind_raw_arguments(json.dumps(business | metadata))
                    with self.assertRaisesRegex(ValueError, 'SDK summary|SDK security_risk|Submission fields'):
                        self.verify()

    def test_duplicate_metadata_cannot_pass_audit_after_rehashing_entire_chain(self):
        for stage in ('update', 'actor'):
            for number, duplicate in enumerate(('"summary":"second"', '"security_risk":"HIGH"')):
                with self.subTest(stage=stage, duplicate=duplicate):
                    business = self.metadata_fixture(stage, number)
                    raw = json.dumps(business | {'summary': None, 'security_risk': 'LOW'})
                    self.rebind_raw_arguments(raw[:-1]+','+duplicate+'}')
                    with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
                        self.verify()

    def test_complete_chain_is_accepted_without_source_or_task_execution(self):
        result = self.verify()
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['request_id'],'request-0001')
        self.assertEqual(result['tool'],'submit_policy')
        self.assertIn('trusted-client',result['evidence_boundary'])

    def test_rehashed_raw_response_cannot_change_policy_or_business(self):
        self.replace_ref('response',lambda v:v['choices'][0]['message']['tool_calls'][0]['function'].update(
            arguments='{"rule_1":"R08","rule_2":"R02","rule_3":"R03","rule_4":"R04"}'))
        with self.assertRaises(ValueError): self.verify()

    def test_rehashed_request_cannot_disagree_with_ledger(self):
        self.replace_ref('request',lambda v:v.update(model='changed'))
        with self.assertRaises(ValueError): self.verify()

    def test_duplicate_raw_tool_arguments_are_not_accepted_after_normalization(self):
        self.replace_ref('response',lambda v:v['choices'][0]['message']['tool_calls'][0]['function'].update(
            arguments='{"rule_1":"R01","rule_1":"R08","rule_2":"R02","rule_3":"R03","rule_4":"R04"}'))
        with self.assertRaises(ValueError): self.verify()

    def test_missing_or_mismatched_sdk_action_event_is_rejected(self):
        self.write('events.jsonl',binding.canonical(dict(type='ObservationEvent',tool_name='submit_policy',tool_call_id='call-1'))+b'\n')
        with self.assertRaises(ValueError): self.verify()

    def test_unknown_or_failed_usage_cannot_certify_acceptance(self):
        value = json.loads(self.ledger_path.read_text())
        value['requests'][0].update(usage=None,usage_state='unknown',status='failed')
        self.ledger_path.write_bytes(binding.canonical(value)+b'\n')
        with self.assertRaises(ValueError): self.verify()

    def test_rehashed_policy_result_cannot_replace_accepted_policy(self):
        self.result['policy']['rule_ids'][0]='R08'
        self.write('session-summary.json',self.result)
        with self.assertRaises(ValueError): self.verify()

    def test_dispatch_without_controller_acceptance_is_rejected(self):
        (self.directory/'acceptance-attempt.json').unlink()
        with self.assertRaises(ValueError): self.verify()

    def test_transport_configuration_cannot_introduce_retries(self):
        self.write('transport-settings.json',dict(version='strategy-pair-agent-v0.1',timeout=180,num_retries=1,
            provider_max_retries=0,stream=False,max_output_tokens=8192))
        with self.assertRaises(ValueError): self.verify()

    def test_missing_actual_dispatch_proof_is_rejected(self):
        (self.directory/'sdk-dispatch.json').unlink(missing_ok=True)
        with self.assertRaises(ValueError): self.verify()

    def test_changed_actual_messages_hash_or_sampling_parameter_is_rejected(self):
        path=self.directory/'sdk-dispatch.json'
        original=path.read_bytes()
        for key,value in [('messages_sha256','0'*64),('temperature',0.5),('reasoning_effort_present',True)]:
            with self.subTest(key=key):
                proof=json.loads(original)
                proof['observed'][key]=value
                path.write_bytes(binding.canonical(proof)+b'\n')
                with self.assertRaises(ValueError): self.verify()
        path.write_bytes(original)

    def test_result_cannot_point_to_another_slot(self):
        wrong = copy.deepcopy(self.slot)
        wrong['id'] = self.slots[1]['id']
        with self.assertRaises(ValueError):
            audit.verify_session(ROOT,wrong,self.packet,self.result,self.ledger_path)

    def test_reservation_for_a_slot_that_never_started_is_rejected(self):
        self.write('partial/summary.json',dict(status='stopped',slots=[],events=[]))
        partial=dict(status='record_consistent_incomplete',accepted_sessions=0)
        with patch.object(audit,'audit_protocol',return_value=partial):
            with self.assertRaises(ValueError):
                audit.audit_run(ROOT,self.directory/'partial',ledger_path=self.ledger_path)


class PhaseAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_strategy_pair_run import SyntheticSessions, SyntheticExecutorFactory, TEMPLATE, BUDGET
        from rsi_eval.strategy_pair_run import run_strategy_pair
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT/'tmp',prefix='strategy-phase-audit-')
        cls.output = (Path(cls.temp.name)/'run').relative_to(ROOT).as_posix()
        cls.report = run_strategy_pair(ROOT,cls.output,session_runner=SyntheticSessions(),
            executor_factory=SyntheticExecutorFactory(cls.output),request_template=TEMPLATE,budget=BUDGET,evidence_kind='synthetic')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_complete_protocol_replays_all_716_synthetic_measurements(self):
        self.assertTrue(hasattr(audit,'audit_protocol'),'Phase audit is missing')
        report = audit.audit_protocol(ROOT,self.output)
        self.assertEqual(report['status'],'passed_complete')
        self.assertEqual(report['measurement_records_verified'],716)
        self.assertEqual(report['sdk_sessions_verified'],0)
        self.assertEqual(report['synthetic_measurements'],716)

    def test_rehashed_phase_events_cannot_move_evaluation_before_both_decisions(self):
        self.assertTrue(hasattr(audit,'audit_protocol'),'Phase audit is missing')
        path = ROOT/self.output/'summary.json'
        original = path.read_bytes()
        changed = copy.deepcopy(self.report)
        event = next(e for e in changed['events'] if e['kind']=='both_decisions_frozen')
        event['kind']='not_yet_frozen'
        backups = {}
        try:
            previous = None
            for value in changed['events']:
                value['previous_sha256']=previous
                previous=binding.digest(value)
                file = ROOT/self.output/'events'/f"{value['ordinal']:05d}.json"
                backups[file]=file.read_bytes()
                file.write_bytes(binding.canonical(value)+b'\n')
            path.write_bytes(binding.canonical(changed)+b'\n')
            with self.assertRaises(ValueError): audit.audit_protocol(ROOT,self.output)
        finally:
            path.write_bytes(original)
            for file,raw in backups.items(): file.write_bytes(raw)

    def test_rehashed_summary_cannot_change_paired_evaluation_result(self):
        self.assertTrue(hasattr(audit,'audit_protocol'),'Phase audit is missing')
        path = ROOT/self.output/'summary.json'
        original = path.read_bytes()
        changed = copy.deepcopy(self.report)
        changed['evaluation_pairs'][0]['attribution']='invented_policy_effect'
        try:
            path.write_bytes(binding.canonical(changed)+b'\n')
            with self.assertRaises(ValueError): audit.audit_protocol(ROOT,self.output)
        finally:
            path.write_bytes(original)

    def test_stopped_run_reports_only_two_accepted_requests_and_no_measurements(self):
        from tests.test_strategy_pair_run import SyntheticSessions, SyntheticExecutorFactory, TEMPLATE, BUDGET
        from rsi_eval.strategy_pair_run import run_strategy_pair
        sessions=SyntheticSessions()
        sessions.fail_at=3
        output=(Path(self.temp.name)/'stopped').relative_to(ROOT).as_posix()
        run_strategy_pair(ROOT,output,session_runner=sessions,executor_factory=SyntheticExecutorFactory(output),
            request_template=TEMPLATE,budget=BUDGET,evidence_kind='synthetic')
        result=audit.audit_protocol(ROOT,output)
        self.assertEqual(result['status'],'record_consistent_incomplete')
        self.assertEqual(result['slots_completed'],2)
        self.assertEqual(result['slots_failed'],1)
        self.assertEqual(result['slots_not_started'],33)
        self.assertEqual(result['measurement_records_verified'],0)


if __name__=='__main__': unittest.main()
