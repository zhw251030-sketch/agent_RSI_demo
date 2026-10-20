import copy
import json
from pathlib import Path
import tempfile
import unittest
from scripts.run_inference_policy import (classify_update,dependency_missing,update_order,
    evaluation_order,verify_pairs,validate_config,execute_updates,load_phase)

ROOT=Path(__file__).resolve().parents[1]


class FakeLedger:
    def __init__(self,path): self.path=path; self.rows=[];self.halted=False; self.save()
    def save(self): self.path.write_text(json.dumps({'requests':self.rows,'halted':self.halted}))
    def add(self,session,unknown=False):
        self.rows.append({'session_id':session,'request_id':f'request-{len(self.rows)+1:04d}',
            'status':'settled','usage_state':'unknown' if unknown else 'known','usage':{} })
        self.halted=unknown;self.save()
    def summary(self): return {'halted':self.halted,'usage_unknown_count':int(self.halted),'reserved_count':0}


class InferenceRunnerTests(unittest.TestCase):
    def test_schedule_has_no_information_descendant_state(self):
        self.assertEqual(len(update_order()+evaluation_order()),14)
        self.assertNotIn('P-B002',{r['state_id'] for r in evaluation_order()})
        self.assertIn('P-H002',{r['state_id'] for r in evaluation_order()})

    def test_missing_review_does_not_block_other_review(self):
        rows={'p1-proposal':{'disposition':'available'},'p1-self':{'disposition':'missing'}}
        self.assertFalse(dependency_missing({'pair_id':'p1','condition':'checked'},rows))
        rows['p1-proposal']['disposition']='missing'
        self.assertTrue(dependency_missing({'pair_id':'p1','condition':'checked'},rows))

    def test_missing_policy_distinct_from_fatal_failure(self):
        class C: halted=False;policy=None
        c=C();budget={'halted':False,'usage_unknown_count':0,'reserved_count':0}
        self.assertEqual(classify_update({'status':'stopped'},c,budget),'missing')
        self.assertEqual(classify_update({'status':'error','cause_type':'PilotResponseContractError'},c,budget),'missing')
        c.halted=True
        self.assertEqual(classify_update({'status':'stopped'},c,budget),'blocked')
        c.halted=False;c.policy={'anything':'available'}
        self.assertEqual(classify_update({'status':'stopped'},c,dict(budget,usage_unknown_count=1)),'blocked')

    def test_partial_actor_pair_is_explicit_and_memory_still_checked(self):
        class C:
            records=[{'source_sha256':'x','n_params':3}]
            def __init__(self,memory=None):self.memory=memory or []
            def state_packet(self): return {'repair_policy':{},'experience_memory':self.memory,'input':1}
        prepared=[(C(),None,{'pair_id':'x','condition':'self'})]
        self.assertFalse(verify_pairs(prepared)['x']['both_available'])
        prepared.append((C(['leak']),None,{'pair_id':'x','condition':'checked'}))
        with self.assertRaises(ValueError):verify_pairs(prepared)

    def _run(self,missing=(),unknown=None,duplicate=None):
        from rsi_eval.inference_cases import load_inference_bundle
        from rsi_eval.inference_policy import fixture_submission
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);out=Path(tmp.name)
        bundle=load_inference_bundle(ROOT);ledger=FakeLedger(out/'budget-ledger.json')
        report={'run_id':'mock','updates':[dict(r,status='not_started') for r in update_order()]}
        called=[]
        def run(c,row,directory):
            name=row['session_id'];called.append(name);ledger.add(name,unknown==name)
            if name not in missing and unknown!=name:
                submission=fixture_submission(bundle)
                if name==duplicate:submission['rule_2']=submission['rule_1']
                c.submit_policy(**submission)
            return {'status':'stopped','model_error_type':None}
        execute_updates(out,report,bundle,ledger,run)
        return out,report,bundle,called

    def test_one_review_missing_still_freezes_other_five(self):
        out,report,bundle,called=self._run(missing={'p1-self'})
        self.assertEqual(len(called),6);self.assertEqual(report['status'],'updates_frozen')
        policies=load_phase(out,bundle,report)
        self.assertNotIn('p1-self',policies);self.assertEqual(len(policies),3)
        (out/'p1-self/injected.json').write_text('{}')
        with self.assertRaises(ValueError):load_phase(out,bundle,report)

    def test_missing_proposal_skips_only_its_reviews(self):
        out,report,bundle,called=self._run(missing={'p1-proposal'})
        self.assertEqual(called,['p1-proposal','p2-proposal','p2-checked','p2-self'])
        self.assertEqual(set(load_phase(out,bundle,report)),{'p2-self','p2-checked'})

    def test_real_duplicate_rule_rejection_preserves_independent_calls(self):
        out,report,bundle,called=self._run(duplicate='p1-self')
        self.assertEqual(len(called),6)
        self.assertEqual(report['status'],'updates_frozen')
        self.assertEqual(report['updates'][1]['disposition'],'missing')
        self.assertTrue((out/'p1-self/rejection.json').exists())
        self.assertEqual(set(load_phase(out,bundle,report)),{'p1-checked','p2-self','p2-checked'})

    def test_unknown_usage_stops_without_phase_freeze(self):
        out,report,bundle,called=self._run(unknown='p1-proposal')
        self.assertEqual(called,['p1-proposal']);self.assertEqual(report['status'],'stopped')
        self.assertFalse((out/'update-phase-freeze.json').exists())

    def test_budget_and_missing_rules_are_frozen(self):
        config=json.loads((ROOT/'configs/pilots/inference-policy-v0.1.json').read_text())
        validate_config(config)
        for key,value in [('max_requests',15),('max_requests_per_session',2),('max_cost_cny',6)]:
            changed=copy.deepcopy(config);changed['budgets'][key]=value
            with self.assertRaises(ValueError):validate_config(changed)


if __name__=='__main__':unittest.main()
