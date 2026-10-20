"""Read-only audit rejects coherent-looking changes to recorded probe labels."""
import copy
import hashlib
import importlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class InterventionAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.m=importlib.import_module('scripts.analyze_intervention_probes')

    def test_scope_follows_verdict_without_claiming_generalization(self):
        for family,verdict,action in (
            ('planning','supported','consider_format_patch_under_AST_contract'),
            ('planning','contradicted','formatting_not_sufficient_check_semantics'),
            ('symbolic','supported','retain_selected_term_under_fixed_train_protocol'),
            ('symbolic','contradicted','consider_evaluated_term_removal'),
            ('symbolic','unknown','no_term_value_decision')):
            with self.subTest(family=family,verdict=verdict):
                result=self.m.expected_scope(family,{'verdict':verdict,'task_id':'p0'})
                self.assertEqual(result['action'],action)
                self.assertIn('held_out_generalization',result['excludes'])

    def test_planning_verdict_is_derived_from_both_recorded_checks(self):
        raw={'validation':{'status':'invalid_output'},'replay':{'status':'invalid_output'}}
        normalized={'validation':{'status':'success'},'replay':{'status':'valid'}}
        self.assertEqual(self.m.planning_verdict(raw,normalized,True),
                         ('supported','edge_normalization_sufficient_on_this_plan'))
        normalized['validation']['status']='task_failure';normalized['replay']['status']='goal_unsatisfied'
        self.assertEqual(self.m.planning_verdict(raw,normalized,True)[0],'contradicted')
        raw['validation']['status']='success';raw['replay']['status']='valid'
        self.assertEqual(self.m.planning_verdict(raw,normalized,True)[0],'unknown')

    def test_symbolic_threshold_negative_delta_and_boundary_are_distinct(self):
        self.assertEqual(self.m.symbolic_verdict(2e-5,1e-5,1e-10)[0],'supported')
        self.assertEqual(self.m.symbolic_verdict(1e-7,1e-5,1e-10)[0],'contradicted')
        self.assertEqual(self.m.symbolic_verdict(1e-5,1e-5,1e-10)[1],'threshold_boundary')
        self.assertEqual(self.m.symbolic_verdict(-1e-4,1e-5,1e-10)[1],'nested_fit_inconsistent')

    def test_validator_replay_disagreement_and_fake_validator_are_rejected(self):
        good={'validation':{'status':'success','plan_length':1,'validator':{'status':'valid'}},
              'replay':{'status':'valid','plan_length':1,'executed_actions':1,
                        'first_failed_action':None,'unsatisfied_goals':[]}}
        self.m.check_validation(good,['(walk a b c)'])
        for value in ('goal_unsatisfied','invalid_output'):
            bad=copy.deepcopy(good);bad['replay']['status']=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.m.check_validation(bad,['(walk a b c)'])
        bad=copy.deepcopy(good);bad['validation']['validator']['status']='invalid'
        with self.assertRaises(ValueError):self.m.check_validation(bad,['(walk a b c)'])

    def test_success_with_unexecuted_actions_is_rejected(self):
        observation={'validation':{'status':'success','plan_length':2,'validator':{'status':'valid'}},
            'replay':{'status':'valid','plan_length':2,'executed_actions':1,
                      'first_failed_action':None,'unsatisfied_goals':[]}}
        with self.assertRaises(ValueError):self.m.check_validation(observation,['(a b)','(c d)'])

    def test_metrics_require_matching_normalization_and_finite_numbers(self):
        self.assertEqual(self.m.metric_pair({'mse':0.2,'nmse':0.1}), (0.2,0.1))
        for metrics in ({'mse':float('nan'),'nmse':0.1},{'mse':0.0,'nmse':0.1},
                        {'mse':0.1,'nmse':True},{'mse':-1,'nmse':-1}):
            with self.subTest(metrics=metrics),self.assertRaises(ValueError):
                self.m.metric_pair(metrics)

    def test_json_reader_rejects_duplicates_nonfinite_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'record.json'
            for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":1e999}'):
                p.write_bytes(raw)
                with self.assertRaises(ValueError):self.m.read(root,'record.json')
            with self.assertRaises(ValueError):self.m.read(root,'../record.json')

    def test_complete_budget_cannot_exceed_reserved_or_limit(self):
        counts={k:0 for k in self.m.COUNT_KEYS};counts['sandbox_calls']=8
        good={'maximum':40,'reserved':12,'actual':8}
        self.m.check_budget(good,counts,12,40)
        for bad in ({'maximum':40,'reserved':7,'actual':8},
                    {'maximum':40,'reserved':12,'actual':7},
                    {'maximum':41,'reserved':12,'actual':8}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                self.m.check_budget(bad,counts,12,40)


if __name__=='__main__':unittest.main()
