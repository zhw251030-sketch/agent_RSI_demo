import copy
import json
from pathlib import Path
import tempfile
import unittest

from rsi_eval.decision_cases import load_cases
from rsi_eval.pilot_budget import BudgetLedger
from scripts.run_edit_commitment import (ROOT,CONFIG_PATH,CASE_ORDER,draft_order,review_order,
    validate_config,execute,read,write,freeze_inputs,ExecutionLedger)


class CommitmentRunnerTests(unittest.TestCase):
    def test_fixed_twelve_slots_and_balanced_arm_order(self):
        self.assertEqual(len(draft_order()),4); self.assertEqual(len(review_order()),8)
        self.assertEqual(len({r['session_id'] for r in draft_order()+review_order()}),12)
        self.assertEqual([r['condition'] for r in review_order()[:2]],['self','checked'])
        self.assertEqual([r['condition'] for r in review_order()[2:4]],['checked','self'])

    def test_config_cannot_expand_budget_or_coerce_scope_flags(self):
        cfg=read(ROOT/CONFIG_PATH); validate_config(cfg)
        for field,value in [('max_sandbox_calls',49),('sealed_tasks_executed',False),('resume',True)]:
            bad=copy.deepcopy(cfg);bad[field]=value
            with self.assertRaises(ValueError):validate_config(bad)

    def fake_run(self,path,*,missing=None,unknown=False,tamper=False,difference=False):
        case_map={c['id']:c for c in load_cases(ROOT)}
        cases={k:case_map[k] for k in CASE_ORDER};cfg=read(ROOT/CONFIG_PATH)
        report={'drafts':draft_order(),'reviews':review_order()}
        ledger=BudgetLedger(path/'budget-ledger.json',session_ids=[r['session_id'] for r in report['drafts']+report['reviews']],**cfg['budgets'])
        executions=ExecutionLedger(path/'execution-ledger.json',48)
        report['inputs_freeze_sha256']=freeze_inputs(path,cases)
        write(path/'runtime-freeze.json',{'runtime_files_sha256':{}})
        history=[]
        def session(c,row,directory):
            stage=row['stage']; history.append((stage,row['session_id']))
            if stage=='review':
                self.assertEqual(sum(s=='draft' for s,_ in history),4)
                self.assertTrue((path/'draft-freeze.json').exists())
                self.assertTrue((path/'feedback-freeze.json').exists())
            p=c.task_packet()
            if difference and row.get('condition')=='checked':p['objective']='different'
            payload={'model':'mock','messages':[{'role':'user','content':json.dumps(p)}]}
            rid=ledger.reserve(row['session_id'],payload,4096)
            write(directory/'requests'/(rid+'.request.json'),payload)
            ledger.settle(rid,None if unknown else {'prompt_tokens':10,'completion_tokens':5,'total_tokens':15})
            if not unknown and not(stage=='draft' and (row['case_id']==missing or missing=='all')):
                c.submit(session_id=row['session_id'],source=c.case['source'],n_params=c.case['n_params'],
                         edit_claim='keep_ast',deployment_claim='unspecified')
            if tamper and stage=='review':
                write(path/'drafts'/CASE_ORDER[0]/'extra.json',{})
            return {'status':'completed'}
        def evaluate(family,task,source,**kw):
            self.assertEqual(sum(s=='draft' for s,_ in history),4)
            phase=[{'phase':'plan'}] if family=='planning' else [{'phase':'fit'},{'phase':'predict'}]
            row=dict(family=family,task_id=task,candidate_hash=__import__('hashlib').sha256(source.encode()).hexdigest(),
                     candidate_id=kw['candidate_id'],parent_id=kw['parent_id'],strategy_version=kw['strategy_version'],
                     status='task_failure' if family=='planning' else 'success',executions=phase)
            if family=='symbolic':row['metrics']={'nmse':0.2}
            return row
        execute(ROOT,path,report,cases,ledger,executions,session,evaluate)
        return report,ledger

    def test_all_drafts_before_any_review_and_only_final_evaluations(self):
        with tempfile.TemporaryDirectory() as d:
            r,l=self.fake_run(Path(d))
            self.assertEqual(r['status'],'attempts_completed')
            self.assertEqual(l.summary()['request_count'],12)
            self.assertEqual(r['execution_budget']['actual']['new_candidate_executions'],44)
            self.assertEqual(r['execution_budget']['actual']['sandbox_calls'],48)
            self.assertEqual(len(r['common_request_sha256']),4)

    def test_missing_draft_skips_both_arms_without_replacement(self):
        with tempfile.TemporaryDirectory() as d:
            r,l=self.fake_run(Path(d),missing='P-format')
            self.assertEqual(l.summary()['request_count'],10)
            rows=[r for r in r['reviews'] if r['case_id']=='P-format']
            self.assertTrue(all(r['disposition']=='skipped_missing_draft' for r in rows))
            self.assertFalse((Path(d)/'reviews'/'P-format-self').exists())

    def test_unknown_usage_stops_before_second_draft_and_no_execution(self):
        with tempfile.TemporaryDirectory() as d:
            r,l=self.fake_run(Path(d),unknown=True)
            self.assertEqual(r['status'],'stopped');self.assertEqual(l.summary()['request_count'],1)
            self.assertEqual(r['execution_budget']['actual']['sandbox_calls'],0)

    def test_all_missing_drafts_produce_empty_complete_review_allocation(self):
        with tempfile.TemporaryDirectory() as d:
            r,l=self.fake_run(Path(d),missing='all')
            self.assertEqual(l.summary()['request_count'],4)
            self.assertEqual(r['common_request_sha256'],{})
            self.assertTrue((Path(d)/'reviews').is_dir())
            self.assertTrue(all(s['disposition']=='skipped_missing_draft' for s in r['reviews']))

    def test_draft_tampering_after_freeze_is_rejected(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            self.fake_run(Path(d),tamper=True)

    def test_extra_common_input_difference_is_rejected(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaisesRegex(ValueError,'common request'):
            self.fake_run(Path(d),difference=True)


if __name__=='__main__':unittest.main()
