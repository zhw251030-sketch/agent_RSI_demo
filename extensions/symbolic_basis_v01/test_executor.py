import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from extensions.symbolic_basis_v01.contract import make_spec
from extensions.symbolic_basis_v01.executor import evaluate_submission, validate_transition, evaluate_role


def payload(features): return {'feature_ids':features,'explanation':'synthetic fixture'}


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.spec=make_spec(1,2)
        self.payload=payload(['m_0','m_1'])
        self.request={'family':'symbolic','X':[[0.0],[1.0]],'y':[1.0,3.0],'task_id':'synthetic','input_names':['x']}

    def test_invalid_submission_before_sandbox_or_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary)/'run'
            with self.assertRaises(ValueError): evaluate_submission(payload(['m_0','bad']),self.spec,request=self.request,provenance={'kind':'synthetic'},output=out,runner=lambda *a: self.fail('sandbox called'))
            self.assertFalse(out.exists())

    def test_fit_then_target_free_prediction_and_host_score(self):
        calls=[]
        def runner(source,request):
            calls.append(copy.deepcopy(request))
            if request['phase']=='fit': return {'status':'completed','result':{'status':'success','params':[1.,2.],'converged':True,'nfev':1,'candidate_calls':2,'diagnostics':{'optimizer_invocations':1}}}
            self.assertNotIn('y',request)
            return {'status':'completed','result':{'status':'success','predictions':[1.,3.]}}
        with tempfile.TemporaryDirectory() as temporary:
            result=evaluate_submission(self.payload,self.spec,request=self.request,provenance={'kind':'synthetic'},output=Path(temporary)/'run',runner=runner)
        self.assertEqual([r['phase'] for r in calls],['fit','predict'])
        self.assertEqual(result['metrics']['nmse'],0.)

    def test_fit_failure_does_not_predict(self):
        calls=[]
        def runner(source,request):
            calls.append(request)
            return {'status':'completed','result':{'status':'candidate_error','error':'optimization_failed'}}
        with tempfile.TemporaryDirectory() as temporary:
            result=evaluate_submission(self.payload,self.spec,request=self.request,provenance={'kind':'synthetic'},output=Path(temporary)/'run',runner=runner)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['status'],'fit_failed')
        self.assertIsNone(result['metrics'])

    def test_existing_run_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(FileExistsError): evaluate_submission(self.payload,self.spec,request=self.request,provenance={'kind':'synthetic'},output=Path(temporary),runner=lambda *a:self.fail('sandbox'))

    def test_swap_cannot_change_k(self):
        with self.assertRaises(ValueError): validate_transition(payload(['m_0','m_1','m_2']),make_spec(1,3),self.payload,self.spec,'swap_one')

    def test_swap_replaces_at_most_one(self):
        parent=payload(['m_0_0','m_1_0','m_0_1'])
        child=payload(['m_0_0','m_2_0','m_0_2'])
        with self.assertRaises(ValueError): validate_transition(child,make_spec(2,3),parent,make_spec(2,3),'swap_one')

    def test_add_preserves_all_parent_features(self):
        with self.assertRaises(ValueError): validate_transition(payload(['m_0','m_2','m_3']),make_spec(1,3),self.payload,self.spec,'add_one')

    def test_retention_and_growth_labeled(self):
        self.assertEqual(validate_transition(self.payload,self.spec,self.payload,self.spec,'swap_one')['observed_change'],'keep')
        self.assertEqual(validate_transition(payload(['m_0','m_1','m_2']),make_spec(1,3),self.payload,self.spec,'add_one')['observed_change'],'add_one')

    def test_wrong_dimensions_rejected_before_call(self):
        request=dict(self.request,X=[[0.,1.],[2.,3.]])
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError): evaluate_submission(self.payload,self.spec,request=request,provenance={},output=Path(temporary)/'run',runner=lambda *a:self.fail('sandbox'))

    def test_illegal_submission_before_role_data_access(self):
        with patch('extensions.symbolic_basis_v01.executor.RoleExecutor') as factory:
            with self.assertRaises(ValueError): evaluate_role(payload(['m_0','bad']),self.spec,task_id='oscillator1',role='learning',output=Path('unused'))
            factory.assert_not_called()

    def test_nested_metadata_rejected(self):
        for key,value in [('input_names',[{'y':[1.,3.]}]),('task_id',{'y':[1.,3.]})]:
            request=dict(self.request,**{key:value})
            with tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(ValueError): evaluate_submission(self.payload,self.spec,request=request,provenance={},output=Path(temporary)/'run',runner=lambda *a:self.fail('sandbox'))


if __name__=='__main__': unittest.main()
