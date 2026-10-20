"""Offline provenance and budget tampering tests; no SDK or executor is imported."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from rsi_eval.pilot_budget import BudgetLedger
from rsi_eval.two_stage_audit import audit_budget, audit_request


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class AuditTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)

    def fixture(self, stage='probe', raw=None):
        tool='submit_probe' if stage=='probe' else 'submit_candidate'
        business=({'probe_id':'P1','target_id':'T1','auxiliary':{}} if stage=='probe' else
            {'source':'def solve(): return []\n','n_params':0,'rationale':'one edit','auxiliary':{}})
        raw=copy.deepcopy(business) if raw is None else raw
        directory=self.root/stage;directory.mkdir()
        ledger=BudgetLedger(directory/'ledger.json',session_ids=['case-'+stage],
            max_requests=1,max_requests_per_session=1)
        payload={'model':'anthropic/MiniMax-M3','messages':[{'role':'user','content':'{}'}],
                 'tools':[{'type':'function','function':{'name':tool}}],
                 'tool_choice':None,'max_output_tokens':4096}
        rid=ledger.reserve('case-'+stage,payload,4096)
        usage={'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}
        ledger.settle(rid,usage)
        row=json.loads((directory/'ledger.json').read_text())['requests'][0]
        response={'response_id':'offline','usage':usage,'usage_details':{},'choices':[
            {'message':{'role':'assistant','content':'offline','tool_calls':[
                {'id':'call-1','type':'function','function':{'name':tool,'arguments':json.dumps(raw)}}]},
             'finish_reason':'tool_calls'}]}
        write(directory/'requests'/f'{rid}.request.json',payload)
        write(directory/'requests'/f'{rid}.response.json',response)
        write(directory/'sdk-submission.json',{'stage':stage,'tool':tool,
              'session_id':'case-'+stage,'business':business})
        registration={'status':'accepted',**business}
        candidate={'source_sha256':hashlib.sha256(business.get('source','').encode()).hexdigest(),
                   **{k:business[k] for k in ('n_params','rationale','auxiliary') if k in business}}
        if stage=='revision':(directory/'candidate.py').write_bytes(business['source'].encode('utf-8'))
        return directory,row,ledger,response,registration,candidate

    def test_probe_binds_documented_normalization_and_registration(self):
        d,row,_,_,reg,_=self.fixture(raw={'probe_id':'P1','target_id':'T1',
            'auxiliary':None,'summary':42,'security_risk':None})
        result=audit_request(d,row,stage='probe',session_id='case-probe',registration=reg)
        self.assertTrue(result['submitted'])

    def test_candidate_binds_saved_source_and_all_business_fields(self):
        d,row,_,_,_,candidate=self.fixture('revision')
        audit_request(d,row,stage='revision',session_id='case-revision',candidate=candidate)
        for field,value in [('n_params',1),('rationale','changed'),('auxiliary',{'new':True})]:
            altered={**candidate,field:value}
            with self.subTest(field=field),self.assertRaises(ValueError):
                audit_request(d,row,stage='revision',session_id='case-revision',candidate=altered)
        (d/'candidate.py').write_text('changed')
        with self.assertRaises(ValueError):
            audit_request(d,row,stage='revision',session_id='case-revision',candidate=candidate)

    def test_ledger_usage_cannot_disagree_with_raw_response(self):
        d,row,_,_,reg,_=self.fixture()
        row=copy.deepcopy(row);row['usage']['prompt_tokens']+=1;row['usage']['total_tokens']+=1
        with self.assertRaises(ValueError):audit_request(d,row,stage='probe',session_id='case-probe',registration=reg)

    def test_response_boolean_token_cannot_equal_integer_usage(self):
        d,row,_,response,reg,_=self.fixture()
        usage={'prompt_tokens':1,'completion_tokens':20,'total_tokens':21}
        row={**row,'usage':usage,'usage_sha256':hashlib.sha256(json.dumps(
            usage,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
        response['usage']={**usage,'prompt_tokens':True}
        write(d/'requests'/'request-0001.response.json',response)
        with self.assertRaises(ValueError):audit_request(d,row,stage='probe',session_id='case-probe',registration=reg)

    def test_invalid_counts_and_reservation_overflow_reject(self):
        d,row,_,_,reg,_=self.fixture()
        for usage in [{'prompt_tokens':True,'completion_tokens':20,'total_tokens':21},
                      {'prompt_tokens':-1,'completion_tokens':20,'total_tokens':19},
                      {'prompt_tokens':100,'completion_tokens':20,'total_tokens':121},
                      {'prompt_tokens':100,'completion_tokens':4097,'total_tokens':4197}]:
            altered={**row,'usage':usage}
            with self.subTest(usage=usage),self.assertRaises(ValueError):
                audit_request(d,altered,stage='probe',session_id='case-probe',registration=reg)

    def test_registration_auxiliary_and_sdk_session_are_bound(self):
        d,row,_,_,reg,_=self.fixture()
        with self.assertRaises(ValueError):
            audit_request(d,row,stage='probe',session_id='case-probe',registration={**reg,'auxiliary':{'new':True}})
        saved=json.loads((d/'sdk-submission.json').read_text());saved['session_id']='other'
        write(d/'sdk-submission.json',saved)
        with self.assertRaises(ValueError):audit_request(d,row,stage='probe',session_id='case-probe',registration=reg)

    def test_finish_has_no_submission_and_cannot_acquire_one(self):
        d,row,_,response,_,_=self.fixture()
        response['choices'][0]['message']['tool_calls'][0]['function']={
            'name':'finish','arguments':'{"message":"Done"}'}
        write(d/'requests'/'request-0001.response.json',response)
        with self.assertRaises(ValueError):audit_request(d,row,stage='probe',session_id='case-probe')
        (d/'sdk-submission.json').unlink()
        result=audit_request(d,row,stage='probe',session_id='case-probe')
        self.assertFalse(result['submitted'])

    def test_known_response_contract_failure_can_be_a_missing_slot(self):
        d,row,_,response,_,_=self.fixture()
        response['choices'][0]['message']['tool_calls']*=2
        response['error_type']='PilotResponseContractError'
        write(d/'requests'/'request-0001.response.json',response)
        row={**row,'status':'failed','error_type':'PilotResponseContractError'}
        (d/'sdk-submission.json').unlink()
        result=audit_request(d,row,stage='probe',session_id='case-probe')
        self.assertFalse(result['submitted'])

    def test_valid_business_rejection_requires_core_rejection_evidence(self):
        d,row,_,_,_,_=self.fixture()
        with self.assertRaises(ValueError):audit_request(d,row,stage='probe',session_id='case-probe')
        write(d/'attempts.json',[{'session_id':'case-probe','status':'invalid_request'}])
        result=audit_request(d,row,stage='probe',session_id='case-probe')
        self.assertTrue(result['submitted'])

    def test_budget_recomputes_native_ledger_summary(self):
        d,_,ledger,_,_,_=self.fixture()
        stored=json.loads((d/'ledger.json').read_text())
        expected=ledger.summary()
        self.assertEqual(audit_budget(stored,expected,stored['config']),expected)

    def test_budget_summary_counts_and_cost_tampering_reject(self):
        d,_,ledger,_,_,_=self.fixture();stored=json.loads((d/'ledger.json').read_text())
        for field in ('request_count','known_total_tokens','known_estimated_cost_cny',
                      'reserved_input_tokens','reserved_cost_cny','actual_estimated_cost_cny'):
            altered=copy.deepcopy(ledger.summary());altered[field]+=1
            with self.subTest(field=field),self.assertRaises(ValueError):
                audit_budget(stored,altered,stored['config'])

    def test_budget_false_integer_unknown_usage_recovery_and_duplicate_session_reject(self):
        d,_,ledger,_,_,_=self.fixture();stored=json.loads((d/'ledger.json').read_text())
        variants=[]
        bad=copy.deepcopy(stored);bad['requests'][0]['input_bytes']=True;variants.append(bad)
        bad=copy.deepcopy(stored);bad['requests'][0]['usage_state']='unknown';variants.append(bad)
        bad=copy.deepcopy(stored);bad['recovery']={'kind':'operator_transport_recovery'};variants.append(bad)
        bad=copy.deepcopy(stored);bad['requests'].append(copy.deepcopy(bad['requests'][0]));variants.append(bad)
        bad=copy.deepcopy(stored);bad['requests'][0]['actual_estimated_cost_cny']+=1;variants.append(bad)
        for bad in variants:
            with self.subTest(index=variants.index(bad)),self.assertRaises(ValueError):
                audit_budget(bad,ledger.summary(),stored['config'])


if __name__=='__main__':unittest.main()
