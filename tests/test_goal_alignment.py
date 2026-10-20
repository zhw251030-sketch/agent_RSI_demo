"""Behavioral tests for declared goals; fixtures are simulations, not S results."""
import copy
import hashlib
import importlib
import json
import math
import unittest


try:
    goal = importlib.import_module('rsi_eval.goal_alignment')
except ModuleNotFoundError as error:
    if error.name != 'rsi_eval.goal_alignment':
        raise
    goal = None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def plan_rows(successes=(), ids=('p0', 'd0', 'd1', 'd2')):
    return [dict(task_id=t, status='success' if t in successes else 'candidate_error') for t in ids]


def strategy_fixture():
    def policy(name, rules):
        body = dict(content={'version':'simulated-v1', 'rules':rules}, renderer_sha256='a'*64)
        return dict(body, sha256=digest(body), policy_id=name)
    parent = policy('old', ['G1', 'G3'])
    candidate = policy('new', ['G2', 'G3'])
    def state(identifier, family):
        planning = family == 'planning'
        return dict(id=identifier, family=family, base_source_sha256='b'*64,
            base_n_params=3, task_ids=['p0','d0','d1','d2'] if planning else ['eq'],
            development_ids=['d0','d1','d2'] if planning else [],
            public_ids=['p0'] if planning else [], metric_scope='selection' if planning else 'train',
            feedback_sha256='c'*64, model_config_sha256='d'*64, budget_sha256='e'*64,
            evaluator_sha256='f'*64, data_sha256='1'*64, replicate_ids=['r1'])
    states = [state('P', 'planning'), state('S', 'symbolic')]
    allocation = dict(version='goal-selection-allocation-v0.1', role='selection', states=states)
    allocation['sha256'] = digest(allocation)
    pairs = []
    for st in states:
        def measurement(pol, improved):
            results = plan_rows(('p0','d0','d1') if improved else ('p0','d0')) if st['family']=='planning' else [
                dict(task_id='eq', status='success', metrics={'nmse':0.1})]
            value = dict(policy_sha256=pol['sha256'], allocation_sha256=allocation['sha256'],
                context_sha256=digest(st), source_sha256=('2' if improved else '3')*64,
                state_id=st['id'],replicate_id='r1',request_id=f"{st['id']}-r1-{pol['policy_id']}",
                n_params=3, status='measured', results=results)
            value['evaluation_sha256'] = digest(value)
            return value
        pairs.append(dict(state_id=st['id'], replicate_id='r1',
            parent=measurement(parent, False), candidate=measurement(candidate, st['family']=='planning')))
    return parent, candidate, allocation, pairs


def rehash_measurement(row):
    row['evaluation_sha256'] = digest({k:v for k,v in row.items() if k != 'evaluation_sha256'})


class GoalTestCase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(goal, 'goal_alignment production module is not implemented')


class PlanningGoalTests(GoalTestCase):
    def assess(self, parent, candidate):
        return goal.assess_planning(parent, candidate,
            development_ids=['d0','d1','d2'], public_ids=['p0'])

    def test_net_gain_cannot_hide_loss_of_previously_solved_development_task(self):
        result = self.assess(plan_rows(['d0']), plan_rows(['d1','d2']))
        self.assertEqual(result['decision'], 'reject')
        self.assertEqual(result['metrics']['development_delta'], 1)
        self.assertEqual(result['details']['development']['lost_ids'], ['d0'])
        self.assertEqual(result['details']['development']['gained_ids'], ['d1','d2'])

    def test_public_regression_also_blocks_promotion(self):
        result = self.assess(plan_rows(['p0']), plan_rows(['d0']))
        self.assertEqual(result['decision'], 'reject')
        self.assertEqual(result['details']['public']['lost_ids'], ['p0'])

    def test_measured_gain_survives_unknown_edit_claim(self):
        old = plan_rows(['p0']); new = plan_rows(['p0','d1'])
        for row in new: row['edit_claim_status'] = 'unknown'
        self.assertEqual(self.assess(old,new)['decision'], 'promote')

    def test_relabeling_and_same_successes_have_no_gain(self):
        old = plan_rows(['p0','d0']); new = copy.deepcopy(old)
        for row in new: row['edit_claim'] = 'keep_bytes'
        self.assertEqual(self.assess(old,new)['decision'], 'retain')

    def test_public_only_gain_does_not_change_development_objective(self):
        self.assertEqual(self.assess(plan_rows(),plan_rows(['p0']))['decision'], 'retain')

    def test_infrastructure_failure_is_not_a_measured_task_failure(self):
        new = plan_rows(['p0','d0']); new[2]['status'] = 'infrastructure_error'
        self.assertEqual(self.assess(plan_rows(),new)['decision'], 'unknown')

    def test_missing_duplicate_and_extra_task_records_are_unknown(self):
        original = plan_rows()
        for new in [original[:-1], original+[original[0]], original+[dict(task_id='extra',status='success')]]:
            with self.subTest(new=new):
                self.assertEqual(self.assess(original,new)['decision'], 'unknown')

    def test_status_typo_is_unknown_not_silently_a_valid_failure(self):
        for status in ['sucess',[],None,True]:
            new=plan_rows(); new[0]['status']=status
            with self.subTest(status=status):
                self.assertEqual(self.assess(plan_rows(),new)['decision'], 'unknown')

    def test_allocation_overlap_is_rejected(self):
        with self.assertRaises(ValueError):
            goal.assess_planning([],[],development_ids=['p0'],public_ids=['p0'])


