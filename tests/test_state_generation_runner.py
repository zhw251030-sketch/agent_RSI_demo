import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.run_state_generation import (canonical, history_index, static_source,
    freeze_sources, analyze_frozen_sources, execute, create_json, sha, new_output)
from rsi_eval.pilot_budget import BudgetLedger


class FakeController:
    def __init__(self,slot,output_dir):
        self.slot=slot;self.output_dir=Path(output_dir);self.output_dir.mkdir(parents=True)
        self.candidate=None;self.halted=False
    def task_packet(self):return self.slot['packet']
    def summary(self):return {'candidate':self.candidate}
    def submit(self,session_id,source,n_params):
        (self.output_dir/'source.py').write_bytes(source.encode())
        self.candidate=dict(version='state-generation-candidate-v0.1',slot_id=session_id,
            family=self.slot['family'],origin='model_generated_without_task_feedback',
            status='stored_unexecuted',source_file='source.py',source_sha256=sha(self.output_dir/'source.py'),
            n_params=n_params,packet_sha256=self.slot['packet_sha256'])
        create_json(self.output_dir/'candidate.json',self.candidate)


class GenerationRunnerTests(unittest.TestCase):
    def test_ast_ignores_comments_and_layout_but_not_program(self):
        a=static_source('def get_plan(objects, init, goal):\n return []\n','planning',None)
        b=static_source('# note\ndef get_plan(objects,init,goal):\n    return []\n','planning',None)
        c=static_source('def get_plan(objects,init,goal):\n return [1]\n','planning',None)
        self.assertEqual(a['ast_sha256'],b['ast_sha256']);self.assertNotEqual(a['ast_sha256'],c['ast_sha256'])
        self.assertTrue(a['entry_signature_matches']);self.assertFalse(a['executed'])
    def test_syntax_failure_is_preserved_not_executed(self):
        row=static_source('not python !','symbolic',3)
        self.assertEqual(row['parse_status'],'syntax_error');self.assertIsNone(row['ast_sha256'])
    def test_signature_is_not_an_execution_score(self):
        row=static_source('def equation(u0,params):\n raise RuntimeError()\n','symbolic',1)
        self.assertTrue(row['entry_signature_matches']);self.assertFalse(row['executed'])
        self.assertFalse(static_source('def equation(*args):\n return 0\n','symbolic',3)['entry_signature_matches'])
    def test_source_does_not_execute_top_level(self):
        with patch('builtins.exec',side_effect=AssertionError('execution forbidden')):
            row=static_source('raise RuntimeError("never execute")\ndef equation(u0,params):\n return u0\n','symbolic',1)
        self.assertEqual(row['parse_status'],'parsed')
    def test_history_index_does_not_read_data_and_marks_malformed(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);(r/'artifacts/old').mkdir(parents=True)
            (r/'artifacts/old/a.py').write_text('def f(): pass\n')
            (r/'artifacts/old/b.py').write_text('!')
            (r/'data').mkdir();(r/'data/secret.csv').write_text('not accessed')
            idx=history_index(r)
            self.assertEqual(set(idx['files']),{'artifacts/old/a.py','artifacts/old/b.py'})
            self.assertIsNone(idx['files']['artifacts/old/b.py']['ast_sha256'])
    def test_create_json_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.json';create_json(p,{'a':1})
            with self.assertRaises(FileExistsError):create_json(p,{'a':1})
    def test_existing_run_is_never_returned_for_error_summary_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out=new_output(root,'saved')
            create_json(out/'summary.json',{'old':'immutable'})
            with self.assertRaises(FileExistsError):new_output(root,'saved')
            self.assertEqual(json.loads((out/'summary.json').read_text()),{'old':'immutable'})
    def make_run(self,r):
        out=r/'runs/test';out.mkdir(parents=True)
        slots=[]
        for ident,role in [('P-select-1','selection'),('P-eval-1','evaluation')]:
            packet={'family':'planning','instructions':'create'}
            slots.append(dict(id=ident,family='planning',role=role,task_ids=['fake'],input_dimension=None,
                packet=packet,packet_sha256=__import__('hashlib').sha256(canonical(packet)).hexdigest()))
        inputs={'version':'fixture','source_bindings':{},'slots':slots}
        create_json(out/'input-freeze.json',inputs)
        create_json(out/'runtime-freeze.json',{'runtime_commit':'a'*40,'runtime_files_sha256':{}})
        create_json(out/'history-index.json',{'version':'history-source-index-v0.1','files':{}})
        ledger=BudgetLedger(out/'budget-ledger.json',max_requests=2,max_requests_per_session=1,
            max_output_tokens=8192,max_input_bytes=65536,session_ids=[s['id'] for s in slots])
        report=dict(version='state-generation-run-v0.1',run_id='fixture',status='running',runtime_commit='a'*40,
            inputs_freeze_sha256=sha(out/'input-freeze.json'),history_index_sha256=sha(out/'history-index.json'),
            slots=[{**{k:s[k] for k in ('id','family','role','task_ids','input_dimension')},
                'status':'not_started','disposition':'not_started','request_id':None,'candidate':None,'session_summary':None} for s in slots])
        return out,inputs,ledger,report
    def test_all_sources_freeze_before_analysis_and_duplicates_remain(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);out,inputs,ledger,report=self.make_run(r)
            def session(c,row,directory):
                self.assertFalse((out/'source-freeze.json').exists());self.assertFalse((out/'static-analysis.json').exists())
                rid=ledger.reserve(row['id'],{'fixture':True},8192)
                c.submit(row['id'],'def get_plan(objects,init,goal):\n return []\n',0)
                ledger.settle(rid,dict(prompt_tokens=1,completion_tokens=1,total_tokens=2))
                return {'status':'completed','model_error_type':None}
            with patch('scripts.run_state_generation.GenerationController',FakeController):
                execute(r,out,report,inputs,ledger,session)
            self.assertEqual(report['status'],'attempts_completed')
            analysis=analyze_frozen_sources(out)
            self.assertEqual(analysis['available_sources'],2)
            self.assertEqual(analysis['distinct_source_count'],1)
            self.assertTrue(analysis['cross_role_ast_duplicates'])
            self.assertEqual(report['budget']['request_count'],2)
    def test_unknown_usage_stops_remaining_slots_without_resampling(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);out,inputs,ledger,report=self.make_run(r)
            def session(c,row,directory):
                rid=ledger.reserve(row['id'],{'fixture':True},8192);ledger.settle(rid,None,'RuntimeError')
                return {'status':'error','model_error_type':'RuntimeError'}
            with patch('scripts.run_state_generation.GenerationController',FakeController):
                execute(r,out,report,inputs,ledger,session)
            self.assertEqual(report['status'],'stopped');self.assertEqual(report['budget']['request_count'],1)
            self.assertEqual(report['slots'][1]['disposition'],'not_started')
            self.assertEqual(analyze_frozen_sources(out)['available_sources'],0)
    def test_known_missing_continues_and_remains_missing(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);out,inputs,ledger,report=self.make_run(r)
            def session(c,row,directory):
                rid=ledger.reserve(row['id'],{},8192);ledger.settle(rid,dict(prompt_tokens=1,completion_tokens=1,total_tokens=2))
                return {'status':'completed','model_error_type':None}
            with patch('scripts.run_state_generation.GenerationController',FakeController):
                execute(r,out,report,inputs,ledger,session)
            self.assertEqual(report['status'],'attempts_completed');self.assertEqual(report['budget']['request_count'],2)
            self.assertTrue(all(s['disposition']=='missing' for s in report['slots']))
    def test_host_exception_preserves_prefix_and_freezes_stopped_run(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);out,inputs,ledger,report=self.make_run(r)
            def session(c,row,directory):
                rid=ledger.reserve(row['id'],{},8192)
                c.submit(row['id'],'def get_plan(objects,init,goal):\n return []\n',0)
                ledger.settle(rid,dict(prompt_tokens=1,completion_tokens=1,total_tokens=2))
                raise RuntimeError('untrusted sensitive message must not be saved')
            with patch('scripts.run_state_generation.GenerationController',FakeController):
                execute(r,out,report,inputs,ledger,session)
            self.assertEqual(report['status'],'stopped');self.assertEqual(report['slots'][0]['disposition'],'blocked')
            self.assertEqual(report['slots'][1]['disposition'],'not_started')
            self.assertTrue((out/'source-freeze.json').exists())
            self.assertNotIn('sensitive message', (out/'summary.json').read_text())
    def test_runtime_tamper_after_request_preserves_unverified_snapshot_only(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);out,inputs,ledger,report=self.make_run(r)
            def session(c,row,directory):
                rid=ledger.reserve(row['id'],{},8192);ledger.settle(rid,dict(prompt_tokens=1,completion_tokens=1,total_tokens=2))
                (out/'input-freeze.json').write_text('{}')
                return {'status':'completed','model_error_type':None}
            with patch('scripts.run_state_generation.GenerationController',FakeController):
                execute(r,out,report,inputs,ledger,session)
            self.assertEqual(report['status'],'integrity_failed')
            self.assertEqual(report['budget']['request_count'],1)
            self.assertTrue((out/'unverified-source-snapshot.json').exists())
            self.assertFalse((out/'static-analysis.json').exists())
    def test_input_tamper_prevents_any_request(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);out,inputs,ledger,report=self.make_run(r)
            (out/'input-freeze.json').write_text('{}')
            with patch('scripts.run_state_generation.GenerationController',FakeController),self.assertRaises(ValueError):
                execute(r,out,report,inputs,ledger,lambda *a:self.fail('request occurred'))
    def test_static_audit_refuses_unfrozen_or_changed_sources(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            with self.assertRaises(ValueError):analyze_frozen_sources(out)
            create_json(out/'history-index.json',{'version':'history-source-index-v0.1','files':{}})
            (out/'sessions').mkdir();freeze_sources(out,dict(inputs_freeze_sha256='a',history_index_sha256=sha(out/'history-index.json'),runtime_commit='b',slots=[]))
            (out/'sessions/late.py').write_text('print(1)')
            with self.assertRaises(ValueError):analyze_frozen_sources(out)


if __name__=='__main__':unittest.main()
