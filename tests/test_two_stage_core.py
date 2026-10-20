"""No model, candidate, dataset or subprocess is used by these core tests."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from rsi_eval import two_stage_core as core


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def case(family='planning'):
    source = 'def get_plan(objects, init, goal):\n    return []\n' if family == 'planning' else 'def equation(x,v,params):\n    return params[0]*x + params[1]*v + params[2]*x**3\n'
    tasks = [f'spannerlearning/seed0/problem{i}' for i in range(10)] if family == 'planning' else ['oscillator1']
    c = dict(case_id='P-prefix' if family == 'planning' else 'S-cubic', family=family,
        source=source, source_sha256=sha(source), n_params=0 if family == 'planning' else 3,
        task_ids=tasks, prompt_task_ids=tasks[:2] if family == 'planning' else [],
        development_task_ids=tasks[2:] if family == 'planning' else tasks,
        probe_id='planning_whitespace' if family == 'planning' else 'symbolic_term_removal',
        target_id='public_pair' if family == 'planning' else 'param2',
        baseline_results=[dict(task_id=t,status='task_failure') for t in tasks] if family == 'planning' else [dict(task_id='oscillator1',status='success',metrics={'nmse':.1})],
        parent_source='def equation(x,v,params):\n    return params[0]*x + params[1]*v\n',
        parent_n_params=2, remove_param_index=2)
    c['parent_sha256'] = sha(c['parent_source'])
    c['public_packet'] = {k:copy.deepcopy(c[k]) for k in ('case_id','family','source','source_sha256','n_params')}
    return c


def registration(c):
    return dict(status='accepted',case_id=c['case_id'],source_sha256=c['source_sha256'],
                family=c['family'],probe_id=c['probe_id'],target_id=c['target_id'],auxiliary={})


def plan_probe(c):
    return {'results':[dict(version='planning-format-probe-v0.1',status='completed',
        source_sha256=c['source_sha256'],task_id=t,verdict='contradicted',
        reason='edge_normalization_insufficient_on_this_plan',task_binding={'pilot_role':'prompt'},
        raw={'validation':{'status':'task_failure','plan_length':0}},
        normalized={'validation':{'status':'task_failure','plan_length':0}},
        normalization={'original':[], 'normalized':[]},next_edit_scope={'source':'SECRET'})
        for t in c['prompt_task_ids']]}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)

    def test_probe_bad_aux_keeps_registration_and_copies_it(self):
        c=case(); p=core.ProbeController(c,self.path)
        aux={'pre_verdict':{'bad':'semantic'},'reason':[1,2]}
        result=p.submit_probe('s',c['probe_id'],c['target_id'],aux)
        self.assertEqual(result['status'],'accepted')
        aux['reason'].append(3)
        self.assertEqual(p.registration['auxiliary']['reason'],[1,2])
        self.assertEqual(json.loads((self.path/'registration.json').read_text()),p.registration)

    def test_probe_bad_binding_consumes_attempt(self):
        c=case(); p=core.ProbeController(c,self.path)
        self.assertEqual(p.submit_probe('s','symbolic_term_removal','param2',{})['status'],'invalid_request')
        self.assertEqual(p.submit_probe('s',c['probe_id'],c['target_id'],{})['status'],'budget_exhausted')
        self.assertIsNone(p.registration)

    def test_probe_cannot_reopen_or_accept_nonfinite_aux(self):
        p=core.ProbeController(case(),self.path)
        self.assertEqual(p.submit_probe('s','planning_whitespace','public_pair',{'x':float('nan')})['status'],'invalid_request')
        with self.assertRaises(FileExistsError): core.ProbeController(case(),self.path)

    def test_invalid_case_hash_and_scope_rejected(self):
        c=case();c['source_sha256']='0'*64
        with self.assertRaises(ValueError): core.ProbeController(c,self.path/'a')
        c=case();c['task_ids'][-1]='spannerlearning/seed0/problem10'
        with self.assertRaises(ValueError): core.ProbeController(c,self.path/'b')

    def test_projection_hides_artifacts_and_rejects_scope(self):
        c=case(); full=plan_probe(c)
        projected=core.feedback_projection(c,full)
        self.assertNotIn('SECRET',json.dumps(projected))
        self.assertNotIn('"normalization":',json.dumps(projected))
        self.assertEqual(len(projected['observations']),2)
        full['results'][0]['task_id']='spannerlearning/seed0/problem8'
        with self.assertRaises(ValueError):core.feedback_projection(c,full)

    def test_projection_preserves_unknown_not_failure(self):
        c=case();full=plan_probe(c)
        full['results'][0].update(verdict='unknown',reason='original_already_valid_not_applicable')
        self.assertEqual(core.feedback_projection(c,full)['observations'][0]['verdict'],'unknown')

    def test_symbolic_projection_drops_sources_parameters_and_next_action(self):
        c=case('symbolic')
        full=dict(case_id=c['case_id'],status='completed',verdict='contradicted',reason='removal_loss_below_threshold',
            epsilon=1e-5,tolerance=1e-10,delta_nmse=1e-7,sham_delta_nmse=0,
            transformation={'source_sha256':c['source_sha256'],'parent_sha256':c['parent_sha256'],
                'canonical_source':'SECRET','removed_source':'SECRET'},dataset_identity={'task':'oscillator1','split':'train'},
            variants=[{'name':name,'source':'SECRET','n_params':n,'result':{'status':'success',
                'metrics':{'nmse':score},'fitting':{'params':['SECRET']}}} for name,n,score in
                [('original',3,.1),('canonical_full',3,.1),('removed',2,.1000001)]], next_edit_scope='SECRET')
        p=core.feedback_projection(c,full)
        self.assertNotIn('SECRET',json.dumps(p));self.assertEqual(p['delta_nmse'],1e-7)
        full['dataset_identity']['split']='test_id'
        with self.assertRaises(ValueError):core.feedback_projection(c,full)

    def test_common_request_removes_only_feedback(self):
        packet={'case_id':'P-prefix','probe_feedback':None,'source':'ORIGINAL'}
        request={'model':'same','tools':[{'type':'function'}],'messages':[{'role':'system','content':'same'},
                  {'role':'user','content':json.dumps(packet)}]}
        changed=copy.deepcopy(request);p=copy.deepcopy(packet);p['probe_feedback']={'status':'unknown'}
        changed['messages'][1]['content']=json.dumps(p)
        self.assertEqual(core.common_request(request),core.common_request(changed))
        changed['tools']=[]
        self.assertNotEqual(core.common_request(request),core.common_request(changed))
        request['messages'].append({'role':'user','content':json.dumps(packet)})
        with self.assertRaises(ValueError):core.common_request(request)

    def test_revision_evaluates_one_candidate_and_all_tasks(self):
        c=case();calls=[]
        def evaluator(family,task_id,source,**kw):
            calls.append((family,task_id,source,kw))
            return dict(status='success',task_id=task_id,candidate_hash=sha(source),executions=[{'phase':'planning'}])
        r=core.RevisionController(c,registration(c),None,self.path,self.path/'run',evaluator=evaluator)
        result=r.submit('s',c['source'],0,'why',{'forecast':{'bad':True}})
        self.assertEqual(result['status'],'evaluated');self.assertEqual(len(calls),10)
        self.assertEqual(r.summary()['candidate']['score']['development_successes'],8)
        self.assertEqual(len(list((self.path/'run/evaluations').glob('*.json'))),10)
        self.assertEqual(r.submit('s',c['source'],0,'',{})['status'],'budget_exhausted')

    def test_revision_missing_registration_never_executes(self):
        c=case()
        with self.assertRaises(ValueError):core.RevisionController(c,None,None,self.path,self.path/'run')

    def test_revision_invalid_source_consumes_slot_but_aux_wrong_does_not(self):
        c=case();r=core.RevisionController(c,registration(c),None,self.path,self.path/'run',evaluator=lambda *a,**k:None)
        self.assertEqual(r.submit('s','',0,'',{})['status'],'invalid_request')
        self.assertEqual(r.submit('s',c['source'],0,'',{})['status'],'budget_exhausted')
        self.assertIsNone(r.summary()['candidate'])

    def test_infrastructure_error_halts_and_score_remains_missing(self):
        c=case();calls=[]
        def evaluator(*args,**kwargs):
            calls.append(args);raise OSError('DO NOT LOG SECRET')
        r=core.RevisionController(c,registration(c),None,self.path,self.path/'run',evaluator=evaluator)
        self.assertEqual(r.submit('s',c['source'],0,'',{})['status'],'infrastructure_error')
        self.assertTrue(r.halted);self.assertEqual(len(calls),1)
        self.assertFalse(r.summary()['candidate']['score']['complete'])
        self.assertNotIn('SECRET',json.dumps(r.summary()))

    def test_symbolic_scores_allow_small_loss_simplification(self):
        c=case('symbolic')
        score=core.summarize_scores(c,[dict(task_id='oscillator1',status='success',metrics={'nmse':.1000001})],2)
        self.assertTrue(score['acceptable_simplification']);self.assertFalse(score['strict_improvement'])
        self.assertAlmostEqual(score['delta_nmse'],1e-7)
        score=core.summarize_scores(c,[dict(task_id='oscillator1',status='success',metrics={'nmse':.1+1e-5})],2)
        self.assertIsNone(score['acceptable_simplification'])

    def test_missing_score_and_boolean_metric_never_count(self):
        self.assertFalse(core.summarize_scores(case(),[],0)['complete'])
        c=case('symbolic')
        score=core.summarize_scores(c,[dict(task_id='oscillator1',status='success',metrics={'nmse':True})],2)
        self.assertFalse(score['complete'])

    def test_edit_classification_does_not_execute_source(self):
        c=case('symbolic')
        self.assertEqual(core.classify_edit(c,c['source'],3)['kind'],'unchanged')
        self.assertEqual(core.classify_edit(c,c['parent_source'],2)['kind'],'exact_term_removal')
        self.assertEqual(core.classify_edit(c,'raise RuntimeError("bad")',3)['kind'],'other_change')

    def test_forecast_records_bad_values_as_schema_invalid(self):
        c=case();self.assertEqual(core.check_forecast(c,{'development_successes':'eight'},
             {'complete':True,'development_successes':8})['status'],'schema_invalid')
        self.assertEqual(core.check_forecast(c,{'development_successes':8},
             {'complete':True,'development_successes':8})['absolute_error'],0)

    def test_task_packets_only_feedback_diff(self):
        c=case(); reg=registration(c); fb=core.feedback_projection(c,plan_probe(c))
        a=core.RevisionController(c,reg,None,self.path,self.path/'a').task_packet()
        b=core.RevisionController(c,reg,fb,self.path,self.path/'b').task_packet()
        a.pop('probe_feedback');b.pop('probe_feedback');self.assertEqual(a,b)

    def test_revision_rejects_extra_feedback_solution_or_wrong_scope(self):
        c=case(); fb=core.feedback_projection(c,plan_probe(c))
        fb['source']='SECRET'
        with self.assertRaises(ValueError):core.RevisionController(c,registration(c),fb,self.path,self.path/'a')
        del fb['source'];fb['scope']='sealed'
        with self.assertRaises(ValueError):core.RevisionController(c,registration(c),fb,self.path,self.path/'b')

    def test_real_cases_load_without_candidate_execution(self):
        from rsi_eval.two_stage_cases import load_cases
        root=Path(__file__).resolve().parents[1]
        for index,c in enumerate(load_cases(root)):
            p=core.ProbeController(c,self.path/str(index))
            packet=p.task_packet()
            self.assertEqual(packet['source_sha256'],c['source_sha256'])
            self.assertLess(len(core.canonical(packet)),65536)

    def test_probe_contract_is_identical_in_both_stages(self):
        for family in ('planning','symbolic'):
            c=case(family)
            p=core.ProbeController(c,self.path/(family+'-probe'))
            r=core.RevisionController(c,registration(c),None,self.path,self.path/(family+'-revision'))
            contract=p.task_packet()['probe_contract']
            self.assertEqual(contract,r.task_packet()['probe_contract'])
            self.assertIn('claim',contract)
            self.assertIn('unknown',contract['verdicts'])

    def test_probe_forecast_unknown_is_checked_as_its_own_label(self):
        c=case(); feedback=core.feedback_projection(c,plan_probe(c))
        feedback['observations'][0]['verdict']='unknown'
        result=core.check_probe_forecast(c,{'pre_verdict':{'problem0':'unknown','problem1':'contradicted'}},feedback)
        self.assertTrue(all(row['correct'] for row in result['verdicts']))
        result=core.check_probe_forecast(c,{'pre_verdict':{'problem0':False}},feedback)
        self.assertEqual(result['verdicts'][0]['status'],'schema_invalid')


if __name__=='__main__':unittest.main()