class SymbolicGoalTests(GoalTestCase):
    def assess(self, nmse=0.1, n_params=4):
        return goal.assess_symbolic(dict(nmse=0.1,n_params=4),dict(nmse=nmse,n_params=n_params))

    def test_simplification_can_allow_small_loss_without_becoming_accuracy_improvement(self):
        result=self.assess(0.1000007,3)
        self.assertEqual(result['decision'],'promote')
        self.assertTrue(result['metrics']['acceptable_simplification'])
        self.assertFalse(result['metrics']['meaningful_improvement'])

    def test_accuracy_gain_with_more_parameters_is_reported_separately(self):
        result=self.assess(0.099,5)
        self.assertEqual(result['decision'],'promote')
        self.assertTrue(result['metrics']['meaningful_improvement'])
        self.assertFalse(result['metrics']['acceptable_simplification'])

    def test_more_parameters_without_meaningful_gain_are_rejected(self):
        self.assertEqual(self.assess(0.0999999,5)['decision'],'reject')

    def test_same_formula_and_tiny_accuracy_drift_do_not_earn_improvement(self):
        self.assertEqual(self.assess()['decision'],'retain')
        self.assertEqual(self.assess(0.0999999)['decision'],'retain')

    def test_excess_loss_is_rejected_even_when_simpler(self):
        self.assertEqual(self.assess(0.101,3)['decision'],'reject')

    def test_both_threshold_boundaries_are_uncertain(self):
        for delta in [-1e-5, -1e-5+5e-11, -1e-5-5e-11,1e-5,1e-5+5e-11,1e-5-5e-11]:
            with self.subTest(delta=delta):
                self.assertEqual(self.assess(0.1+delta,3)['decision'],'unknown')

    def test_nonfinite_negative_boolean_and_missing_values_are_unknown(self):
        for v in [math.nan,math.inf,-1,True,None,'0.1']:
            with self.subTest(v=v): self.assertEqual(self.assess(v)['decision'],'unknown')
        for n in [True,-1,1.5,None]:
            with self.subTest(n=n): self.assertEqual(self.assess(n_params=n)['decision'],'unknown')

    def test_zero_fitted_parameters_are_a_valid_simplification(self):
        self.assertEqual(self.assess(0.1,0)['decision'],'promote')

    def test_optional_scope_bindings_cannot_disagree_or_be_one_sided(self):
        old=dict(nmse=0.1,n_params=4,task_id='eq1',data_sha256='1'*64)
        for new in [dict(nmse=0.01,n_params=4),
                    dict(nmse=0.01,n_params=4,task_id='eq2',data_sha256='1'*64)]:
            with self.subTest(new=new): self.assertEqual(goal.assess_symbolic(old,new)['decision'],'unknown')


