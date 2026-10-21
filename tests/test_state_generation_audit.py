"""Saved cold-start receipts: synthetic records, never model or source execution."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rsi_eval.pilot_budget import BudgetLedger
from rsi_eval.state_generation import build_inputs, GenerationController

ROOT = Path(__file__).resolve().parents[1]
try:
    audit_module = importlib.import_module('scripts.analyze_state_generation')
except ModuleNotFoundError as error:
    if error.name != 'scripts.analyze_state_generation':
        raise
    audit_module = None


def raw(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw(value) + b'\n')


class Availability(unittest.TestCase):
    def test_offline_auditor_implemented(self):
        self.assertIsNotNone(audit_module, 'Cold-start offline auditor is not implemented')


@unittest.skipIf(audit_module is None, 'auditor not implemented yet')
class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        examples = json.loads((ROOT/'artifacts/edit-commitment/2026-10-21/v01/reviews/P-format-self/task-packet.json').read_text())['public_examples']
        self.inputs = build_inputs(ROOT, examples)
        self.slot = self.inputs['slots'][0]
        self.directory = self.run/'session'
        self.controller = GenerationController(self.slot, self.directory)
        self.config = dict(self.inputs['config']['budgets'], session_ids=[s['id'] for s in self.inputs['slots']])
        self.ledger = BudgetLedger(self.run/'budget-ledger.json', **self.config)
        self.payload = dict(model='synthetic-test-model', max_output_tokens=8192,
            messages=[dict(role='system', content='Synthetic audit fixture.'),
                      dict(role='user', content=raw(self.slot['packet']).decode())],
            tools=[dict(type='function', function={'name':name}) for name in ('submit_candidate','finish')],
            tool_choice='auto')
        self.request_id = self.ledger.reserve(self.slot['id'], self.payload, 8192)
        save(self.directory/'requests'/f'{self.request_id}.request.json', self.payload)
        save(self.directory/'task-packet.json', self.slot['packet'])
        self.source = 'def get_plan(objects, init, goal):\n    return []\n'
        self.business = dict(source=self.source, n_params=0)

    def response(self, *, business=None, error=None, unknown=False, tool='submit_candidate', dispatch=True):
        supplied = copy.deepcopy(self.business if business is None else business)
        usage = None if unknown else dict(prompt_tokens=100, completion_tokens=40, total_tokens=140)
        response = dict(usage=usage, choices=[dict(message={'tool_calls':[
            {'function':{'name':tool,'arguments':raw(supplied).decode()}}]})])
        if error: response['error_type'] = error
        save(self.directory/'requests'/f'{self.request_id}.response.json', response)
        self.ledger.settle(self.request_id, usage, error_type=error)
        if dispatch:
            save(self.directory/'sdk-submission.json', dict(stage='generation', tool='submit_candidate',
                session_id=self.slot['id'], business=self.business))
            self.controller.submit(self.slot['id'], **self.business)
        return self.controller.candidate

    def row(self):
        return json.loads((self.run/'budget-ledger.json').read_text())['requests'][0]

    def audit(self, artifact=None, allow_incomplete=False):
        return audit_module.audit_request(self.directory, self.row(), self.slot,
            artifact=artifact, allow_incomplete=allow_incomplete)

    def test_valid_source_binds_raw_response_sdk_and_bytes_without_execution(self):
        candidate = self.response()
        self.assertTrue(self.audit(candidate)['submitted'])
        self.assertEqual(self.audit(candidate)['usage']['total_tokens'], 140)

    def test_documented_sdk_metadata_is_removed_and_source_is_preserved(self):
        candidate = self.response(business={**self.business, 'summary':'fixture', 'security_risk':'LOW'})
        self.assertTrue(self.audit(candidate)['submitted'])

    def test_source_bytes_cannot_be_replaced_after_dispatch(self):
        candidate = self.response()
        (self.directory/'source.py').write_text('raise RuntimeError("must never run")\n')
        with self.assertRaises(ValueError): self.audit(candidate)

    def test_candidate_parameter_count_must_match_sdk(self):
        candidate = self.response(); candidate['n_params'] = 1
        with self.assertRaises(ValueError): self.audit(candidate)

    def test_request_packet_must_match_frozen_slot_not_just_rehashed_ledger(self):
        candidate = self.response(); self.slot = copy.deepcopy(self.slot)
        self.slot['packet']['instructions'] += '\nLeaked prior score.'
        self.slot['packet_sha256'] = hashlib.sha256(raw(self.slot['packet'])).hexdigest()
        with self.assertRaises(ValueError): self.audit(candidate)

    def test_raw_extra_business_field_is_not_silently_removed(self):
        candidate = self.response(business={**self.business, 'score':1})
        with self.assertRaises(ValueError): self.audit(candidate)

    def test_raw_numeric_coercion_is_not_claimed_as_audited(self):
        candidate = self.response(business={**self.business, 'n_params':'0'})
        with self.assertRaises(ValueError): self.audit(candidate)

    def test_known_schema_failure_can_remain_missing_without_replacement(self):
        self.response(business={**self.business, 'score':1}, dispatch=False)
        result = self.audit()
        self.assertFalse(result['submitted'])
        self.assertFalse(result['incomplete'])

    def test_finish_without_source_is_preserved_as_missing(self):
        self.response(business={'message':'done'}, tool='finish', dispatch=False)
        self.assertFalse(self.audit()['submitted'])

    def test_unknown_usage_kept_as_incomplete_not_zero_cost(self):
        self.response(unknown=True, error='Timeout', dispatch=False)
        with self.assertRaises(ValueError): self.audit()
        self.assertTrue(self.audit(allow_incomplete=True)['incomplete'])
        result = audit_module.audit_budget_state(json.loads((self.run/'budget-ledger.json').read_text()),
            self.ledger.summary(), self.config, allow_incomplete=True)
        self.assertIsNone(result['actual_estimated_cost_cny'])
        self.assertEqual(result['usage_unknown_count'], 1)

    def test_known_budget_totals_and_reservations_are_recomputed(self):
        self.response()
        value = json.loads((self.run/'budget-ledger.json').read_text())
        result = audit_module.audit_budget_state(value, self.ledger.summary(), self.config)
        self.assertEqual(result['known_total_tokens'], 140)
        changed = self.ledger.summary(); changed['reserved_cost_cny'] = 0
        with self.assertRaises(ValueError): audit_module.audit_budget_state(value, changed, self.config)

    def test_unknown_response_cannot_have_accepted_source(self):
        candidate = self.response(unknown=True, dispatch=True)
        with self.assertRaises(ValueError): self.audit(candidate, allow_incomplete=True)

    def test_missing_response_and_reserved_request_require_incomplete_scope(self):
        with self.assertRaises(ValueError): self.audit()
        self.assertTrue(self.audit(allow_incomplete=True)['incomplete'])
        result = audit_module.audit_budget_state(json.loads((self.run/'budget-ledger.json').read_text()),
            self.ledger.summary(), self.config, allow_incomplete=True)
        self.assertEqual(result['reserved_count'], 1)

    def test_sdk_single_text_system_block_is_supported_exactly(self):
        payload=copy.deepcopy(self.payload)
        payload['messages'][0]['content']=[dict(type='text',text='Synthetic audit fixture.')]
        self.assertEqual(audit_module._packet(payload),self.slot['packet'])

    def test_extra_or_mixed_system_blocks_are_rejected(self):
        for content in ([dict(type='text',text='one'),dict(type='text',text='hidden')],
                        [dict(type='image_url',image_url={'url':'hidden'})],
                        [dict(type='text',text='one',hidden='leak')]):
            payload=copy.deepcopy(self.payload);payload['messages'][0]['content']=content
            with self.subTest(content=content),self.assertRaises(ValueError):audit_module._packet(payload)


@unittest.skipIf(audit_module is None, 'auditor not implemented yet')
class OutputTests(unittest.TestCase):
    def test_output_does_not_overwrite_history_or_existing_different_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit_module.write_output(root, root/'tmp/report.json', {'a':1})
            audit_module.write_output(root, root/'tmp/report.json', {'a':1})
            with self.assertRaises(ValueError): audit_module.write_output(root, root/'tmp/report.json', {'a':2})
            with self.assertRaises(ValueError): audit_module.write_output(root, root/'artifacts/report.json', {})


@unittest.skipIf(audit_module is None, 'auditor not implemented yet')
class CompleteRecordTests(unittest.TestCase):
    """Real runner/controller/budget; provider and Git provenance are fixtures."""
    def setUp(self):
        from scripts.run_state_generation import execute, sha
        from scripts.run_checked_feedback import _model_configuration
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.run=Path(self.temp.name)/'run';self.run.mkdir()
        examples=json.loads((ROOT/'artifacts/edit-commitment/2026-10-21/v01/reviews/P-format-self/task-packet.json').read_text())['public_examples']
        self.inputs=build_inputs(ROOT,examples);self.config=self.inputs['config'];self.mode='normal'
        save(self.run/'input-freeze.json',self.inputs)
        save(self.run/'history-index.json',dict(version='history-source-index-v0.1',files={}))
        save(self.run/'runtime-freeze.json',dict(runtime_commit='a'*40,runtime_files_sha256={},checkout_clean=True))
        save(self.run/'config.json',self.config)
        config_digest,public,effective=_model_configuration(ROOT/'configs/models/minimax-m3.json',self.config['budgets'])
        save(self.run/'generation-settings.json',dict(model_config_sha256=config_digest,public=public,effective=effective))
        self.model=effective['model']
        self.report=dict(version='state-generation-run-v0.1',run_id='synthetic',status='running',runtime_commit='a'*40,
            inputs_freeze_sha256=sha(self.run/'input-freeze.json'),history_index_sha256=sha(self.run/'history-index.json'),
            model_config_sha256=config_digest,model_config=public,effective_model_config=effective,
            candidate_executions=0,task_evaluations=0,probe_executions=0,sealed_tasks_executed=0,strategy_updates=0,
            model_weight_updates=0,symbolic_csv_reads=0,resumed=False,
            slots=[dict({k:s[k] for k in ('id','family','role','task_ids','input_dimension')},status='not_started',
                disposition='not_started',request_id=None,candidate=None,session_summary=None) for s in self.inputs['slots']])
        self.ledger=BudgetLedger(self.run/'budget-ledger.json',**self.config['budgets'],
            session_ids=[s['id'] for s in self.inputs['slots']])
        self.execute=execute

    def session(self,c,row,directory):
        constants=audit_module._literal_constants(ROOT)
        tool=dict(name='submit_candidate',description=constants['TOOL_DESCRIPTION'],parameters=dict(type='object',
            properties={'source':{'type':'string'},'n_params':{'type':'integer','minimum':0,'maximum':16}},required=['source','n_params']))
        payload=dict(model=self.model,max_output_tokens=8192,tool_choice='auto',
            messages=[dict(role='system',content=[dict(type='text',text=constants['GENERATION_SYSTEM_PROMPT'])]),dict(role='user',content=raw(c.task_packet()).decode())],
            tools=[dict(type='function',function=tool),dict(type='function',function={'name':'finish'})])
        rid=self.ledger.reserve(row['id'],payload,8192)
        save(directory/'requests'/f'{rid}.request.json',payload)
        save(directory/'requests/packet-0001.json',c.task_packet())
        request=json.loads((self.run/'budget-ledger.json').read_text())['requests'][-1]
        save(directory/'requests/input-audit-0001.json',dict(version='input-audit-v0.1',attempt_index=1,
            session_id=row['id'],request_id=rid,max_input_bytes=65536,actual_input_bytes=request['input_bytes'],
            payload_sha256=request['payload_sha256'],excess_bytes=0,request_reserved=True,
            network_dispatch_attempted=True,transport_called=True,status='completed',reason=None))
        usage=dict(prompt_tokens=100,completion_tokens=40,total_tokens=140)
        error=None
        if self.mode=='unknown' and row['id']=='P-select-1':
            usage=None;error='Timeout';response={'error_type':error}
        elif self.mode=='missing' and row['id']=='P-select-1':
            response=dict(usage=usage,choices=[dict(message={'tool_calls':[{'function':{'name':'finish','arguments':'{}'}}]})])
        else:
            names=['objects','init','goal'] if row['family']=='planning' else [f'u{i}' for i in range(row['input_dimension'])]+['params']
            name='get_plan' if row['family']=='planning' else 'equation'
            source='raise RuntimeError("never execute this fixture")\ndef '+name+'('+','.join(names)+'):\n    return []\n'
            business=dict(source=source,n_params=0)
            response=dict(usage=usage,choices=[dict(message={'tool_calls':[{'function':{'name':'submit_candidate','arguments':raw(business).decode()}}]})])
        save(directory/'requests'/f'{rid}.response.json',response)
        self.ledger.settle(rid,usage,error_type=error)
        if error is None and not (self.mode=='missing' and row['id']=='P-select-1'):
            save(directory/'sdk-submission.json',dict(stage='generation',tool='submit_candidate',session_id=row['id'],business=business))
            c.submit(row['id'],**business)
        summary=dict(session_id=row['id'],stage='generation',adapter_version='state-generation-agent-v0.1',
            status='error' if error else 'completed',model_error_type=error,sdk_version='1.55.1',
            tools=['finish','submit_candidate'],controller=c.summary())
        save(directory/'session-summary.json',summary)
        return summary

    def build(self,mode='normal'):
        self.mode=mode
        self.execute(ROOT,self.run,self.report,self.inputs,self.ledger,self.session)

    def inspect(self):
        with patch.object(audit_module,'_runtime',return_value='a'*40),patch.object(audit_module,'_history'):
            return audit_module.audit(ROOT,self.run)

    def test_all_eight_sources_are_static_and_allocation_fully_accounted(self):
        self.build();result=self.inspect()
        self.assertEqual(result['status'],'passed');self.assertEqual(result['accepted_sources'],8)
        self.assertEqual(result['model_requests'],8);self.assertEqual(result['candidate_executions'],0)
        self.assertTrue(result['static_analysis']['cross_role_ast_duplicates'])

    def test_one_missing_slot_is_kept_with_eight_attempts(self):
        self.build('missing');result=self.inspect()
        self.assertEqual(result['status'],'passed');self.assertEqual(result['accepted_sources'],7)
        self.assertEqual(result['missing_or_unattempted_sources'],1)

    def test_stopped_round_preserves_unknown_usage_and_unattempted_slots(self):
        self.build('unknown');result=self.inspect()
        self.assertEqual(result['status'],'record_consistent_incomplete')
        self.assertFalse(result['allocation_completed']);self.assertEqual(result['model_requests'],1)
        self.assertEqual(result['accepted_sources'],0);self.assertIsNone(result['actual_estimated_cost_cny'])

    def test_source_changed_after_freeze_fails_before_static_report_is_trusted(self):
        self.build();(self.run/'sessions/P-select-1/source.py').write_text('pass\n')
        with self.assertRaisesRegex(ValueError,'inventory'):self.inspect()

    def test_rehashing_static_report_cannot_forge_new_source_count(self):
        self.build()
        analysis=json.loads((self.run/'static-analysis.json').read_text());analysis['distinct_source_count']=8
        save(self.run/'static-analysis.json',analysis)
        summary=json.loads((self.run/'summary.json').read_text())
        summary['analysis_sha256']=hashlib.sha256((self.run/'static-analysis.json').read_bytes()).hexdigest()
        save(self.run/'summary.json',summary)
        with self.assertRaisesRegex(ValueError,'static analysis'):self.inspect()

    def test_extra_session_file_cannot_escape_source_freeze(self):
        self.build();save(self.run/'sessions/P-select-1/evaluation.json',{'score':10})
        with self.assertRaisesRegex(ValueError,'inventory'):self.inspect()

    def test_completed_claim_cannot_hide_unattempted_slots(self):
        self.build('unknown');summary=json.loads((self.run/'summary.json').read_text())
        summary['status']='attempts_completed';save(self.run/'summary.json',summary)
        with self.assertRaises(ValueError):self.inspect()


if __name__ == '__main__': unittest.main()
