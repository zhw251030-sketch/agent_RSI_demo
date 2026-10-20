import copy
import tempfile
from pathlib import Path
import unittest

from scripts.run_decision_replay import (ROOT, CONFIG_PATH, CASE_ORDER, actor_order,
    execute, read, write, validate_config, ExecutionLedger, freeze_inputs, verify_inputs,
    checked_execution_counts)
from rsi_eval.pilot_budget import BudgetLedger


class DecisionRunnerTests(unittest.TestCase):
    def test_missing_or_explicitly_incomplete_execution_counts_rejected(self):
        for record in ({'status':'success'}, {'status':'success','executions':[],
                'execution_accounting_complete':False}, {'status':'success','executions':[{}]},
                {'status':'infrastructure_error','executions':[]}):
            with self.subTest(record=record),self.assertRaises(ValueError):checked_execution_counts(record)
        self.assertEqual(checked_execution_counts({'family':'planning','status':'candidate_error','executions':[]})['sandbox_calls'],0)

    def test_success_requires_exact_family_execution_phases(self):
        for family,phases in [('planning',[]),('planning',['fit']),('symbolic',[]),('symbolic',['fit'])]:
            with self.subTest(family=family,phases=phases),self.assertRaises(ValueError):
                checked_execution_counts({'family':family,'status':'success','executions':[{'phase':p} for p in phases]})

    def test_exact_config_no_expansion_or_boolean_coercion(self):
        original=read(ROOT/CONFIG_PATH)
        self.assertEqual(validate_config(original), original)
        for path,value in [('repeats',3),('new_probe_executions',False),('max_sandbox_calls',97)]:
            changed=copy.deepcopy(original);changed[path]=value
            with self.assertRaises(ValueError):validate_config(changed)

    def test_counterbalanced_two_repeats_and_exact_sixteen_sessions(self):
        rows=actor_order()
        self.assertEqual(len(rows),16)
        self.assertEqual(len({r['session_id'] for r in rows}),16)
        for case in CASE_ORDER:
            first=[r['condition'] for r in rows if r['case_id']==case and r['repeat']==1]
            second=[r['condition'] for r in rows if r['case_id']==case and r['repeat']==2]
            self.assertEqual(sorted(first),['checked','hidden'])
            self.assertEqual(second,first[::-1])

    def fake_run(self,output,*,unknown=False,tamper=False,change_common=False,submit=False):
        from rsi_eval.decision_cases import load_cases
        cases={c['id']:c for c in load_cases(ROOT)}
        config=read(ROOT/CONFIG_PATH)
        report={'revisions':actor_order()}
        ledger=BudgetLedger(output/'budget-ledger.json',
            session_ids=[r['session_id'] for r in report['revisions']],**config['budgets'])
        executions=ExecutionLedger(output/'execution-ledger.json',96)
        write(output/'runtime-freeze.json',{'runtime_files_sha256':{}})
        report['inputs_freeze_sha256']=freeze_inputs(output,cases)
        def session(c,row,directory):
            self.assertTrue((output/'inputs-freeze.json').exists())
            packet=c.task_packet()
            if change_common and row['condition']=='checked':packet['objective']='changed'
            payload={'model':'mock','messages':[{'role':'user','content':__import__('json').dumps(packet)}]}
            rid=ledger.reserve(row['session_id'],payload,4096)
            write(directory/'requests'/(rid+'.request.json'),payload)
            ledger.settle(rid,None if unknown else {'prompt_tokens':10,'completion_tokens':5,'total_tokens':15})
            if submit:c.submit(row['session_id'],c.case['source'],c.case['n_params'])
            if tamper:write(output/'inputs'/'extra.json',{})
            return {'status':'completed'}
        execute(ROOT,output,report,cases,ledger,executions,session,
                lambda *a,**k:self.fail('Finish-only must not execute a candidate'))
        return report,ledger

    def test_all_finish_results_are_missing_not_success_and_no_evaluation(self):
        with tempfile.TemporaryDirectory() as d:
            report,ledger=self.fake_run(Path(d))
            self.assertEqual(report['status'],'attempts_completed')
            self.assertEqual(ledger.summary()['request_count'],16)
            self.assertEqual(len(report['common_request_sha256']),4)
            self.assertTrue(all(r['candidate'] is None and r['disposition']=='missing' for r in report['revisions']))
            self.assertEqual(report['execution_budget']['actual']['sandbox_calls'],0)

    def test_unknown_usage_stops_after_first_request(self):
        with tempfile.TemporaryDirectory() as d:
            report,ledger=self.fake_run(Path(d),unknown=True)
            self.assertEqual(report['status'],'stopped')
            self.assertEqual(ledger.summary()['request_count'],1)

    def test_unknown_usage_tool_response_cannot_reserve_or_execute_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            report,ledger=self.fake_run(Path(d),unknown=True,submit=True)
            self.assertEqual(report['status'],'stopped')
            self.assertEqual(report['execution_budget']['reserved_sandbox_calls'],0)

    def test_input_tamper_stops_before_next_request(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'Frozen phase files changed'):
                self.fake_run(Path(d),tamper=True)

    def test_full_request_difference_other_than_feedback_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'common request differs'):
                self.fake_run(Path(d),change_common=True)

    def test_input_freeze_rejects_changed_anchor_and_payload(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);digest=freeze_inputs(out,{'case':{'source':'exact'}})
            verify_inputs(out,digest)
            write(out/'inputs-freeze.json',{})
            with self.assertRaisesRegex(ValueError,'anchor'):
                verify_inputs(out,digest)


if __name__=='__main__':unittest.main()
