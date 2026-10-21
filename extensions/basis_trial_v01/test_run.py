"""Scheduling tests: catch leakage, repeated execution and partial-failure continuation."""
import copy
import tempfile
import unittest
from pathlib import Path
from . import run


class TrialTests(unittest.TestCase):
    def test_shared_context_changes_only_rendered_policy(self):
        design=run.design()
        common={'parent':design['parents']['A'],'feedback':{'nmse':0.3}}
        p0=run.actor_packet(common,run.S0)
        p1=run.actor_packet(common,{'version':run.S0['version'],'rule_ids':['R01','R02','R05','R08']})
        self.assertEqual(run.common_packet(p0),run.common_packet(p1))
        self.assertNotEqual(p0['repair_policy'],p1['repair_policy'])
        self.assertNotIn('arm',p0)
        p0['current_state']['feedback']['nmse']=99
        self.assertEqual(common['feedback']['nmse'],0.3)

    def test_balanced_once_only_slots(self):
        slots=run.design()['slots']
        self.assertEqual(len(slots),13)
        self.assertEqual(len({s['id'] for s in slots}),13)
        for parent in ['A','B']:
            for arm in ['S0','S1']:
                self.assertEqual([s['repeat'] for s in slots[1:] if s['parent']==parent and s['arm']==arm],[1,2,3])

    def exercise(self,fail=None,proposal=None):
        directory=Path(self.tmp.name)/('run'+str(len(list(Path(self.tmp.name).iterdir()))))
        calls=[]
        def session(slot,packet):
            calls.append(('request',slot['id']))
            if slot['id']==fail: raise RuntimeError('injected')
            if slot['stage']=='update':
                return {'status':'accepted','business':proposal or {'rule_ids':run.S0['rule_ids'],'explanation':'No change.'}}
            self.assertTrue((directory/'policy-freeze.json').exists())
            return {'status':'accepted','business':copy.deepcopy(packet['current_state']['parent']['payload'])}
        def measure(parent,child,out):
            self.assertTrue((directory/'policy-freeze.json').exists())
            calls.append(('measure',out.name))
            return {'status':'success','metrics':{'nmse':0.25},'feedback':{'nmse':0.25},'n_params':4,'sandbox_calls':2,'fit_attempts':1,'prediction_calls':1}
        result=run.orchestrate(directory,run.design(),{'old_history':True},session,measure)
        return directory,result,calls

    def setUp(self): self.tmp=tempfile.TemporaryDirectory()
    def tearDown(self): self.tmp.cleanup()

    def test_freeze_precedes_any_baseline_and_no_child_feedback_enters_actor(self):
        directory,result,calls=self.exercise()
        self.assertEqual(result['status'],'complete')
        self.assertTrue(result['policy_no_change'])
        self.assertEqual(len([x for x in calls if x[0]=='request']),13)
        self.assertEqual(len([x for x in calls if x[0]=='measure']),14)
        self.assertEqual(calls[0],('request','update'))
        with self.assertRaises(FileExistsError): run.orchestrate(directory,run.design(),{},None,None)

    def test_update_failure_prevents_all_data_access(self):
        _,result,calls=self.exercise(fail='update')
        self.assertEqual(result['status'],'stopped')
        self.assertEqual(calls,[('request','update')])

    def test_invalid_policy_stops_before_baselines(self):
        _,result,calls=self.exercise(proposal={'rule_ids':['R01']*4,'explanation':'bad'})
        self.assertEqual(result['status'],'stopped')
        self.assertEqual(len(calls),1)

    def test_actor_failure_stops_without_recovery(self):
        _,result,calls=self.exercise(fail='A-r1-S1')
        self.assertEqual(result['status'],'stopped')
        self.assertEqual(len([c for c in calls if c[0]=='request']),3)
        self.assertEqual(len([c for c in calls if c[0]=='measure']),3)

    def test_thresholds_and_no_best_sample_selection(self):
        self.assertEqual(run.change_label(0.2,0.1),'improved')
        self.assertEqual(run.change_label(0.2,0.3),'degraded')
        self.assertEqual(run.change_label(0.2,0.2000001),'unchanged')
        with self.assertRaises(ValueError): run.change_label(0.2,float('nan'))

    def test_context_tampering_stops_before_candidate_fit(self):
        directory=Path(self.tmp.name)/'tamper';measurements=[]
        def session(slot,packet):
            if slot['stage']=='update':return {'status':'accepted','business':{'rule_ids':run.S0['rule_ids'],'explanation':'same'}}
            (directory/'context-A.json').write_text('{}')
            return {'status':'accepted','business':packet['current_state']['parent']['payload']}
        def measure(parent,child,out):
            measurements.append(out.name)
            return {'status':'success','metrics':{'nmse':0.2},'feedback':{'nmse':0.2}}
        result=run.orchestrate(directory,run.design(),{},session,measure)
        self.assertEqual(result['status'],'stopped')
        self.assertEqual(measurements,['baseline-A','baseline-B'])

    def test_ledger_rejects_out_of_order_and_recovery(self):
        ledger=run.TrialLedger(Path(self.tmp.name)/'ledger.json')
        with self.assertRaises(run.BudgetExceeded):ledger.reserve('A-r1-S0',{},8192)
        request=ledger.reserve('update',{},8192)
        ledger.settle(request,None,error_type='Timeout')
        with self.assertRaises(run.BudgetExceeded):ledger.reserve('A-r1-S0',{},8192)
        with self.assertRaises(run.BudgetExceeded):ledger.resume_after_transport_failure()

if __name__=='__main__': unittest.main()
