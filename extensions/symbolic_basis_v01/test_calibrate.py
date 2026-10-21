import unittest
from .calibrate import fixtures, assess
from .contract import compile_submission
from .executor import validate_transition


class FixtureTests(unittest.TestCase):
    def test_complete_fixed_set(self):
        cases=fixtures()
        self.assertEqual(len(cases),10)
        self.assertEqual(len({c['id'] for c in cases}),10)
        self.assertEqual({c['spec']['n_inputs'] for c in cases},{1,2,3,4})

    def test_all_structures_and_transitions_legal(self):
        for case in fixtures():
            compiled=compile_submission(case['payload'],case['spec'])
            self.assertEqual(compiled['n_params'],case['spec']['k'])
            validate_transition(case['payload'],case['spec'],case['parent_payload'],case['parent_spec'],case['mode'])

    def test_fixed_k_and_growth_share_identical_data(self):
        cases={c['id']:c for c in fixtures()}
        for label in ('swap-one','add-one'):
            self.assertEqual(cases[label]['request']['X'],cases['missing-square']['request']['X'])
            self.assertEqual(cases[label]['request']['y'],cases['missing-square']['request']['y'])
        self.assertEqual(cases['swap-one']['spec']['k'],3)
        self.assertEqual(cases['add-one']['spec']['k'],4)

    def test_known_gold_examples(self):
        cases={c['id']:c for c in fixtures()}
        for case in cases.values():
            self.assertEqual(len(case['request']['X']),len(case['request']['y']))
        case=cases['mixed-2d']
        i=case['request']['X'].index([2.,-1.])
        self.assertEqual(case['request']['y'][i],14.5)
        self.assertTrue(all(b==2*a for a,b in cases['collinear-inputs']['request']['X']))

    def test_failure_cannot_pass_exact(self):
        case=fixtures()[0]
        self.assertFalse(assess(case,{'status':'fit_failed'},[],{'exact_max_abs_error':1e-6,'exact_nmse':1e-12}))

    def test_constant_metric_must_remain_unavailable(self):
        case=next(c for c in fixtures() if c['id']=='constant-target')
        thresholds={'exact_max_abs_error':1e-6}
        result={'status':'metric_unavailable','score':{'error':'zero_target_variance'}}
        self.assertTrue(assess(case,result,[4.]*len(case['request']['y']),thresholds))
        result['status']='success'
        self.assertFalse(assess(case,result,[4.]*len(case['request']['y']),thresholds))


if __name__=='__main__': unittest.main()
