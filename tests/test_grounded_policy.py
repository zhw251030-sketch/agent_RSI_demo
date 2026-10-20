"""Check factual premises without pretending to certify rule applicability."""
import copy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GroundedPolicyTests(unittest.TestCase):
    def setUp(self):
        if importlib.util.find_spec('rsi_eval.grounded_policy') is None:
            self.fail('Grounded policy controller is not implemented')
        self.m = importlib.import_module('rsi_eval.grounded_policy')
        self.bundle = json.loads((ROOT/'artifacts/policy-transfer/2026-10-20/v01/update-bundle.json').read_text(encoding='utf-8'))
        self.parent = copy.deepcopy(self.m.S0)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)/'policy'
        self.pair = 'draw-01'

    def submission(self):
        data = {}
        for i, rule in enumerate(('R01', 'R02', 'R04', 'R07'), 1):
            data.update({f'rule_{i}': rule, f'parent_{i}': rule in self.parent['rule_ids'],
                         f'quote_{i}': self.m.RULES[rule], f'support_{i}': 'F1' if i < 3 else 'F2',
                         f'hypothesis_{i}': 'This rule may help; this is not a verified inference.',
                         f'edit_{i}': 'Inspect the relevant artifact before proposing a concrete edit.'})
        for i, fact in enumerate((self.fact('P.after.p0.executed_actions'), self.fact('S.parent.nmse')), 1):
            data.update({f'fact_{i}_id': fact['fact_id'],
                         f'fact_{i}_value': json.dumps(fact['value']), f'fact_{i}_scope': fact['scope']})
        return data

    def fact(self, identifier):
        return next(row for row in self.m.factual_catalogue(self.bundle) if row['fact_id'] == identifier)

    def controller(self, **kwargs):
        return self.m.GroundedPolicyController(self.bundle, self.parent, self.out, pair_id=self.pair, **kwargs)

    def check(self, **changes):
        submission = self.submission(); submission.update(changes)
        return self.m.check_submission(submission, self.bundle, self.parent)

    def freeze(self, **kwargs):
        c = self.controller(**kwargs); c.submit_policy(**self.submission())
        frozen = self.m.freeze_policy(self.out, self.bundle, self.parent, 'request-0001',
                                     pair_id=self.pair, **kwargs)
        return c, frozen

    def test_catalogue_is_deterministic_scoped_and_resolves_actual_bundle_paths(self):
        table = self.m.factual_catalogue(self.bundle)
        self.assertEqual(table, self.m.factual_catalogue(copy.deepcopy(self.bundle)))
        self.assertEqual(len({x['fact_id'] for x in table}), len(table))
        for fact in table:
            value = self.bundle
            for component in fact['json_pointer'].split('/')[1:]:
                value = value[int(component)] if type(value) is list else value[component]
            self.assertEqual(fact['value'], value)
            self.assertIn(fact['case_id'], fact['scope'])
            self.assertIn(fact['family'], fact['scope'])
            self.assertLessEqual(len(fact['scope']), 160)
            self.assertNotIn('recommended_rule', fact)
        self.assertEqual(self.fact('P.after.p0.executed_actions')['value'], 0)
        self.assertEqual(self.fact('P.after.p0.plan_length')['value'], 11)
        self.assertEqual(self.fact('S.before.v.bin1.mean_residual')['value'], 0.004091271791985808)
        self.assertEqual(self.fact('S.before.v.bin3.mean_residual')['value'], 0.0016885746717607935)
        table[0]['value'] = 'mutated'
        self.assertNotEqual(table[0], self.m.factual_catalogue(self.bundle)[0])

    def test_valid_checks_do_not_certify_hypotheses_or_actions(self):
        result = self.check(hypothesis_1='A false causal explanation remains unverified.',
                            edit_1='Change an unrelated function.')
        self.assertTrue(result['all_checked_pass'])
        self.assertEqual(len(result['parent_membership']), 4)
        self.assertEqual(len(result['rule_quotes']), 4)
        self.assertEqual(len(result['facts']), 2)
        self.assertEqual(len(result['unverified']), 4)
        self.assertTrue(all(x['status'] == 'not_checked' for x in result['unverified']))
        self.assertFalse(result['applicability_certified'])

    def test_parent_membership_error_is_detected_without_rejecting_policy(self):
        result = self.check(parent_1=True)
        self.assertEqual(result['parent_membership'][0]['status'], 'contradicted')
        c = self.controller(); data = self.submission(); data['parent_1'] = True
        self.assertEqual(c.submit_policy(**data)['status'], 'accepted')
        self.assertFalse(c.halted)
        self.assertIsNotNone(c.policy)
        self.assertFalse(c.summary()['all_checked_pass'])

    def test_truncated_rule_quote_is_detected_even_with_valid_rule_id(self):
        result = self.check(quote_1='Check the input types before diagnosing a search failure.')
        self.assertEqual(result['rule_quotes'][0]['status'], 'contradicted')
        self.assertFalse(result['all_checked_pass'])

    def test_numeric_boolean_and_string_types_are_not_interchangeable(self):
        for supplied in ('false', '"0"', 'null'):
            with self.subTest(supplied=supplied):
                fact = self.check(fact_1_value=supplied)['facts'][0]
                self.assertEqual(fact['checks']['type'], 'contradicted')
                self.assertFalse(self.check(fact_1_value=supplied)['all_checked_pass'])
        self.assertTrue(self.check(fact_1_value='0.0')['all_checked_pass'])

    def test_only_finite_json_scalars_are_valid_claim_values(self):
        for supplied in ('NaN', 'Infinity', '-Infinity', '1e9999', '{}', '[]', '0 1', '', 'True'):
            with self.subTest(supplied=supplied):
                fact = self.check(fact_1_value=supplied)['facts'][0]
                self.assertEqual(fact['status'], 'invalid')
                self.assertFalse(self.check(fact_1_value=supplied)['all_checked_pass'])

    def test_boolean_and_null_catalogue_facts_keep_their_types(self):
        for identifier, correct, wrong in (
            ('S.before.v.bin3.upper_inclusive', 'true', '1'),
            ('P.after.p0.first_failed_action.action', 'null', '"null"'),
        ):
            with self.subTest(identifier=identifier):
                fact=self.fact(identifier)
                changes={'fact_1_id':identifier,'fact_1_scope':fact['scope'],'fact_1_value':correct}
                self.assertEqual(self.check(**changes)['facts'][0]['status'],'supported')
                changes['fact_1_value']=wrong
                self.assertEqual(self.check(**changes)['facts'][0]['checks']['type'],'contradicted')

    def test_exact_value_and_scope_are_checked_separately(self):
        value = self.check(fact_1_value='11')['facts'][0]
        self.assertEqual(value['checks']['value'], 'contradicted')
        self.assertEqual(value['checks']['scope'], 'supported')
        scope = self.check(fact_2_scope='symbolic/U-S/test/oscillator1/parent/nmse')['facts'][1]
        self.assertEqual(scope['checks']['value'], 'supported')
        self.assertEqual(scope['checks']['scope'], 'contradicted')

    def test_unknown_fact_and_family_coverage_are_not_structural_rejection(self):
        result = self.check(fact_2_id='imaginary.fact')
        self.assertEqual(result['facts'][1]['status'], 'invalid')
        self.assertEqual(result['coverage']['status'], 'contradicted')
        data = self.submission()
        for suffix in ('id', 'value', 'scope'): data['fact_2_'+suffix] = data['fact_1_'+suffix]
        c = self.controller(); self.assertEqual(c.submit_policy(**data)['status'], 'accepted')
        self.assertFalse(c.summary()['all_checked_pass'])
        self.assertEqual(c.checks['coverage']['observed_families'], ['planning'])

    def test_schema_rejects_extra_missing_type_and_bounds_errors(self):
        cases = [{'extra':'bad'}, {'rule_2':'R01'}, {'rule_1':'R09'}, {'parent_1':1},
                 {'parent_1':'false'}, {'quote_1':None}, {'quote_1':'q'*1001},
                 {'fact_1_id':'x'*81}, {'fact_1_value':'1'*161}, {'fact_1_scope':'x'*161},
                 {'support_1':'U-P'}, {'hypothesis_1':'h'*241}, {'edit_1':'e'*181}]
        for changes in cases:
            with self.subTest(changes=str(changes)[:70]), self.assertRaises(ValueError):
                self.check(**changes)
        data = self.submission(); del data['parent_1']
        with self.assertRaises(ValueError): self.m.check_submission(data, self.bundle, self.parent)

    def test_controller_stores_raw_submission_and_only_ids_in_policy(self):
        c = self.controller(); data = self.submission(); data['hypothesis_1'] = 'HOST_ONLY_CANARY'
        accepted = c.submit_policy(**data)
        self.assertEqual(accepted['status'], 'accepted')
        self.assertEqual(json.loads((self.out/'submission.json').read_text()), data)
        self.assertEqual(json.loads((self.out/'checks.json').read_text()), c.checks)
        self.assertEqual(set(c.policy), {'version','rule_ids'})
        self.assertNotIn('HOST_ONLY_CANARY', json.dumps(c.policy))
        self.assertEqual(c.summary()['candidate_executions'], 0)
        c.policy['rule_ids'][0] = 'R08'
        self.assertEqual(c.policy['rule_ids'][0], 'R01')

    def test_invalid_attempt_is_saved_and_cannot_be_retried(self):
        c = self.controller(); data = self.submission(); data['parent_1'] = 'false'
        result = c.submit_policy(**data)
        self.assertEqual(result['status'], 'invalid_request')
        self.assertIsNone(c.policy)
        before = {p.name:p.read_bytes() for p in self.out.iterdir()}
        self.assertEqual(c.submit_policy(**self.submission())['status'], 'invalid_request')
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.out.iterdir()})

    def test_persistence_failure_is_infrastructure_error_not_model_contract_failure(self):
        c=self.controller()
        (self.out/'policy.json').write_text('must not overwrite',encoding='utf-8')
        with self.assertRaises(ValueError): c.submit_policy(**self.submission())
        self.assertTrue(c.halted)
        self.assertEqual(c.summary()['status'],'infrastructure_error')
        self.assertEqual((self.out/'policy.json').read_text(),'must not overwrite')
        self.assertFalse((self.out/'rejection.json').exists())

    def test_nonfinite_fact_text_is_accepted_for_evaluation_with_invalid_check(self):
        c=self.controller(); data=self.submission(); data['fact_1_value']='NaN'
        self.assertEqual(c.submit_policy(**data)['status'],'accepted')
        self.assertFalse(c.halted)
        self.assertEqual(c.checks['facts'][0]['status'],'invalid')
        self.m.freeze_policy(self.out,self.bundle,self.parent,'request-1',pair_id=self.pair)
        self.assertIsNotNone(self.m.load_frozen_policy(self.out,self.bundle,self.parent,pair_id=self.pair))

    def test_self_and_checked_packets_differ_only_in_feedback(self):
        proposal = self.submission(); feedback = self.m.check_submission(proposal, self.bundle, self.parent)
        a = self.controller(proposal=proposal)
        self.out = Path(self.tmp.name)/'checked'
        b = self.controller(proposal=proposal, feedback=feedback)
        pa, pb = a.state_packet(), b.state_packet()
        self.assertIsNone(pa['premise_feedback'])
        self.assertEqual(pb['premise_feedback'], feedback)
        pa.pop('premise_feedback'); pb.pop('premise_feedback')
        self.assertEqual(pa, pb)
        self.assertEqual(json.loads(a.task_prompt()), a.state_packet())
        proposal['rule_1'] = 'R08'; feedback['all_checked_pass'] = False
        self.assertEqual(a.state_packet()['proposal']['rule_1'], 'R01')
        self.assertTrue(b.state_packet()['premise_feedback']['all_checked_pass'])

    def test_feedback_cannot_be_forged_or_given_without_a_proposal(self):
        data=self.submission(); checks=self.check(); checks['all_checked_pass']=False
        with self.assertRaises(ValueError): self.controller(proposal=data, feedback=checks)
        with self.assertRaises(ValueError): self.controller(feedback=self.check())

    def test_noop_is_valid_and_premise_errors_do_not_gate_freeze(self):
        c=self.controller(); data=self.submission()
        for i, rule in enumerate(self.parent['rule_ids'], 1): data[f'rule_{i}']=rule
        data['fact_1_value']='123'
        self.assertEqual(c.submit_policy(**data)['status'], 'accepted')
        self.assertTrue(c.summary()['no_op'])
        frozen=self.m.freeze_policy(self.out,self.bundle,self.parent,'request-1',pair_id=self.pair)
        self.assertFalse(frozen['all_checked_pass'])
        self.assertEqual(self.m.load_frozen_policy(self.out,self.bundle,self.parent,pair_id=self.pair),self.parent)

    def test_freeze_binds_context_raw_bytes_and_checker_version(self):
        c, frozen = self.freeze()
        self.assertEqual(frozen['checker_version'], self.m.CHECKER_VERSION)
        for name in ('submission.json','checks.json','policy.json'):
            self.assertEqual(frozen['files'][name], hashlib.sha256((self.out/name).read_bytes()).hexdigest())
        expected=hashlib.sha256((self.out/'freeze.json').read_bytes()).hexdigest()
        self.assertEqual(self.m.load_frozen_policy(self.out,self.bundle,self.parent,pair_id=self.pair,
                                                 expected_freeze_sha256=expected),c.policy)
        with self.assertRaises(ValueError):
            self.m.load_frozen_policy(self.out,self.bundle,self.parent,pair_id=self.pair,
                                     expected_freeze_sha256='0'*64)

    def test_revision_freeze_binds_proposal_feedback_condition_and_pair(self):
        data=self.submission(); feedback=self.check()
        c=self.controller(proposal=data,feedback=feedback); c.submit_policy(**data)
        args={'proposal':data,'feedback':feedback,'condition':'checked','pair_id':self.pair}
        self.m.freeze_policy(self.out,self.bundle,self.parent,'request-2',**args)
        self.assertEqual(self.m.load_frozen_policy(self.out,self.bundle,self.parent,**args),c.policy)
        for changed in ({'feedback':None},{'condition':'self'},{'pair_id':'other'},
                        {'proposal':{**data,'hypothesis_1':'different'}}):
            with self.subTest(changed=list(changed)), self.assertRaises(ValueError):
                self.m.load_frozen_policy(self.out,self.bundle,self.parent,**{**args,**changed})

    def test_freeze_artifacts_each_fail_on_tampering(self):
        self.freeze()
        for name in ('submission.json','checks.json','policy.json','freeze.json'):
            with self.subTest(name=name):
                path=self.out/name; original=path.read_bytes(); path.write_bytes(original+b' ')
                with self.assertRaises(ValueError):
                    self.m.load_frozen_policy(self.out,self.bundle,self.parent,pair_id=self.pair)
                path.write_bytes(original)

    def test_freeze_recomputes_checks_instead_of_trusting_saved_result(self):
        c=self.controller(); c.submit_policy(**self.submission())
        path=self.out/'checks.json'; value=json.loads(path.read_text()); value['all_checked_pass']=False
        path.write_text(json.dumps(value),encoding='utf-8')
        with self.assertRaises(ValueError):
            self.m.freeze_policy(self.out,self.bundle,self.parent,'request-1',pair_id=self.pair)

    def test_context_and_duplicate_freeze_are_rejected(self):
        self.freeze(); bundle=copy.deepcopy(self.bundle); bundle['cases'][0]['rationale']='changed'
        parent=copy.deepcopy(self.parent); parent['rule_ids'].reverse()
        for b,p in ((bundle,self.parent),(self.bundle,parent)):
            with self.assertRaises(ValueError):
                self.m.load_frozen_policy(self.out,b,p,pair_id=self.pair)
        original=(self.out/'freeze.json').read_bytes()
        with self.assertRaises(ValueError):
            self.m.freeze_policy(self.out,self.bundle,self.parent,'request-2',pair_id=self.pair)
        self.assertEqual((self.out/'freeze.json').read_bytes(),original)
        with self.assertRaises(ValueError): self.controller()

    def test_duplicate_keys_in_frozen_json_are_not_accepted(self):
        c=self.controller(); c.submit_policy(**self.submission())
        path=self.out/'policy.json'
        path.write_text('{"version":"bad","version":"revision-policy-v0.1","rule_ids":["R01","R02","R04","R07"]}',encoding='utf-8')
        with self.assertRaises(ValueError):
            self.m.freeze_policy(self.out,self.bundle,self.parent,'request-1',pair_id=self.pair)


if __name__=='__main__': unittest.main()
