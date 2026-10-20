"""Phase and stop boundaries with fake SDK transport and a real persistent budget."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from rsi_eval.pilot_budget import BudgetLedger
from rsi_eval.policy_cases import load_update_bundle
from rsi_eval.revision_policy import PolicyUpdateController, S0, freeze_policy
from scripts import run_policy_transfer as runner


PROJECT = Path(__file__).resolve().parents[1]
VALID_POLICY_ARGS = dict(rule_1='R01', rule_2='R02', rule_3='R05', rule_4='R07',
    support_1='U-P', support_2='U-P', support_3='both', support_4='both',
    rationale='Synthetic offline selection.')


class FakeLLM:
    def __init__(self, **settings):
        self.settings = settings

    def bind_controller(self, controller):
        self.controller = controller
        return self

    def bind_pilot(self, ledger, session, output):
        self.ledger, self.session = ledger, session
        return self


class FakeLedger:
    def __init__(self):
        self.value = dict(halted=False, usage_unknown_count=0, reserved_count=0)

    def summary(self):
        return copy.deepcopy(self.value)


class PolicyEvaluationRunnerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def prepared(self, count=2):
        entries = []
        for index in range(count):
            directory = self.root/str(index)
            directory.mkdir()
            controller = types.SimpleNamespace(halted=False, family='planning', records=[{
                'source_sha256': 'same-source', 'n_params': 0, 'results': [{'task_id':'fixture'}],
                'metrics': {'total_successes': 0}}], state_packet=lambda: {'same':True})
            entry = dict(session_id='offline'+str(index), pair_id='pair',
                         condition=('fixed','memory','updated')[index % 3])
            entries.append((controller, directory, entry))
        return entries

    @staticmethod
    def fake_module(dispatch):
        return types.SimpleNamespace(CompactStatePacketLLM=FakeLLM,
                                     compact_candidate_tool=object(), run_session=dispatch)

    def test_known_response_contract_failures_continue_with_no_invented_candidate(self):
        for error in ('IncompleteToolResponseError','PilotResponseContractError'):
            with self.subTest(error=error), tempfile.TemporaryDirectory(dir=self.root) as temp:
                old = self.root
                self.root = Path(temp)
                entries = self.prepared()
                self.root = old
                dispatch = Mock(side_effect=[{'status':'error','cause_type':error},
                                             {'status':'stopped','model_error_type':None}])
                report = {'sessions':[e for _,_,e in entries]}
                with patch.dict(sys.modules, {'rsi_eval.compact_agent':self.fake_module(dispatch)}), \
                        patch.object(runner,'verify_triplets',return_value={'pair':{'verified':True}}):
                    runner.run_evaluation(entries,report,FakeLedger(),{})
                self.assertEqual(dispatch.call_count,2)
                self.assertEqual(report['status'],'attempts_completed')
                for _,_,entry in entries:
                    self.assertEqual(entry['step_status'],'no_candidate')
                    self.assertIsNone(entry['endpoint']['child_metrics'])

    def test_unknown_usage_on_final_response_still_stops_round(self):
        entries, ledger = self.prepared(1), FakeLedger()
        def dispatch(*args,**kwargs):
            ledger.value.update(halted=True,usage_unknown_count=1)
            return {'status':'stopped','model_error_type':None}
        report = {'sessions':[e for _,_,e in entries]}
        with patch.dict(sys.modules, {'rsi_eval.compact_agent':self.fake_module(Mock(side_effect=dispatch))}), \
                patch.object(runner,'verify_triplets',return_value={}):
            runner.run_evaluation(entries,report,ledger,{})
        self.assertEqual(report['status'],'stopped')
        self.assertEqual(report['stop_reason'],'budget_or_unknown_usage')
        self.assertEqual(report['budget']['usage_unknown_count'],1)

    def test_halted_controller_prevents_later_dispatch_even_with_normal_sdk_stop(self):
        entries = self.prepared()
        def dispatch(controller,*args,**kwargs):
            controller.halted = True
            return {'status':'stopped','model_error_type':None}
        call = Mock(side_effect=dispatch)
        report = {'sessions':[e for _,_,e in entries]}
        with patch.dict(sys.modules, {'rsi_eval.compact_agent':self.fake_module(call)}), \
                patch.object(runner,'verify_triplets',return_value={}):
            runner.run_evaluation(entries,report,FakeLedger(),{})
        call.assert_called_once()
        self.assertEqual(report['stop_reason'],'controller_infrastructure_error')
        self.assertEqual(entries[1][2]['status'],'not_started_after_stop')

    def test_real_triplet_mismatch_rejects_before_llm_or_dispatch(self):
        entries = self.prepared(3)
        entries[1][0].state_packet = lambda: {'same':False}
        dispatch, construction = Mock(), Mock()
        module = self.fake_module(dispatch)
        module.CompactStatePacketLLM = construction
        with patch.dict(sys.modules, {'rsi_eval.compact_agent':module}), self.assertRaises(ValueError):
            runner.run_evaluation(entries,{},FakeLedger(),{})
        construction.assert_not_called()
        dispatch.assert_not_called()


class PolicyMainRunnerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config_raw = (PROJECT/runner.CONFIG_PATH).read_bytes()
        self.config = json.loads(self.config_raw)
        self.config_path = self.root/runner.CONFIG_PATH
        self.config_path.parent.mkdir(parents=True)
        self.config_path.write_bytes(self.config_raw)
        self.model_path = self.root/'configs/models/offline.json'
        self.model_path.parent.mkdir()
        self.model_path.write_text('{}')
        base_path = self.root/self.config['base_config']
        base_path.write_text(json.dumps({'model_configuration':'configs/models/offline.json'}))
        self.bundle = load_update_bundle(PROJECT)
        self.provenance = {'code_commit':'offline','sdk_version':'1.55.1','source_sha256':{'fixture':'hash'}}
        self.identity = dict(config_sha256=hashlib.sha256(self.config_raw).hexdigest(),
            model_config_sha256='offline-model-hash',model_config={},effective_model_config={},**self.provenance)
        self.output = self.root/'runs/policy-transfer/offline-run'

    @contextlib.contextmanager
    def environment(self, policy_run=None):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(runner,'ROOT',self.root))
            stack.enter_context(patch.object(runner,'source_provenance',return_value=self.provenance))
            stack.enter_context(patch('rsi_eval.policy_cases.load_update_bundle',return_value=self.bundle))
            stack.enter_context(patch('rsi_eval.policy_cases.load_evaluation_states',return_value=[]))
            stack.enter_context(patch('scripts.run_checked_feedback._base_sessions',return_value={}))
            stack.enter_context(patch('scripts.run_checked_feedback._model_configuration',
                                      return_value=('offline-model-hash',{},{})))
            stack.enter_context(patch('scripts.configure_minimax.CONFIG',self.model_path))
            read_key = stack.enter_context(patch('scripts.configure_minimax.read_key',
                                                 return_value='offline-not-a-key'))
            stack.enter_context(patch('scripts.configure_minimax.auth_path',return_value='not-read'))
            if policy_run is not None:
                stack.enter_context(patch.dict(sys.modules, {'rsi_eval.policy_agent':types.SimpleNamespace(
                    PolicyStatePacketLLM=FakeLLM,run_policy_session=policy_run)}))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            yield read_key

    def saved_update(self):
        self.output.mkdir(parents=True)
        controller = PolicyUpdateController(self.bundle,S0,self.output/'policy_update')
        self.assertEqual(controller.submit_policy(**VALID_POLICY_ARGS)['status'],'accepted')
        ledger = BudgetLedger(self.output/'budget-ledger.json',
            session_ids=['policy_update']+[e['session_id'] for e in runner.expected_order()],
            **self.config['budgets'])
        request = ledger.reserve('policy_update',{'offline':True},4096)
        ledger.settle(request,{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2})
        frozen = freeze_policy(self.output/'policy_update',self.bundle,S0,request)
        previous = dict(self.identity,run_id='offline-run',mode='update',status='policy_frozen',
            sessions=runner.expected_order(),freeze=frozen,selected_policy=controller.policy,
            freeze_file_sha256=hashlib.sha256((self.output/'policy_update/freeze.json').read_bytes()).hexdigest())
        for name,value in [('summary.json',previous),('update-bundle.json',self.bundle),('policy-S0.json',S0)]:
            runner.write_json(self.output/name,value)
        return previous

    def invoke(self, phase):
        return runner.main(['--run-id','offline-run','--config',str(self.config_path),'--'+phase])

    def test_evaluation_reentry_preserves_original_summary_and_never_reads_key(self):
        self.saved_update()
        marker = self.output/'evaluation-started.json'
        marker.write_bytes(b'original phase marker\n')
        summary = (self.output/'summary.json').read_bytes()
        with self.environment() as read_key:
            self.assertEqual(self.invoke('evaluate'),1)
        read_key.assert_not_called()
        self.assertEqual((self.output/'summary.json').read_bytes(),summary)
        self.assertEqual(marker.read_bytes(),b'original phase marker\n')

    def test_missing_freeze_preserves_original_summary_and_never_reads_key(self):
        self.saved_update()
        (self.output/'policy_update/freeze.json').unlink()
        summary = (self.output/'summary.json').read_bytes()
        with self.environment() as read_key:
            self.assertEqual(self.invoke('evaluate'),1)
        read_key.assert_not_called()
        self.assertEqual((self.output/'summary.json').read_bytes(),summary)
        self.assertFalse((self.output/'evaluation-started.json').exists())

    def test_cross_phase_freeze_anchor_mismatch_rejects_before_key_and_keeps_summary(self):
        previous = self.saved_update()
        previous['freeze_file_sha256'] = '0'*64
        runner.write_json(self.output/'summary.json',previous)
        summary = (self.output/'summary.json').read_bytes()
        with self.environment() as read_key:
            self.assertEqual(self.invoke('evaluate'),1)
        read_key.assert_not_called()
        self.assertEqual((self.output/'summary.json').read_bytes(),summary)
        self.assertFalse((self.output/'evaluation-started.json').exists())

    def test_valid_policy_with_sdk_recording_error_never_freezes(self):
        def fake_run(controller,llm,session,output):
            request = llm.ledger.reserve(session,{'offline':True},4096)
            llm.ledger.settle(request,{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2})
            self.assertEqual(controller.submit_policy(**VALID_POLICY_ARGS)['status'],'accepted')
            return {'status':'error','model_error_type':'OSError','controller':controller.summary()}
        with self.environment(fake_run) as read_key, patch('rsi_eval.revision_policy.freeze_policy') as freeze:
            self.assertEqual(self.invoke('update'),1)
        read_key.assert_called_once()
        freeze.assert_not_called()
        report = json.loads((self.output/'summary.json').read_text())
        self.assertEqual(report['status'],'update_not_frozen')
        self.assertEqual(report['policy_update']['controller']['status'],'accepted')
        self.assertEqual(report['budget']['usage_unknown_count'],0)
        self.assertTrue((self.output/'policy_update/policy-S1.json').exists())
        self.assertFalse((self.output/'policy_update/freeze.json').exists())


if __name__ == '__main__':
    unittest.main()
