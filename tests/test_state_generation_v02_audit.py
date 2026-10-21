"""V02 audit boundaries: real receipts and configuration, no model or source execution."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

try:
    from scripts import analyze_state_generation_v02 as auditor
except ImportError:
    auditor = None


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


class ImplementationTests(unittest.TestCase):
    def test_v02_auditor_exists_without_replacing_legacy_module(self):
        self.assertIsNotNone(auditor, 'A separate v02 auditor is required')


@unittest.skipIf(auditor is None, 'v02 auditor is not implemented')
class TransportReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.row = {'request_id':'request-0001', 'session_id':'P-select-1',
                    'status':'settled', 'usage_state':'known', 'error_type':None}
        save(self.directory/'requests/request-0001.request.json', {'model':'anthropic/MiniMax-M3'})
        save(self.directory/'requests/request-0001.response.json', {'usage':{'total_tokens':2}})
        self.request = dict(version='state-generation-transport-v0.1', expected_timeout_seconds=180,
            timeout_seconds=180, max_retries=0, stream_present=False, stream=False,
            num_retries_present=False, num_retries=None,
            request_file='requests/request-0001.request.json',
            request_sha256=sha(self.directory/'requests/request-0001.request.json'))
        self.result = dict(version='state-generation-transport-v0.1', request_receipt_sha256='',
                           elapsed_seconds=0.125, status='returned', error_type=None)
        self.write()

    def write(self):
        save(self.directory/'transport-request.json', self.request)
        self.result['request_receipt_sha256'] = sha(self.directory/'transport-request.json')
        save(self.directory/'transport-result.json', self.result)

    def inspect(self, **kwargs):
        return auditor.audit_transport(self.directory, self.row, expected_timeout=180, **kwargs)

    def test_transport_180_observed_at_bound_request_is_verified(self):
        result = self.inspect()
        self.assertTrue(result['observed']); self.assertFalse(result['incomplete'])
        self.assertEqual(result['timeout_seconds'], 180)

    def test_configuration_180_cannot_hide_provider_boundary_60(self):
        self.request['timeout_seconds']=60; self.write()
        with self.assertRaisesRegex(ValueError, 'timeout'): self.inspect()

    def test_retry_enabling_or_boolean_zero_is_rejected(self):
        for key,value in [('max_retries',1),('max_retries',False),('num_retries',1)]:
            with self.subTest(key=key,value=value):
                original=copy.deepcopy(self.request)
                self.request[key]=value
                if key=='num_retries': self.request['num_retries_present']=True
                self.write()
                with self.assertRaises(ValueError): self.inspect()
                self.request=original

    def test_presence_and_safe_receipt_schema_are_checked(self):
        for change in ({'stream_present':False,'stream':True},
                       {'num_retries_present':False,'num_retries':0},
                       {'api_key':'must-not-be-an-audit-field'}):
            with self.subTest(change=change):
                original=copy.deepcopy(self.request);self.request.update(change);self.write()
                with self.assertRaises(ValueError):self.inspect()
                self.request=original

    def test_request_file_replacement_cannot_escape_receipt_binding(self):
        save(self.directory/'requests/request-0001.request.json', {'model':'changed'})
        with self.assertRaisesRegex(ValueError, 'request'):self.inspect()

    def test_wrong_request_slot_cannot_borrow_another_transport_receipt(self):
        self.row['request_id']='request-0002'
        with self.assertRaises(ValueError):self.inspect()

    def test_result_rebinding_and_nonfinite_elapsed_are_rejected(self):
        for change in ({'request_receipt_sha256':'0'*64}, {'elapsed_seconds':-1},
                       {'elapsed_seconds':float('nan')}, {'elapsed_seconds':True}):
            with self.subTest(change=change):
                value=dict(self.result,**change);save(self.directory/'transport-result.json',value)
                with self.assertRaises(ValueError):self.inspect()

    def test_recorded_timeout_retains_observed_dispatch_and_unknown_usage(self):
        self.row.update(status='failed', usage_state='unknown', error_type='Timeout')
        self.result.update(status='raised', error_type='Timeout');self.write()
        result=self.inspect(allow_incomplete=True)
        self.assertTrue(result['observed']);self.assertEqual(result['status'],'raised')

    def test_missing_result_is_incomplete_and_cannot_pass_complete_run(self):
        (self.directory/'transport-result.json').unlink()
        with self.assertRaises(ValueError):self.inspect()
        result=self.inspect(allow_incomplete=True)
        self.assertTrue(result['incomplete'])

    def test_missing_receipts_never_mean_verified_timeout(self):
        (self.directory/'transport-request.json').unlink()
        (self.directory/'transport-result.json').unlink()
        with self.assertRaises(ValueError):self.inspect()
        result=self.inspect(allow_incomplete=True)
        self.assertFalse(result['observed']);self.assertTrue(result['incomplete'])


@unittest.skipIf(auditor is None, 'v02 auditor is not implemented')
class BatchRecordTests(unittest.TestCase):
    """Real legacy core/budget/freeze; synthetic provider and Git provenance only."""
    def setUp(self):
        from tests import test_state_generation_audit as fixtures
        from scripts.run_state_generation_v02 import batch_snapshot, model_configuration
        self.fixture=fixtures.CompleteRecordTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=fixtures.ROOT;self.run=self.fixture.run;self.report=self.fixture.report
        self.report['version']='state-generation-run-v0.2'
        save(self.run/'batch-freeze.json',batch_snapshot(self.root))
        self.report['batch_freeze_sha256']=sha(self.run/'batch-freeze.json')
        digest,public,effective=model_configuration(self.root,self.fixture.config['budgets'])
        self.report.update(model_config_sha256=digest,model_config=public,effective_model_config=effective)
        save(self.run/'generation-settings.json',dict(model_config_sha256=digest,public=public,effective=effective))
        session=self.fixture.session
        def with_transport(controller,row,directory):
            result=session(controller,row,directory)
            request=next((directory/'requests').glob('*.request.json'))
            save(directory/'transport-request.json',dict(version='state-generation-transport-v0.1',
                expected_timeout_seconds=180,timeout_seconds=180,max_retries=0,
                stream_present=False,stream=False,num_retries_present=False,num_retries=None,
                request_file='requests/'+request.name,request_sha256=sha(request)))
            error=result['model_error_type']
            save(directory/'transport-result.json',dict(version='state-generation-transport-v0.1',
                request_receipt_sha256=sha(directory/'transport-request.json'),elapsed_seconds=0.5,
                status='raised' if error else 'returned',error_type=error))
            return result
        self.fixture.session=with_transport

    def build(self,mode='normal'):self.fixture.build(mode)

    def inspect(self):
        with patch.object(auditor,'_runtime',return_value='a'*40),patch.object(auditor.base,'_history'):
            return auditor.audit(self.root,self.run)

    def rewrite_summary(self,change):
        value=json.loads((self.run/'summary.json').read_text());value.update(change)
        save(self.run/'summary.json',value)

    def test_complete_v02_has_eight_observed_180_dispatches(self):
        self.build();result=self.inspect()
        self.assertEqual(result['status'],'passed');self.assertTrue(result['allocation_completed'])
        self.assertEqual(result['accepted_sources'],8);self.assertEqual(result['observed_transport_calls'],8)
        self.assertEqual(result['effective_timeout_seconds'],180)
        self.assertEqual(result['candidate_executions'],0)

    def test_unknown_timeout_stops_and_preserves_null_actual_cost(self):
        self.build('unknown');result=self.inspect()
        self.assertEqual(result['status'],'record_consistent_incomplete')
        self.assertEqual(result['model_requests'],1);self.assertEqual(result['observed_transport_calls'],1)
        self.assertEqual(result['accepted_sources'],0);self.assertEqual(result['unknown_usage_requests'],1)
        self.assertIsNone(result['actual_estimated_cost_cny']);self.assertFalse(result['allocation_completed'])

    def test_known_usage_missing_source_is_not_invented(self):
        self.build('missing');result=self.inspect()
        self.assertEqual(result['status'],'passed');self.assertEqual(result['accepted_sources'],7)
        self.assertEqual(result['missing_or_unattempted_sources'],1)

    def test_old_batch_cannot_be_relabelled_without_batch_freeze(self):
        self.build();(self.run/'batch-freeze.json').unlink()
        with self.assertRaisesRegex(ValueError,'batch-freeze'):self.inspect()

    def test_effective_60_cannot_be_certified_by_v02_batch_label(self):
        self.build();settings=json.loads((self.run/'generation-settings.json').read_text())
        settings['effective']['timeout']=60;save(self.run/'generation-settings.json',settings)
        self.rewrite_summary({'effective_model_config':settings['effective']})
        with self.assertRaisesRegex(ValueError,'Model configuration'):self.inspect()

    def test_rehashed_batch_cannot_change_python_protocol_or_predecessor(self):
        self.build();original=json.loads((self.run/'batch-freeze.json').read_text())
        for change in ({'python_version':'3.10.12'}, {'protocol_sha256':'0'*64},
                       {'previous_archive_manifest_sha256':'0'*64}):
            with self.subTest(change=change):
                save(self.run/'batch-freeze.json',dict(original,**change))
                self.rewrite_summary({'batch_freeze_sha256':sha(self.run/'batch-freeze.json')})
                with self.assertRaisesRegex(ValueError,'batch'):self.inspect()

    def test_source_and_transport_are_both_bound_before_analysis(self):
        self.build();path=self.run/'sessions/P-select-1/transport-request.json'
        value=json.loads(path.read_text());value['timeout_seconds']=60;save(path,value)
        with self.assertRaisesRegex(ValueError,'Frozen source'):self.inspect()

    def test_completed_label_cannot_hide_seven_unattempted_slots(self):
        self.build('unknown');self.rewrite_summary({'status':'attempts_completed'})
        with self.assertRaises(ValueError):self.inspect()

    def test_v01_schema_is_not_implicitly_converted(self):
        self.build();self.rewrite_summary({'version':'state-generation-run-v0.1'})
        with self.assertRaisesRegex(ValueError,'v02'):self.inspect()

    def test_prepared_batch_does_not_claim_observed_transport(self):
        self.report.update(status='prepared',budget=self.fixture.ledger.summary())
        save(self.run/'summary.json',self.report)
        result=self.inspect()
        self.assertEqual(result['status'],'prepared_checked')
        self.assertEqual(result['observed_transport_calls'],0)
        self.assertFalse(result['allocation_completed'])


@unittest.skipIf(auditor is None, 'v02 auditor is not implemented')
class RuntimeAnchorTests(unittest.TestCase):
    """A small real Git repository checks inventory and blob/current-file bindings."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        names=[auditor.PROTOCOL,auditor.BATCH_CONFIG,auditor.base.PROTOCOL,
            'docs/protocols/2026-10-21-two-stage-v0.1.md',
            'scripts/run_state_generation_v02.py','scripts/analyze_state_generation_v02.py',
            'scripts/run_state_generation.py','scripts/analyze_state_generation.py',
            'rsi_eval/state_generation_transport.py','tests/test_state_generation_v02_audit.py',
            'tests/test_state_generation_transport.py','prompts/frozen-task.md']
        for name in names:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('# audit fixture '+name+'\n',encoding='utf-8')
        self.git('init','-q');self.git('config','core.autocrlf','false');self.git('add','.')
        self.git('-c','user.name=Audit Fixture','-c','user.email=fixture@example.invalid',
                 '-c','core.hooksPath='+str(self.root/'absent-hooks'),'commit','-qm','fixture')
        self.commit=self.git('rev-parse','HEAD').strip()
        self.freeze=dict(runtime_commit=self.commit,checkout_clean=True,
                         runtime_files_sha256={name:sha(self.root/name) for name in names})
        self.report={'runtime_commit':self.commit}

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.root),*args],text=True,stderr=subprocess.PIPE)

    def test_v02_protocol_and_both_generations_are_anchored_to_git(self):
        self.assertEqual(auditor._runtime(self.root,self.freeze,self.report),self.commit)

    def test_runtime_cannot_drop_a_tracked_transitive_test_or_prompt(self):
        for name in ('tests/test_state_generation_transport.py','prompts/frozen-task.md'):
            with self.subTest(name=name):
                value=copy.deepcopy(self.freeze);value['runtime_files_sha256'].pop(name)
                with self.assertRaisesRegex(ValueError,'inventory'):
                    auditor._runtime(self.root,value,self.report)

    def test_current_file_and_rehashed_inventory_must_still_match_git_blob(self):
        name='scripts/run_state_generation_v02.py';(self.root/name).write_text('# changed\n')
        self.freeze['runtime_files_sha256'][name]=sha(self.root/name)
        with self.assertRaisesRegex(ValueError,'Frozen runtime'):
            auditor._runtime(self.root,self.freeze,self.report)


if __name__=='__main__':unittest.main()
