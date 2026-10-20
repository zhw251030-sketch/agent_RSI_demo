"""Evidence sufficiency is narrower than semantic repair or causal truth."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InferencePolicyTests(unittest.TestCase):
    def setUp(self):
        self.m = importlib.import_module('rsi_eval.inference_policy')
        self.cases = importlib.import_module('rsi_eval.inference_cases')
        self.bundle = self.cases.load_inference_bundle(ROOT)
        self.parent = copy.deepcopy(self.m.S0)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)/'policy'
        self.pair = 'p1'

    def submission(self):
        return self.m.fixture_submission(self.bundle)

    def controller(self, **kwargs):
        return self.m.InferencePolicyController(self.bundle, self.parent, self.out,
                                               pair_id=self.pair, **kwargs)

    def check(self, **changes):
        data = self.submission(); data.update(changes)
        return self.m.check_submission(data, self.bundle, self.parent)

    def freeze(self, **kwargs):
        c = self.controller(**kwargs)
        self.assertEqual(c.submit_policy(**self.submission())['status'], 'accepted')
        f = self.m.freeze_policy(self.out, self.bundle, self.parent, 'request-1',
                                 pair_id=self.pair, **kwargs)
        return c, f

    def test_changed_source_is_not_proof_that_specific_repair_was_implemented(self):
        expected = self.m.expected_assessments(self.bundle)
        self.assertEqual(expected[0]['expected_verdict'], 'supported')
        self.assertEqual(expected[1]['expected_verdict'], 'unknown')
        self.assertEqual(expected[1]['missing_evidence'], ['predeclared_executable_edit_contract'])
        self.assertEqual(self.check(verdict_2='supported')['assessments'][1]['status'], 'overclaim')
        self.assertEqual(self.check(verdict_2='contradicted')['assessments'][1]['status'], 'overclaim')

    def test_small_positive_gain_and_missed_mse_forecast_do_not_prove_structure_unnecessary(self):
        e = self.m.expected_assessments(self.bundle)
        self.assertEqual(e[2]['expected_verdict'], 'supported')
        self.assertEqual(e[2]['details']['forecast_metric'], 'mse')
        self.assertGreater(e[2]['details']['official_nmse_gain'], 0)
        self.assertLess(e[2]['details']['forecast_actual_delta'], e[2]['details']['forecast_min_delta'])
        self.assertEqual(e[3]['expected_verdict'], 'unknown')
        self.assertEqual(e[3]['missing_evidence'], ['matched_structure_intervention'])

    def test_c3_requires_both_actual_nmse_improvement_and_registered_forecast_miss(self):
        b = copy.deepcopy(self.bundle)
        s = b['cases'][1]
        s['forecast']['min_delta'] = 0.0
        s['forecast']['status'] = 'supported'
        self.assertEqual(self.m.expected_assessments(b)[2]['expected_verdict'], 'contradicted')
        b = copy.deepcopy(self.bundle)
        s = b['cases'][1]
        s['child_metrics']['nmse'] = s['parent_metrics']['nmse']
        self.assertEqual(self.m.expected_assessments(b)[2]['expected_verdict'], 'contradicted')

    def test_c3_respects_nmse_registered_prediction_without_relabeling_mse(self):
        b = copy.deepcopy(self.bundle); s = b['cases'][1]
        s['forecast'].update(metric_key='nmse', before=s['parent_metrics']['nmse'],
                             after=s['child_metrics']['nmse'], min_delta=0.002,
                             actual_delta=s['parent_metrics']['nmse']-s['child_metrics']['nmse'])
        e = self.m.expected_assessments(b)[2]
        self.assertEqual(e['details']['forecast_metric'], 'nmse')
        self.assertEqual(e['expected_verdict'], 'supported')

    def test_all_correct_narrow_assessments_do_not_certify_rule_applicability(self):
        c = self.check()
        self.assertEqual(c['passed_checks'], 4)
        self.assertEqual(c['total_checks'], 4)
        self.assertTrue(c['all_checked_pass'])
        self.assertFalse(c['applicability_certified'])
        self.assertFalse(c['open_text_certified'])

    def test_wrong_verdicts_are_separated_from_missing_knowledge(self):
        self.assertEqual(self.check(verdict_1='unknown')['assessments'][0]['status'], 'underclaim')
        self.assertEqual(self.check(verdict_1='contradicted')['assessments'][0]['status'], 'overclaim')
        self.assertEqual(self.check(verdict_4='unknown')['assessments'][3]['status'], 'correct')

    def test_claim3_needs_both_metric_and_forecast_references(self):
        self.assertEqual(self.check(evidence_3='D-S:metrics')['assessments'][2]['status'], 'invalid')
        self.assertEqual(self.check(evidence_3='D-S:forecast')['assessments'][2]['status'], 'invalid')
        self.assertEqual(self.check(evidence_3='D-S:metrics,D-S:forecast')['assessments'][2]['status'], 'correct')

    def test_unknown_still_requires_available_case_evidence_not_invented_missing_evidence(self):
        self.assertEqual(self.check(evidence_2='D-P:source-diff')['assessments'][1]['status'], 'correct')
        self.assertEqual(self.check(evidence_2='')['assessments'][1]['status'], 'invalid')
        self.assertEqual(self.check(evidence_2='D-P:edit-contract')['assessments'][1]['status'], 'invalid')
        self.assertEqual(self.check(evidence_4='D-P:source-diff')['assessments'][3]['status'], 'invalid')

    def test_auxiliary_wrong_types_labels_missing_and_long_text_do_not_reject_policy(self):
        c = self.controller(); data = self.submission()
        data.update(verdict_1=['supported'], verdict_2='maybe', evidence_3={'id':'D-S:metrics'},
                    evidence_4=None, notes='长'*2000 + 'a'*280)
        self.assertEqual(c.submit_policy(**data)['status'], 'accepted')
        self.assertFalse(c.halted)
        self.assertEqual([x['status'] for x in c.checks['assessments']], ['invalid']*4)
        self.assertEqual(json.loads((self.out/'submission.json').read_text(encoding='utf-8')), data)
        self.assertEqual(c.policy['rule_ids'], self.parent['rule_ids'])

    def test_only_hard_rule_fields_are_required_and_empty_aux_is_preserved_as_default(self):
        c = self.controller()
        hard = {f'rule_{i}':v for i,v in enumerate(self.parent['rule_ids'],1)}
        self.assertEqual(c.submit_policy(**hard)['status'], 'accepted')
        stored=json.loads((self.out/'submission.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['notes'], '')
        self.assertEqual(c.checks['passed_checks'], 0)
        self.m.freeze_policy(self.out,self.bundle,self.parent,'request-1',pair_id=self.pair)
        self.assertEqual(self.m.load_frozen_policy(self.out,self.bundle,self.parent,pair_id=self.pair),self.parent)

    def test_oversize_notes_are_archived_softly_without_truncation(self):
        c=self.controller(); data=self.submission(); data['notes']='注'*3000
        self.assertEqual(c.submit_policy(**data)['status'],'accepted')
        self.assertEqual(c.checks['notes_status'],'oversize')
        self.assertEqual(json.loads((self.out/'submission.json').read_text(encoding='utf-8'))['notes'],data['notes'])

    def test_global_size_and_nonfinite_json_remain_hard_boundaries(self):
        for value in ('x'*65537, float('nan'), float('inf')):
            with self.subTest(value=str(value)[:20]), self.assertRaises(ValueError):
                data=self.submission(); data['notes']=value
                self.m.validate_submission(data)

    def test_non_json_auxiliary_values_are_not_silently_coerced(self):
        for value in (('a','b'), {1:'integer key'}, {'x':object()}):
            with self.subTest(value=str(value)), self.assertRaises(ValueError):
                data=self.submission();data['notes']=value
                self.m.validate_submission(data)

    def test_identical_source_bytes_contradict_only_the_source_change_proposition(self):
        b=copy.deepcopy(self.bundle);p=b['cases'][0]
        p['source_sha256']['child']=p['source_sha256']['parent']
        p['source_diff']='';p['ast_equal']=True
        expected=self.m.expected_assessments(b)
        self.assertEqual(expected[0]['expected_verdict'],'contradicted')
        self.assertEqual(expected[1]['expected_verdict'],'unknown')

    def test_unimplemented_future_contracts_cannot_receive_invented_semantic_labels(self):
        for key,value in (('edit_contract', {'predicate':'unknown'}),
                          ('matched_interventions',[{'score':0.1}])):
            b=copy.deepcopy(self.bundle);b['cases'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.m.expected_assessments(b)

    def test_invalid_hard_fields_and_unknown_fields_are_rejected(self):
        cases=[{'rule_2':'R03'}, {'rule_1':'R09'}, {'rule_1':None}, {'extra':'x'}]
        for edits in cases:
            with self.subTest(edits=edits),self.assertRaises(ValueError):
                data=self.submission();data.update(edits);self.m.validate_submission(data)
        data=self.submission();del data['rule_1']
        with self.assertRaises(ValueError):self.m.validate_submission(data)

    def test_hard_rejection_is_exclusive_and_preserved(self):
        c=self.controller();data=self.submission();data['rule_1']='bad'
        self.assertEqual(c.submit_policy(**data)['status'],'invalid_request')
        self.assertFalse(c.halted)
        self.assertEqual(c.summary()['status'],'rejected')
        self.assertEqual(c.submit_policy(**self.submission())['status'],'invalid_request')
        self.assertIsNone(c.policy)
        self.assertTrue((self.out/'rejection.json').exists())

    def test_rejection_record_storage_fault_halts_as_infrastructure_error(self):
        c=self.controller();(self.out/'rejection.json').write_text('preserve',encoding='utf-8')
        data=self.submission();data['rule_1']='bad'
        with self.assertRaises(ValueError):c.submit_policy(**data)
        self.assertTrue(c.halted)
        self.assertEqual(c.summary()['status'],'infrastructure_error')
        self.assertEqual((self.out/'rejection.json').read_text(encoding='utf-8'),'preserve')
        self.assertIsNone(c.policy)

    def test_self_and_checked_packets_have_only_feedback_difference(self):
        proposal=self.submission();feedback=self.check()
        a=self.controller(proposal=proposal)
        self.out=Path(self.tmp.name)/'checked'
        b=self.controller(proposal=proposal,feedback=feedback)
        pa,pb=a.state_packet(),b.state_packet()
        self.assertIsNone(pa.pop('inference_feedback'))
        self.assertEqual(pb.pop('inference_feedback'),feedback)
        self.assertEqual(pa,pb)
        self.assertEqual(json.loads(a.task_prompt()),a.state_packet())

    def test_forged_feedback_cannot_enter_controller(self):
        feedback=self.check();feedback['passed_checks']=0
        with self.assertRaises(ValueError):self.controller(proposal=self.submission(),feedback=feedback)
        with self.assertRaises(ValueError):self.controller(feedback=self.check())

    def test_freeze_load_binds_context_checker_request_and_raw_bytes(self):
        c,frozen=self.freeze()
        self.assertEqual(frozen['request_id'],'request-1')
        self.assertEqual(frozen['checker_version'],self.m.CHECKER_VERSION)
        sha=hashlib.sha256((self.out/'freeze.json').read_bytes()).hexdigest()
        self.assertEqual(self.m.load_frozen_policy(self.out,self.bundle,self.parent,pair_id=self.pair,
                                                 expected_freeze_sha256=sha),c.policy)
        with self.assertRaises(ValueError):
            self.m.load_frozen_policy(self.out,self.bundle,self.parent,pair_id='p2')
        with self.assertRaises(ValueError):
            self.m.load_frozen_policy(self.out,self.bundle,self.parent,pair_id=self.pair,
                                     expected_freeze_sha256='0'*64)

    def test_freeze_tampered_auxiliary_bytes_are_rejected_even_if_policy_is_identical(self):
        self.freeze()
        p=self.out/'submission.json';data=json.loads(p.read_text(encoding='utf-8'))
        data['notes']='Changed after freeze.'
        p.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaises(ValueError):self.m.load_frozen_policy(self.out,self.bundle,self.parent,pair_id=self.pair)

    def test_missing_freeze_and_overwrite_are_rejected(self):
        c=self.controller();c.submit_policy(**self.submission())
        with self.assertRaises(ValueError):self.m.load_frozen_policy(self.out,self.bundle,self.parent,pair_id=self.pair)
        with self.assertRaises(ValueError):self.controller()
        self.m.freeze_policy(self.out,self.bundle,self.parent,'request-1',pair_id=self.pair)
        with self.assertRaises(ValueError):self.m.freeze_policy(self.out,self.bundle,self.parent,'request-1',pair_id=self.pair)

    def test_storage_fault_is_not_model_rejection(self):
        c=self.controller();(self.out/'policy.json').write_text('keep',encoding='utf-8')
        with self.assertRaises(ValueError):c.submit_policy(**self.submission())
        self.assertEqual(c.summary()['status'],'infrastructure_error')
        self.assertEqual((self.out/'policy.json').read_text(encoding='utf-8'),'keep')
        self.assertFalse((self.out/'rejection.json').exists())

    def test_policy_contains_only_ids_and_copies_prevent_mutation(self):
        c=self.controller();data=self.submission();data['notes']='HOST_ONLY'
        c.submit_policy(**data)
        self.assertEqual(set(c.policy),{'version','rule_ids'})
        self.assertNotIn('HOST_ONLY',json.dumps(c.policy))
        c.policy['rule_ids'][0]='R01'
        self.assertEqual(c.policy,self.parent)
        self.assertEqual(c.summary()['candidate_executions'],0)
        self.assertFalse(c.summary()['applicability_certified'])


if __name__ == '__main__':
    unittest.main()
