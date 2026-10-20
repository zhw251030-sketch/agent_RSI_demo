import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rsi_eval import symbolic_probe as probe

ROOT = Path(__file__).resolve().parents[1]
PARENT = 'import numpy as np\n\ndef equation(x, v, params):\n    a = params[0]\n    b = params[1]\n    return a*x + b*v\n'
CHILD = 'import numpy as np\n\ndef equation(x, v, params):\n    a = params[0]\n    b = params[1]\n    c = params[2]\n    return a*x + b*v + c*x**3\n'


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def args(source=CHILD, parent=PARENT, n=3, index=2, parent_n=2):
    return dict(n_params=n, remove_param_index=index, source_sha256=digest(source),
                parent_source=parent, parent_n_params=parent_n, parent_sha256=digest(parent))


class TermRemovalTests(unittest.TestCase):
    def test_real_archived_additions_are_recognized_without_execution(self):
        base=ROOT/'artifacts/inference-policy/2026-10-20/v01'
        for session,n in [('p1-S-poly5-self',6),('p2-S-odd4-checked',5)]:
            parent=(base/session/'candidates/symbolic-000.py').read_text(encoding='utf-8')
            child=(base/session/'candidates/symbolic-001.py').read_text(encoding='utf-8')
            with patch('socket.socket',side_effect=AssertionError('No network')):
                result=probe.build_term_removal(child,**args(child,parent,n,n-1,n-1))
            self.assertEqual(result['status'],'ready')
            self.assertEqual(result['n_params_after'],n-1)
            self.assertEqual(result['mapping'][str(n-1)],None)
            self.assertNotEqual(result['canonical_sha256'],result['removed_sha256'])

    def test_middle_parameter_removal_reindexes_the_remaining_dimension(self):
        child='def equation(x,v,params):\n    return params[0]*x + params[1]*x**3 + params[2]*v\n'
        result=probe.build_term_removal(child,**args(child,index=1))
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['mapping'],{'0':0,'1':None,'2':1})
        self.assertIn('params[1] * v',result['removed_source'])
        self.assertNotIn('params[2]',result['removed_source'])

    def test_aliases_direct_parameters_and_signs_share_structural_signature(self):
        parent='def equation(x,v,params):\n    return -params[0]*x - params[1]*v\n'
        child='def equation(x,v,params):\n    a=params[0]\n    b=params[1]\n    c=params[2]\n    return -a*x - b*v - c*x**3\n'
        self.assertEqual(probe.build_term_removal(child,**args(child,parent))['status'],'ready')

    def test_changed_retained_term_is_not_an_addition(self):
        child=CHILD.replace('b*v +','b*v**2 +')
        result=probe.build_term_removal(child,**args(child))
        self.assertEqual(result['status'],'unknown')
        self.assertEqual(result['reason'],'retained_terms_differ_from_parent')

    def test_non_linear_coupled_or_duplicate_coefficients_are_ineligible(self):
        expressions=['params[0]*params[1]*x + params[2]*v',
                     'params[0]*x + params[1]*v + params[2]*x + params[2]*v',
                     'params[0]*x + params[1]*v + x**params[2]',
                     'params[0]*x + params[1]*v + np.exp(params[2]*x)']
        for expr in expressions:
            child='import numpy as np\ndef equation(x,v,params):\n    return '+expr+'\n'
            with self.subTest(expr=expr):
                self.assertEqual(probe.build_term_removal(child,**args(child))['status'],'unknown')

    def test_arbitrary_code_and_dynamic_indices_are_not_executed(self):
        for source in ['raise RuntimeError("must not execute")\n'+CHILD,
                       CHILD.replace('params[2]','params[int(x[0])]'),
                       CHILD.replace('c*x**3','__import__("os").system("bad")'),
                       CHILD.replace('c*x**3','np.abs.__call__(x)'),
                       CHILD.replace('a = params[0]','a = params[0]\n    a = params[1]')]:
            with self.subTest(source=source):
                self.assertEqual(probe.build_term_removal(source,**args(source))['status'],'unknown')

    def test_wrong_hash_parameter_bounds_and_oversize_fail_closed(self):
        for overrides in [dict(source_sha256='0'*64),dict(parent_sha256='0'*64),
                          dict(n_params=True),dict(remove_param_index=3),dict(parent_n_params=3)]:
            data=args();data.update(overrides)
            self.assertEqual(probe.build_term_removal(CHILD,**data)['status'],'unknown')
        source='#'+'x'*17000+'\n'+CHILD
        self.assertEqual(probe.build_term_removal(source,**args(source))['status'],'unknown')