class OpportunityTests(GoalTestCase):
    def test_negating_large_loss_supports_trial_not_final_success(self):
        result=goal.symbolic_opportunity(0.1,0.1000007,0.1,5,4)
        self.assertIs(result['proposition']['truth'],False)
        self.assertEqual(result['opportunity'],'eligible_for_trial')
        self.assertFalse(result['details']['final_candidate_benefit_measured'])

    def test_large_removal_loss_is_evidence_against_this_simplification_trial(self):
        result=goal.symbolic_opportunity(0.1,0.101,0.1,6,5)
        self.assertIs(result['proposition']['truth'],True)
        self.assertEqual(result['opportunity'],'avoid_supported_harm')

    def test_sham_drift_boundary_missing_or_failed_fit_never_gives_opportunity(self):
        cases=[(0.1,0.1,0.100001,5,4),(0.1,0.10001,0.1,5,4),
               (0.1,None,0.1,5,4),(0.1,0.1,None,5,4),(0.1,math.nan,0.1,5,4)]
        for args in cases:
            with self.subTest(args=args):
                result=goal.symbolic_opportunity(*args)
                self.assertIsNone(result['proposition']['truth'])
                self.assertEqual(result['opportunity'],'unknown')

    def test_non_nested_parameter_counts_do_not_support_simplification(self):
        result=goal.symbolic_opportunity(0.1,0.1,0.1,4,4)
        self.assertEqual(result['opportunity'],'unknown')

    def test_zero_parameter_removal_can_be_tried_but_nested_fit_anomaly_cannot(self):
        self.assertEqual(goal.symbolic_opportunity(0.1,0.1,0.1,1,0)['opportunity'],'eligible_for_trial')
        result=goal.symbolic_opportunity(0.1,0.09,0.1,5,4)
        self.assertEqual(result['opportunity'],'unknown')
        self.assertIsNone(result['proposition']['truth'])


