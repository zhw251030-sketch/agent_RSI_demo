import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.run_two_stage import (ExecutionLedger, actor_order, classify_session,
    directory_hashes, verify_files, validate_config, CONFIG_PATH, ROOT)
from scripts.run_two_stage import execute,write,read,CASE_ORDER
from rsi_eval.pilot_budget import BudgetLedger
from rsi_eval.two_stage_cases import load_cases


class RunnerTests(unittest.TestCase):
    def test_exact_configuration_rejects_expansion_and_bool(self):
        config=json.loads((ROOT/CONFIG_PATH).read_bytes())
        validate_config(config)
        config['budgets']['max_requests']=13
        with self.assertRaises(ValueError):validate_config(config)
        config=json.loads((ROOT/CONFIG_PATH).read_bytes());config['sealed_tasks_executed']=False
        with self.assertRaises(ValueError):validate_config(config)

    def test_reserve_persists_before_execution_and_cannot_refund(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'executions.json';ledger=ExecutionLedger(p,2)
            token=ledger.reserve('one',2)
            self.assertEqual(json.loads(p.read_bytes())['reserved_sandbox_calls'],2)
            ledger.settle(token,{'sandbox_calls':1,'new_candidate_executions':1})
            with self.assertRaises(ValueError):ledger.reserve('two',1)
            self.assertEqual(ledger.summary()['actual']['sandbox_calls'],1)
            with self.assertRaises(ValueError):ledger.settle(token,{'sandbox_calls':1})

    def test_unaccounted_dispatch_stays_visible(self):
        with tempfile.TemporaryDirectory() as d:
            ledger=ExecutionLedger(Path(d)/'executions.json',2)
            ledger.reserve('lost',2)
            self.assertFalse(ledger.summary()['accounting_complete'])

    def test_count_above_reservation_fails(self):
        with tempfile.TemporaryDirectory() as d:
            ledger=ExecutionLedger(Path(d)/'executions.json',1);token=ledger.reserve('a',1)
            with self.assertRaises(ValueError):ledger.settle(token,{'sandbox_calls':2})

    def test_phase_hash_rejects_edit_and_extra_file(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'a').write_bytes(b'original');pins=directory_hashes(p)
            verify_files(p,pins)
            (p/'a').write_bytes(b'changed')
            with self.assertRaises(ValueError):verify_files(p,pins)
            (p/'a').write_bytes(b'original');(p/'extra').write_bytes(b'new')
            with self.assertRaises(ValueError):verify_files(p,pins)

    def test_finished_is_not_submission_and_unknown_usage_blocks(self):
        class C: halted=False
        safe={'halted':False,'usage_unknown_count':0,'reserved_count':0}
        self.assertEqual(classify_session({'status':'completed'},C(),safe,False),'missing')
        self.assertEqual(classify_session({'status':'stopped'},C(),safe,True),'available')
        self.assertEqual(classify_session({'status':'error','model_error_type':'PilotResponseContractError'},C(),safe,False),'missing')
        self.assertEqual(classify_session({'status':'completed'},C(),dict(safe,usage_unknown_count=1),True),'blocked')
        self.assertEqual(classify_session({'status':'error','model_error_type':'OSError'},C(),safe,False),'blocked')

    def test_balanced_order_and_single_opportunity(self):
        order=actor_order()
        self.assertEqual(len(order),8)
        for case in ('P-format-missing','P-prefix','S-cubic','S-square'):
            self.assertEqual({r['condition'] for r in order if r['case_id']==case},{'self','checked'})
        self.assertEqual(len({r['session_id'] for r in order}),8)

    def fake_run(self,root,unknown=False,tamper=False):
        config=read(ROOT/CONFIG_PATH);cases={c['id']:c for c in load_cases(ROOT)}
        report={'registrations':[dict(case_id=c,session_id=c+'-probe') for c in CASE_ORDER],
                'revisions':actor_order()}
        sessions=[r['session_id'] for r in report['registrations']+report['revisions']]
        ledger=BudgetLedger(root/'budget-ledger.json',session_ids=sessions,**config['budgets'])
        executions=ExecutionLedger(root/'executions.json',64)
        write(root/'runtime-freeze.json',{'runtime_files_sha256':{}})
        calls=[]
        def session(c,row,directory,stage):
            packet=c.task_packet();payload={'model':'mock','messages':[{'role':'user','content':json.dumps(packet)}]}
            rid=ledger.reserve(row['session_id'],payload,4096)
            write(directory/'requests'/(rid+'.request.json'),payload)
            ledger.settle(rid,None if unknown else {'prompt_tokens':10,'completion_tokens':5,'total_tokens':15})
            if stage=='probe':c.submit_probe(row['session_id'],c.case['probe_id'],c.case['target_id'],{})
            return {'status':'completed'}
        def probe(case,budget,directory):
            self.assertTrue((root/'registration-freeze.json').exists())
            self.assertEqual(len(read(root/'budget-ledger.json')['requests']),4)
            calls.append(case['id'])
            if tamper:
                write(root/'stage1'/CASE_ORDER[0]/'tampered.json',{})
            if case['family']=='planning':
                full={'results':[dict(task_id=t,source_sha256=case['source_sha256'],task_binding={'pilot_role':'prompt'},
                    status='completed',verdict='unknown',reason='fixture',executions={}) for t in case['prompt_task_ids']]}
            else:
                full=dict(case_id=case['id'],transformation={'source_sha256':case['source_sha256'],'parent_sha256':case['parent_sha256']},
                    verdict='unknown',status='unavailable',reason='fixture',epsilon=1e-5,tolerance=1e-10,
                    variants=[],dataset_identity=None,executions={})
            write(directory/'probe.json',full);return full
        execute(ROOT,root,report,cases,ledger,executions,session,probe,
                lambda *a,**kw:self.fail('No candidate was submitted'))
        return report,ledger,calls

    def test_complete_allocated_round_preserves_finish_missing_and_freezes_before_probes(self):
        with tempfile.TemporaryDirectory() as d:
            report,ledger,calls=self.fake_run(Path(d))
            self.assertEqual(report['status'],'attempts_completed')
            self.assertEqual(len(calls),4)
            self.assertEqual(ledger.summary()['request_count'],12)
            self.assertTrue(all(r['candidate'] is None and r['disposition']=='missing' for r in report['revisions']))
            self.assertEqual(len(report['common_request_sha256']),4)

    def test_unknown_usage_stops_before_all_followup_work(self):
        with tempfile.TemporaryDirectory() as d:
            report,ledger,calls=self.fake_run(Path(d),unknown=True)
            self.assertEqual(report['status'],'stopped');self.assertEqual(calls,[])
            self.assertEqual(ledger.summary()['request_count'],1)

    def test_changed_registration_cannot_reach_revision(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'Frozen phase files changed'):
                self.fake_run(Path(d),tamper=True)


if __name__=='__main__':unittest.main()
