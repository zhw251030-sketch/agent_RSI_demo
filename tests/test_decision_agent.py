"""New decision prompt/lifecycle with the real SDK and offline model responses."""
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
    from litellm.types.utils import ModelResponse
    from rsi_eval.pilot_budget import BudgetExceeded, BudgetLedger
    from rsi_eval.two_stage_agent import RevisionStatePacketLLM
    from rsi_eval.decision_agent import run_decision_session, DECISION_SYSTEM_PROMPT
    from rsi_eval.two_stage_core import common_request


class Recorder:
    def __init__(self, output, feedback=None):
        self.output_dir = output; self.feedback = feedback; self.calls = []; self.halted = False

    def task_packet(self):
        return {'source': 'def solve(): return []', 'probe_feedback': copy.deepcopy(self.feedback)}

    def task_prompt(self): return json.dumps(self.task_packet())

    def submit(self, session_id, source, n_params, rationale, auxiliary):
        self.calls.append(dict(session_id=session_id,source=source,n_params=n_params,
                               rationale=rationale,auxiliary=copy.deepcopy(auxiliary)))
        return {'status': 'recorded'}

    def summary(self): return {'submissions': len(self.calls), 'halted': self.halted}


@unittest.skipUnless(SDK_PRESENT, 'OpenHands SDK is not installed in this interpreter')
class DecisionSDKTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root = Path(temp.name)
        level = logging.root.manager.disable; logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, level)

    def bound(self, name, feedback=None, **budgets):
        output = self.root/name; output.mkdir(); controller = Recorder(output, feedback)
        ledger = BudgetLedger(output/'budget-ledger.json', session_ids=[name],
            max_requests=1, max_requests_per_session=1, **budgets)
        llm = RevisionStatePacketLLM(model='anthropic/minimax-m3', api_key='offline-placeholder',
            base_url='https://example.invalid',max_output_tokens=4096,num_retries=0,
            caching_prompt=False,api_mode='chat',stream=False,reasoning_effort='none',
            native_tool_calling=True,force_string_serializer=False,fallback_strategy=None,
            log_completions=False).bind_controller(controller).bind_pilot(ledger,name,output/'requests')
        return controller,llm,ledger,output

    @staticmethod
    def args(**changes):
        return dict(source='def solve(): return []',n_params=0,rationale='Keep.',
                    auxiliary={'forecast': 'intentionally-invalid'},**changes)

    @staticmethod
    def response(args=None, tool='submit_candidate', second=False, reason='tool_calls'):
        message = {'role':'assistant','content':'Offline fixture.'}
        if args is not None:
            call = {'id':'call-1','type':'function','function':{'name':tool,'arguments':json.dumps(args)}}
            message['tool_calls'] = [call]
            if second: message['tool_calls'].append({**copy.deepcopy(call),'id':'call-2'})
        return ModelResponse(id='response-fixture',model='minimax-m3',
            choices=[{'message':message,'finish_reason':reason}],
            usage={'prompt_tokens':100,'completion_tokens':20,'total_tokens':120})

    def run_mock(self,name,args=None,**options):
        c,llm,ledger,output = self.bound(name)
        with patch('openhands.sdk.llm.llm.litellm_completion',return_value=self.response(args,**options)) as provider:
            result = run_decision_session(c,llm,name,output)
        self.assertEqual(provider.call_count,1)
        return c,llm,ledger,output,result

    def test_prompt_one_tool_and_preserved_dispatch_evidence(self):
        args = self.args(); c,llm,ledger,output,result = self.run_mock('roundtrip',args)
        self.assertEqual(c.calls,[dict(session_id='roundtrip',**args)])
        self.assertEqual(result['tools'],['finish','submit_candidate'])
        stored = json.loads((output/'sdk-submission.json').read_text())
        self.assertEqual(stored,{'stage':'revision','tool':'submit_candidate',
                                 'session_id':'roundtrip','business':args})
        payload = json.loads((output/'requests/request-0001.request.json').read_text())
        system = payload['messages'][0]['content']
        text = system if isinstance(system,str) else ''.join(v['text'] for v in system if v['type']=='text')
        self.assertIn(DECISION_SYSTEM_PROMPT,text)
        self.assertNotIn('after a frozen check registration',text)
        self.assertEqual(ledger.summary()['request_count'],1)

    def test_submission_is_saved_before_dispatch(self):
        c,llm,ledger,output = self.bound('before'); original = c.submit; args = self.args()
        def observe(*values):
            self.assertEqual(json.loads((output/'sdk-submission.json').read_text())['business'],args)
            return original(*values)
        with patch.object(c,'submit',side_effect=observe), patch('openhands.sdk.llm.llm.litellm_completion',return_value=self.response(args)):
            run_decision_session(c,llm,'before',output)
        self.assertEqual(len(c.calls),1)

    def test_two_actual_envelopes_differ_only_in_feedback(self):
        payloads=[]
        for name,feedback in [('hidden',None),('checked',{'verdict':'unknown'})]:
            c,llm,_,output = self.bound(name,feedback)
            with patch('openhands.sdk.llm.llm.litellm_completion',return_value=self.response(self.args())):
                run_decision_session(c,llm,name,output)
            payloads.append(common_request(json.loads((output/'requests/request-0001.request.json').read_text())))
        self.assertEqual(*payloads)

    def test_wrong_or_multiple_tools_and_bad_schema_never_dispatch(self):
        bad = self.args(); bad['task_id']='sealed'
        for name,args,opts in [('wrong',self.args(),{'tool':'read_file'}),
            ('many',self.args(),{'second':True}),('bad',bad,{})]:
            c,_,ledger,_,_ = self.run_mock(name,args,**opts)
            self.assertEqual(c.calls,[]); self.assertEqual(ledger.summary()['known_total_tokens'],120)

    def test_finish_and_missing_calls_are_not_candidates(self):
        for name,args,opts in [('finish',{'message':'done'},{'tool':'finish'}),
            ('empty',None,{'reason':'stop'}),('incomplete',None,{})]:
            c,_,ledger,_,_ = self.run_mock(name,args,**opts)
            self.assertEqual(c.calls,[]); self.assertEqual(ledger.summary()['request_count'],1)

    def test_unknown_usage_stops_further_transport(self):
        c,llm,ledger,output = self.bound('unknown'); response=self.response(self.args()); response.usage=None
        with patch('openhands.sdk.llm.llm.litellm_completion',return_value=response) as provider:
            run_decision_session(c,llm,'unknown',output)
            with self.assertRaises(BudgetExceeded): llm._transport_call(messages=[],max_tokens=4096)
        self.assertEqual(provider.call_count,1); self.assertTrue(ledger.summary()['halted'])

    def test_unknown_usage_valid_sdk_submission_never_reaches_runner_evaluator(self):
        from rsi_eval.decision_cases import load_cases
        from scripts.run_decision_replay import (
            ROOT, CONFIG_PATH, actor_order, execute, read, write, ExecutionLedger, freeze_inputs,
        )
        output = self.root/'unknown-integrated'; output.mkdir()
        cases = {c['id']: c for c in load_cases(ROOT)}
        config = read(ROOT/CONFIG_PATH)
        report = {'revisions': [dict(row, status='not_started') for row in actor_order()]}
        ledger = BudgetLedger(output/'budget-ledger.json',
            session_ids=[r['session_id'] for r in report['revisions']], **config['budgets'])
        executions = ExecutionLedger(output/'execution-ledger.json', config['max_sandbox_calls'])
        write(output/'runtime-freeze.json', {'runtime_files_sha256': {}})
        report['inputs_freeze_sha256'] = freeze_inputs(output, cases)
        eval_calls = []; session_calls = []
        first = cases[report['revisions'][0]['case_id']]
        response = self.response({'source': first['source'], 'n_params': first['n_params'],
                                  'rationale': 'Keep the existing artifact.', 'auxiliary': {}})
        response.usage = None

        def session(controller, row, directory):
            session_calls.append(row['session_id'])
            llm = RevisionStatePacketLLM(model='anthropic/minimax-m3', api_key='offline-placeholder',
                base_url='https://example.invalid', max_output_tokens=4096, num_retries=0,
                caching_prompt=False, api_mode='chat', stream=False, reasoning_effort='none',
                native_tool_calling=True, force_string_serializer=False, fallback_strategy=None,
                log_completions=False).bind_controller(controller).bind_pilot(
                    ledger, row['session_id'], directory/'requests')
            return run_decision_session(controller, llm, row['session_id'], directory)

        def evaluate(family, task_id, source, **kwargs):
            import hashlib
            eval_calls.append(task_id)
            return {'task_id': task_id, 'status': 'success',
                    'candidate_hash': hashlib.sha256(source.encode()).hexdigest(),
                    'executions': [{'phase': 'plan'}]}

        with patch('openhands.sdk.llm.llm.litellm_completion', return_value=response) as provider:
            execute(ROOT, output, report, cases, ledger, executions, session, evaluate)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(len(session_calls), 1)
        self.assertEqual(eval_calls, [])
        self.assertEqual(executions.summary()['reserved_sandbox_calls'], 0)
        self.assertEqual(executions.summary()['actual']['sandbox_calls'], 0)
        self.assertEqual(ledger.summary()['request_count'], 1)
        self.assertEqual(ledger.summary()['usage_unknown_count'], 1)
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(report['revisions'][0]['disposition'], 'blocked')
        self.assertTrue(all(row['status'] == 'not_started' for row in report['revisions'][1:]))
        # The received SDK submission itself remains real evidence even though
        # an unknown-usage budget must stop its downstream evaluator dispatch.
        self.assertTrue((output/'sessions'/session_calls[0]/'sdk-submission.json').is_file())

    def test_existing_evidence_and_controller_storage_failures_are_fatal(self):
        c,llm,_,output=self.bound('existing'); (output/'sdk-submission.json').write_bytes(b'original')
        with patch('openhands.sdk.llm.llm.litellm_completion',return_value=self.response(self.args())):
            run_decision_session(c,llm,'existing',output)
        self.assertTrue(c.halted);self.assertEqual(c.calls,[])
        self.assertEqual((output/'sdk-submission.json').read_bytes(),b'original')
        c,llm,_,output=self.bound('failure')
        with patch.object(c,'submit',side_effect=OSError('PRIVATE')),patch('openhands.sdk.llm.llm.litellm_completion',return_value=self.response(self.args())):
            run_decision_session(c,llm,'failure',output)
        self.assertTrue(c.halted)
        self.assertNotIn('PRIVATE',(output/'controller-error.json').read_text())

    def test_binding_repeat_and_input_cap_refuse_before_network(self):
        c,llm,ledger,output=self.bound('bound')
        with patch('openhands.sdk.llm.llm.litellm_completion') as provider:
            with self.assertRaises(ValueError):run_decision_session(c,llm,'wrong',output)
        provider.assert_not_called()
        c,llm,_,output,_=self.run_mock('repeat',self.args())
        with patch('openhands.sdk.llm.llm.litellm_completion') as provider:
            with self.assertRaises(FileExistsError):run_decision_session(c,llm,'repeat',output)
        provider.assert_not_called()
        c,llm,ledger,output=self.bound('cap',max_input_bytes=32)
        with patch('openhands.sdk.llm.llm.litellm_completion') as provider:run_decision_session(c,llm,'cap',output)
        provider.assert_not_called();self.assertEqual(ledger.summary()['request_count'],0)


if __name__=='__main__':unittest.main()