class StrategySelectionTests(GoalTestCase):
    def test_direct_paired_result_dominance_can_promote_different_frozen_strategy(self):
        result=goal.select_strategy(*strategy_fixture())
        self.assertEqual(result['decision'],'promote')
        self.assertEqual(result['metrics']['beneficial_pairs'],1)
        self.assertEqual(result['metrics']['retained_pairs'],1)
        self.assertEqual(len(result['details']['pairs']),2)

    def test_different_samples_of_same_strategy_cannot_be_called_an_update(self):
        parent,candidate,allocation,pairs=strategy_fixture()
        candidate=copy.deepcopy(parent);candidate['policy_id']='other-label'
        for pair in pairs:
            pair['candidate']['policy_sha256']=candidate['sha256'];rehash_measurement(pair['candidate'])
        result=goal.select_strategy(parent,candidate,allocation,pairs)
        self.assertEqual(result['decision'],'no_policy_change')

    def test_loss_of_old_success_blocks_promotion_despite_net_gain(self):
        parent,candidate,allocation,pairs=strategy_fixture()
        row=pairs[0]['candidate'];row['results']=plan_rows(['d1','d2']);rehash_measurement(row)
        result=goal.select_strategy(parent,candidate,allocation,pairs)
        self.assertEqual(result['decision'],'retain')
        self.assertIn('pair_regression',result['reason_codes'])

    def test_all_ties_retain_parent(self):
        parent,candidate,allocation,pairs=strategy_fixture()
        pairs[0]['candidate']['results']=copy.deepcopy(pairs[0]['parent']['results'])
        rehash_measurement(pairs[0]['candidate'])
        self.assertEqual(goal.select_strategy(parent,candidate,allocation,pairs)['decision'],'retain')

    def test_unknown_measurement_cannot_be_treated_as_a_win(self):
        parent,candidate,allocation,pairs=strategy_fixture()
        row=pairs[1]['parent'];row['status']='missing';row['results']=None;rehash_measurement(row)
        result=goal.select_strategy(parent,candidate,allocation,pairs)
        self.assertEqual(result['decision'],'unknown')

    def test_missing_submission_has_no_fabricated_source_or_parameter_count(self):
        parent,candidate,allocation,pairs=strategy_fixture()
        row=pairs[1]['candidate']
        row.update(status='missing',results=None,source_sha256=None,n_params=None)
        rehash_measurement(row)
        result=goal.select_strategy(parent,candidate,allocation,pairs)
        self.assertEqual(result['decision'],'unknown')
        self.assertIsNone(result['details']['pairs'][1]['candidate_source_sha256'])
        self.assertEqual(result['metrics']['unknown_pairs'],1)

    def test_missing_submission_cannot_have_only_one_null_artifact_field(self):
        for field in ('source_sha256','n_params'):
            with self.subTest(field=field):
                parent,candidate,allocation,pairs=strategy_fixture()
                row=pairs[1]['candidate'];row.update(status='missing',results=None)
                row[field]=None;rehash_measurement(row)
                with self.assertRaises(ValueError):goal.select_strategy(parent,candidate,allocation,pairs)

    def test_measured_or_infrastructure_record_cannot_omit_its_artifact_identity(self):
        for status in ('measured','infrastructure_error'):
            with self.subTest(status=status):
                parent,candidate,allocation,pairs=strategy_fixture()
                row=pairs[1]['candidate'];row.update(status=status,source_sha256=None,n_params=None)
                if status=='infrastructure_error':row['results']=None
                rehash_measurement(row)
                with self.assertRaises(ValueError):goal.select_strategy(parent,candidate,allocation,pairs)

    def test_pairwise_symbolic_comparison_ignores_each_arms_claimed_base_improvement(self):
        parent,candidate,allocation,pairs=strategy_fixture()
        row=pairs[1]['candidate'];row['results'][0]['metrics']={'nmse':0.102,'achieved_improvement':True}
        rehash_measurement(row)
        self.assertEqual(goal.select_strategy(parent,candidate,allocation,pairs)['decision'],'retain')

    def test_wrong_policy_context_source_or_evaluation_hash_is_rejected(self):
        for key in ['policy_sha256','allocation_sha256','context_sha256','source_sha256','evaluation_sha256']:
            with self.subTest(key=key):
                parent,candidate,allocation,pairs=strategy_fixture()
                pairs[0]['candidate'][key]='9'*64
                if key in ('policy_sha256','allocation_sha256','context_sha256'):
                    rehash_measurement(pairs[0]['candidate'])
                with self.assertRaises(ValueError):goal.select_strategy(parent,candidate,allocation,pairs)

    def test_missing_extra_or_duplicate_pairs_are_rejected(self):
        for change in ['missing','extra','duplicate']:
            with self.subTest(change=change):
                parent,candidate,allocation,pairs=strategy_fixture()
                if change=='missing':pairs.pop()
                else:
                    extra=copy.deepcopy(pairs[0]);pairs.append(extra)
                    if change=='extra':extra['state_id']='other'
                with self.assertRaises(ValueError):goal.select_strategy(parent,candidate,allocation,pairs)

    def test_evaluation_role_and_forged_policy_snapshot_are_rejected(self):
        parent,candidate,allocation,pairs=strategy_fixture()
        allocation['role']='evaluation';allocation['sha256']=digest({k:v for k,v in allocation.items() if k!='sha256'})
        with self.assertRaises(ValueError):goal.select_strategy(parent,candidate,allocation,pairs)
        parent,candidate,allocation,pairs=strategy_fixture();candidate['content']['rules']=['G5']
        with self.assertRaises(ValueError):goal.select_strategy(parent,candidate,allocation,pairs)

    def test_evaluation_record_source_cannot_disagree_with_final_source(self):
        parent,candidate,allocation,pairs=strategy_fixture()
        row=pairs[0]['candidate'];row['results'][0]['candidate_hash']='8'*64;rehash_measurement(row)
        with self.assertRaises(ValueError):goal.select_strategy(parent,candidate,allocation,pairs)

    def test_measurement_cannot_be_rebound_to_another_slot_or_reuse_a_request(self):
        for mutation in ['state_id','replicate_id','request_id']:
            with self.subTest(mutation=mutation):
                parent,candidate,allocation,pairs=strategy_fixture()
                row=pairs[0]['candidate']
                row[mutation]=pairs[1]['candidate']['request_id'] if mutation=='request_id' else 'other'
                rehash_measurement(row)
                with self.assertRaises(ValueError):goal.select_strategy(parent,candidate,allocation,pairs)

    def test_zero_parameter_planning_metadata_is_legal(self):
        parent,candidate,allocation,pairs=strategy_fixture()
        allocation['states'][0]['base_n_params']=0
        allocation['sha256']=digest({k:v for k,v in allocation.items() if k!='sha256'})
        for index,pair in enumerate(pairs):
            for side in ('parent','candidate'):
                row=pair[side];row['allocation_sha256']=allocation['sha256']
                row['context_sha256']=digest(allocation['states'][index])
                if index==0:row['n_params']=0
                rehash_measurement(row)
        self.assertEqual(goal.select_strategy(parent,candidate,allocation,pairs)['decision'],'promote')

    def test_inputs_remain_unchanged(self):
        values=strategy_fixture();before=copy.deepcopy(values)
        goal.select_strategy(*values)
        self.assertEqual(values,before)


if __name__=='__main__':
    unittest.main()