class MatchedProbeTests(unittest.TestCase):
    def run_probe(self,scores=(.1,.1,.11),statuses=None,mutate=None):
        calls=[]
        def evaluate(family,task,source,**kwargs):
            index=len(calls);calls.append((family,task,source,kwargs))
            result=dict(schema_version='0.1',run_id=f'run{index}',family=family,task_id=task,
                candidate_id=kwargs['candidate_id'],candidate_hash=digest(source),
                parent_id=kwargs['parent_id'],strategy_version=kwargs['strategy_version'],
                status='success' if statuses is None else statuses[index],
                limits=copy.deepcopy(probe.LIMITS),model_calls=0,sealed_tasks_executed=0,
                executions=[{'phase':'fit','status':'completed'},{'phase':'predict','status':'completed'}],
                fitting={'params':[1.0]*kwargs['n_params'],'n_params':kwargs['n_params'],
                         'converged':True,'nfev':3,'candidate_calls':9,'split':'train','max_nfev':100},
                diagnostics={'version':'diagnostics-v0.1','task_id':task,'scope':'train',
                             'candidate_sha256':digest(source),'residuals':{}},
                metric_split='train',metrics={'mse':scores[index]*2,'nmse':scores[index]})
            if mutate:mutate(index,result)
            return result
        with tempfile.TemporaryDirectory() as directory,patch.object(probe,'_dataset_identity',return_value={'task':'oscillator1','split':'train','data_sha256':'a'*64,'manifest_sha256':'b'*64}),patch.object(probe,'evaluate_candidate',side_effect=evaluate):
            result=probe.probe_symbolic(CHILD,root=Path(directory),case_id='probe',**args())
        return result,calls

    def test_larger_removal_loss_supports_the_frozen_harm_claim(self):
        result,calls=self.run_probe()
        self.assertEqual(result['verdict'],'supported')
        self.assertEqual([v['name'] for v in result['variants']],['original','canonical_full','removed'])
        self.assertEqual([c[3]['n_params'] for c in calls],[3,3,2])
        self.assertEqual(result['candidate_evaluations'],3)
        self.assertEqual(result['sandbox_executions'],6)
        self.assertEqual(result['model_calls'],0)
        self.assertEqual(result['status'],'completed')
        self.assertIs(result['execution_accounting_complete'],True)
        self.assertEqual(result['executions'],{'sandbox_calls':6,'new_candidate_executions':3,
                                              'fit_calls':3,'predict_calls':3})
        self.assertTrue(all(call[3]['diagnostics'] is True for call in calls))

    def test_loss_smaller_than_epsilon_contradicts_only_operational_claim(self):
        result,_=self.run_probe(scores=(.1,.1,.100001))
        self.assertEqual(result['verdict'],'contradicted')

    def test_boundary_and_unexpected_negative_loss_remain_unknown(self):
        for values in [(.1,.1,.10001),(.1,.1,.099)]:
            result,_=self.run_probe(scores=values)
            self.assertEqual(result['verdict'],'unknown')

    def test_sham_drift_is_unknown(self):
        result,calls=self.run_probe(scores=(.1,.100001,.11))
        self.assertEqual(result['verdict'],'unknown')
        self.assertEqual(result['reason'],'canonical_sham_drift')
        self.assertEqual(len(calls),2)

    def test_ineligible_transformation_does_not_even_read_data(self):
        child=CHILD.replace('c*x**3','c*a*x')
        with patch.object(probe,'_dataset_identity',side_effect=AssertionError('No data needed')),patch.object(probe,'evaluate_candidate') as run:
            result=probe.probe_symbolic(child,root=ROOT,case_id='invalid',**args(child))
        self.assertEqual(result['verdict'],'unknown');self.assertEqual(result['candidate_evaluations'],0)
        run.assert_not_called()

    def test_infrastructure_failure_stops_case(self):
        result,calls=self.run_probe(statuses=['success','infrastructure_error','success'])
        self.assertTrue(result['infrastructure_stopped']);self.assertEqual(len(calls),2)
        self.assertEqual(result['verdict'],'unknown')

    def test_foreign_hash_split_or_fit_settings_are_rejected(self):
        mutations=[lambda r:r.update(candidate_hash='0'*64),lambda r:r.update(metric_split='test'),
                   lambda r:r['fitting'].update(converged=False),lambda r:r['fitting'].update(max_nfev=999),
                   lambda r:r['limits'].update(cpu_seconds=999)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                result,calls=self.run_probe(mutate=lambda i,r:mutate(r) if i==0 else None)
                self.assertEqual(result['verdict'],'unknown');self.assertEqual(len(calls),1)

    def test_diagnostics_must_belong_to_this_source_and_training_task(self):
        for changes in [{'candidate_sha256':'0'*64},{'scope':'test'},{'task_id':'oscillator2'}]:
            with self.subTest(changes=changes):
                result,calls=self.run_probe(mutate=lambda i,r:r['diagnostics'].update(changes) if i==0 else None)
                self.assertEqual(result['status'],'infrastructure_error')
                self.assertEqual(len(calls),1)

    def test_foreign_parent_or_strategy_record_cannot_support_the_probe(self):
        for changes in [{'parent_id':'0'*64},{'strategy_version':'foreign-protocol'}]:
            with self.subTest(changes=changes):
                result,calls=self.run_probe(mutate=lambda i,r:r.update(changes) if i==0 else None)
                self.assertEqual(result['status'],'infrastructure_error')
                self.assertEqual(result['reason'],'executor_record_contract_mismatch')
                self.assertEqual(len(calls),1)

    def test_invalid_numeric_metadata_cannot_pass_by_boolean_equality(self):
        for changes in [{'n_params':True},{'max_nfev':100.0}]:
            with self.subTest(changes=changes):
                result,calls=self.run_probe(mutate=lambda i,r:r['fitting'].update(changes) if i==0 else None)
                self.assertEqual(result['status'],'infrastructure_error')
                self.assertEqual(len(calls),1)

    def test_inconsistent_nmse_normalization_is_not_a_matched_comparison(self):
        result,calls=self.run_probe(mutate=lambda i,r:r['metrics'].update(mse=.3) if i==1 else None)
        self.assertEqual(result['reason'],'metric_normalization_mismatch')
        self.assertEqual(len(calls),2)

    def test_parameter_dimension_changes_reach_executor_and_bad_fit_is_stopped(self):
        result,calls=self.run_probe(mutate=lambda i,r:r['fitting'].update(params=[1.0]*3) if i==2 else None)
        self.assertEqual(result['verdict'],'unknown')
        self.assertEqual(calls[2][3]['n_params'],2)
        self.assertEqual(result['reason'],'executor_record_contract_mismatch')

    def test_evaluation_exception_is_recorded_without_exposing_exception_text(self):
        with patch.object(probe,'_dataset_identity',return_value={'data':'same'}),patch.object(probe,'evaluate_candidate',side_effect=OSError('private-path')):
            result=probe.probe_symbolic(CHILD,root=ROOT,case_id='exception',**args())
        self.assertEqual(result['status'],'infrastructure_error')
        self.assertEqual(result['candidate_evaluations'],1)
        self.assertIs(result['execution_accounting_complete'],False)
        self.assertEqual(result['variants'][0]['controller_error_type'],'OSError')
        self.assertNotIn('private-path',json.dumps(result))

    def test_dataset_changes_stop_before_another_evaluation(self):
        identities=[{'data':'a'},{'data':'a'},{'data':'b'}]
        with patch.object(probe,'_dataset_identity',side_effect=identities),patch.object(probe,'evaluate_candidate',return_value={'status':'candidate_error','executions':[],'model_calls':0}) as run:
            result=probe.probe_symbolic(CHILD,root=ROOT,case_id='changed',**args())
        self.assertEqual(result['verdict'],'unknown');self.assertTrue(result['infrastructure_stopped'])
        self.assertEqual(run.call_count,1)


class DatasetIdentityTests(unittest.TestCase):
    def test_only_training_file_is_loaded_and_hash_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            data=root/'data/symbolic/llm-sr/oscillator1/train.csv'
            manifest=root/'configs/tasks/downloads-v0.1.json'
            data.parent.mkdir(parents=True);manifest.parent.mkdir(parents=True)
            raw=b'x,v,a\n1,2,3\n4,5,6\n'
            data.write_bytes(raw)
            manifest.write_text(json.dumps({'symbolic':{'source_name':'LLM-SR',
                'data_dir':'data/symbolic/llm-sr','files':[{'relative_path':'oscillator1/train.csv',
                'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw),'rows':2,
                'columns':['x','v','a']}]}}),encoding='utf-8')
            identity=probe._dataset_identity(root)
            self.assertEqual(identity['rows'],2)
            self.assertEqual(identity['split'],'train')
            self.assertEqual(identity['data_sha256'],hashlib.sha256(raw).hexdigest())
            self.assertNotIn('X',identity);self.assertNotIn('y',identity)
            data.write_bytes(raw.replace(b'1,2,3',b'1,2,9'))
            with self.assertRaisesRegex(ValueError,'training_hash_mismatch'):
                probe._dataset_identity(root)


if __name__=='__main__':unittest.main()
