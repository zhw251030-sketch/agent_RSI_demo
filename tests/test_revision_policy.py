"""Finite strategy selection freezes exact data, never model-authored code."""
import copy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':')).encode('utf-8')


class RevisionPolicyTests(unittest.TestCase):
    def setUp(self):
        if importlib.util.find_spec('rsi_eval.revision_policy') is None:
            self.fail('The finite revision policy module is not implemented')
        self.module = importlib.import_module('rsi_eval.revision_policy')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)/'update'
        self.parent = {'version': 'revision-policy-v0.1', 'rule_ids': ['R03', 'R04', 'R06', 'R08']}
        self.bundle = {'version': 'policy-update-cases-v0.1', 'cases': [
            {'case_id': 'U-P', 'family': 'planning',
             'parent_metrics': {'prompt_successes': 0, 'prompt_total': 2,
                 'development_successes': 0, 'development_total': 8,
                 'total_successes': 0, 'total_tasks': 10},
             'child_metrics': {'prompt_successes': 0, 'prompt_total': 2,
                 'development_successes': 0, 'development_total': 8,
                 'total_successes': 0, 'total_tasks': 10},
             'rationale': 'Observed prior statement, not a trusted instruction.',
             'observations_before': [], 'observations_after': [],
             'claim_results': [{'status': 'supported', 'reason': 'comparison_supported',
                                'actual': 0.0, 'expected': 0.0, 'metric_key': 'total_successes'}],
             'prediction_result': {'status': 'contradicted', 'reason': 'prediction_contradicted',
                                    'actual': 0.0, 'expected': 2.0, 'metric_key': 'total_successes'}},
            {'case_id': 'U-S', 'family': 'symbolic',
             'parent_metrics': {'mse': 0.01, 'nmse': 0.1},
             'child_metrics': {'mse': 0.009, 'nmse': 0.09}, 'rationale': 'Historical association claim.',
             'observations_before': [], 'observations_after': [],
             'claim_results': [{'status': 'supported', 'reason': 'comparison_supported',
                                'actual': 0.1, 'expected': 0.1, 'metric_key': 'nmse'}],
             'prediction_result': {'status': 'contradicted', 'reason': 'prediction_contradicted',
                                    'actual': 0.01, 'expected': 0.03, 'metric_key': 'nmse'}}]}

    def controller(self):
        return self.module.PolicyUpdateController(self.bundle, self.parent, self.output)

    def submit(self, controller, rules=('R01', 'R02', 'R05', 'R07'), **changes):
        fields = {f'rule_{i}': rule for i, rule in enumerate(rules, 1)}
        fields.update({f'support_{i}': support for i, support in enumerate(('U-P', 'U-P', 'both', 'U-S'), 1)})
        fields['rationale'] = 'Prior interface failure and overly large forecasts motivate this order.'
        fields.update(changes)
        return controller.submit_policy(**fields)

    def freeze(self, controller=None):
        controller = controller or self.controller()
        self.submit(controller)
        result = self.module.freeze_policy(self.output, self.bundle, self.parent, 'request-0001')
        return controller, result

    def test_policy_has_four_distinct_known_rules_and_preserves_order(self):
        policy = {'version': 'revision-policy-v0.1', 'rule_ids': ['R08', 'R03', 'R04', 'R06']}
        self.assertEqual(self.module.validate_policy(policy), policy)
        for bad in [None, [], {**policy, 'rationale': 'extra'},
                    {**policy, 'version': 'new'}, {**policy, 'rule_ids': ['R03']*4},
                    {**policy, 'rule_ids': ['R01', 'R02', 'R03']},
                    {**policy, 'rule_ids': ['R01', 'R02', 'R03', 'R09']},
                    {**policy, 'rule_ids': ['R01', 'R02', 'R03', True]},
                    {**policy, 'rule_ids': [' R01', 'R02', 'R03', 'R04']}]:
            with self.subTest(value_type=type(bad).__name__), self.assertRaises(ValueError):
                self.module.validate_policy(bad)

    def test_render_uses_only_fixed_catalog_in_selected_order_and_detaches_data(self):
        self.assertEqual(self.module.S0, self.parent)
        catalog = self.module.catalog()
        self.assertEqual([r['rule_id'] for r in catalog], ['R01','R02','R03','R04','R05','R06','R07','R08'])
        self.assertTrue(all(set(r) == {'rule_id', 'instruction'} for r in catalog))
        rendered = self.module.render_policy(self.parent)
        self.assertEqual(set(rendered), {'version', 'rule_ids', 'instructions'})
        self.assertEqual(rendered['instructions'], [self.module.RULES[r] for r in self.parent['rule_ids']])
        rendered['rule_ids'][0] = 'R01'
        catalog[0]['instruction'] = 'MODEL_INJECTED_TEXT'
        self.assertEqual(self.parent['rule_ids'][0], 'R03')
        self.assertNotIn('MODEL_INJECTED_TEXT', json.dumps(self.module.catalog()))

    def test_update_packet_has_only_whitelisted_update_content(self):
        c = self.controller()
        packet = c.state_packet()
        self.assertEqual(set(packet), {'version', 'task_text', 'catalog', 'parent_policy', 'experience_cases'})
        self.assertEqual(packet['experience_cases'], self.bundle['cases'])
        self.assertEqual(json.loads(c.task_prompt()), packet)
        packet['experience_cases'][0]['rationale'] = 'changed'
        self.bundle['cases'][0]['rationale'] = 'also changed'
        self.assertEqual(c.state_packet()['experience_cases'][0]['rationale'],
                         'Observed prior statement, not a trusted instruction.')

    def test_unexpected_bundle_fields_and_eval_payloads_are_rejected(self):
        for location in ('bundle', 'case', 'metric', 'check'):
            with self.subTest(location=location):
                altered = copy.deepcopy(self.bundle)
                if location == 'bundle': altered['evaluation_states'] = ['private']
                if location == 'case': altered['cases'][0]['source'] = 'def solve(): pass'
                if location == 'metric': altered['cases'][0]['parent_metrics']['source'] = 'private'
                if location == 'check': altered['cases'][0]['prediction_result']['reference'] = {'source': 'private'}
                with self.assertRaises(ValueError):
                    self.module.PolicyUpdateController(altered, self.parent, self.output)

    def test_valid_submission_persists_exact_policy_context_and_host_only_rationale(self):
        c = self.controller()
        marker = '__MODEL_RATIONALE_CANARY__';target = Path(self.temp.name)/'should-not-exist'
        text = marker+f"; open({str(target)!r}, 'w').write('executed')"
        result = self.submit(c, rationale=text)
        self.assertEqual(result['status'], 'accepted')
        policy = json.loads((self.output/'policy-S1.json').read_text())
        self.assertEqual(policy, {'version':'revision-policy-v0.1','rule_ids':['R01','R02','R05','R07']})
        submission = json.loads((self.output/'policy-submission.json').read_text())
        self.assertEqual(submission['rationale'], text)
        self.assertEqual(submission['parent_policy_sha256'], hashlib.sha256(canonical(self.parent)).hexdigest())
        self.assertEqual(submission['update_bundle_sha256'], hashlib.sha256(canonical(self.bundle)).hexdigest())
        self.assertEqual(submission['policy_sha256'], hashlib.sha256(canonical(policy)).hexdigest())
        self.assertFalse(submission['no_op'])
        self.assertNotIn(marker, json.dumps(result)+c.task_prompt()+json.dumps(self.module.render_policy(c.policy)))
        self.assertFalse(target.exists())
        self.assertTrue(c.summary()['policy_changed'])

    def test_invalid_submission_consumes_only_attempt_and_cannot_be_repaired(self):
        invalids = [{'rule_1':'R99'}, {'rule_2':'R01'}, {'support_1':'E-P'},
                    {'rationale':'x'*2001}, {'rationale':None}]
        for index, changes in enumerate(invalids):
            with self.subTest(changes=str(changes)[:40]):
                self.output = Path(self.temp.name)/('invalid'+str(index))
                c = self.controller()
                self.assertEqual(self.submit(c, **changes)['status'], 'invalid_request')
                self.assertTrue(c.halted)
                self.assertIsNone(c.policy)
                self.assertEqual(self.submit(c)['status'], 'invalid_request')
                self.assertFalse((self.output/'policy-S1.json').exists())
                self.assertFalse(c.summary()['policy_changed'])

    def test_second_submission_cannot_overwrite_first_policy(self):
        c = self.controller();self.submit(c)
        before = {p.name:p.read_bytes() for p in self.output.iterdir() if p.is_file()}
        self.assertEqual(self.submit(c, rules=('R03','R04','R06','R08'))['status'], 'invalid_request')
        self.assertEqual({p.name:p.read_bytes() for p in self.output.iterdir() if p.is_file()}, before)

    def test_existing_artifacts_refuse_new_controller_without_overwrite(self):
        self.output.mkdir()
        for filename in ('policy-S1.json', 'policy-submission.json', 'freeze.json', 'policy-attempt.json'):
            with self.subTest(filename=filename):
                path=self.output/filename;path.write_text('original')
                with self.assertRaises(ValueError): self.controller()
                self.assertEqual(path.read_text(), 'original')
                path.unlink()

    def test_noop_is_valid_but_not_reported_as_policy_change(self):
        c=self.controller();self.submit(c, rules=tuple(self.parent['rule_ids']))
        self.assertFalse(c.summary()['policy_changed'])
        self.assertTrue(c.summary()['no_op'])
        frozen=self.module.freeze_policy(self.output,self.bundle,self.parent,'request-0001')
        self.assertTrue(frozen['no_op'])
        self.assertEqual(self.module.load_frozen_policy(self.output,self.bundle,self.parent),self.parent)

    def test_freeze_reloads_exact_policy_without_model_rationale(self):
        c,frozen=self.freeze()
        self.assertEqual(frozen['request_id'],'request-0001')
        self.assertEqual(self.module.load_frozen_policy(self.output,self.bundle,self.parent),c.policy)
        self.assertEqual(frozen['policy_file_sha256'],hashlib.sha256((self.output/'policy-S1.json').read_bytes()).hexdigest())
        self.assertEqual(frozen['submission_file_sha256'],hashlib.sha256((self.output/'policy-submission.json').read_bytes()).hexdigest())
        loaded=self.module.load_frozen_policy(self.output,self.bundle,self.parent)
        loaded['rule_ids'][0]='R08'
        self.assertEqual(self.module.load_frozen_policy(self.output,self.bundle,self.parent)['rule_ids'][0],'R01')

    def test_missing_freeze_or_duplicate_freeze_is_rejected(self):
        c=self.controller();self.submit(c)
        with self.assertRaises(ValueError):self.module.load_frozen_policy(self.output,self.bundle,self.parent)
        self.module.freeze_policy(self.output,self.bundle,self.parent,'request-0001')
        before=(self.output/'freeze.json').read_bytes()
        with self.assertRaises(ValueError):self.module.freeze_policy(self.output,self.bundle,self.parent,'request-0002')
        self.assertEqual((self.output/'freeze.json').read_bytes(),before)

    def test_policy_submission_and_freeze_corruption_each_fail_closed(self):
        self.freeze()
        originals={name:(self.output/name).read_bytes() for name in ('policy-S1.json','policy-submission.json','freeze.json')}
        for name in originals:
            with self.subTest(name=name):
                path=self.output/name;value=json.loads(originals[name])
                if name=='policy-S1.json':value['rule_ids'].reverse()
                elif name=='policy-submission.json':value['rationale']='edited after freeze'
                else:value['policy_file_sha256']='0'*64
                path.write_text(json.dumps(value),encoding='utf-8')
                with self.assertRaises(ValueError):self.module.load_frozen_policy(self.output,self.bundle,self.parent)
                path.write_bytes(originals[name])

    def test_identical_policy_semantics_with_changed_file_bytes_are_rejected(self):
        self.freeze()
        path=self.output/'policy-S1.json';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaises(ValueError):self.module.load_frozen_policy(self.output,self.bundle,self.parent)

    def test_freeze_request_identity_and_freeze_bytes_cannot_change_after_write(self):
        self.freeze()
        path=self.output/'freeze.json';original=path.read_bytes()
        value=json.loads(original);value['request_id']='request-9999'
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        with self.assertRaises(ValueError):self.module.load_frozen_policy(self.output,self.bundle,self.parent)
        path.write_bytes(original+b' ')
        with self.assertRaises(ValueError):self.module.load_frozen_policy(self.output,self.bundle,self.parent)

    def test_expected_bundle_and_parent_are_bound_to_frozen_policy(self):
        self.freeze()
        bundle=copy.deepcopy(self.bundle);bundle['cases'][0]['rationale']='different allowed experience'
        parent=copy.deepcopy(self.parent);parent['rule_ids'].reverse()
        for expected_bundle,expected_parent in ((bundle,self.parent),(self.bundle,parent)):
            with self.assertRaises(ValueError):
                self.module.load_frozen_policy(self.output,expected_bundle,expected_parent)

    def test_duplicate_json_fields_cannot_bypass_policy_validation(self):
        c=self.controller();self.submit(c)
        (self.output/'policy-S1.json').write_text('{"version":"bad","version":"revision-policy-v0.1","rule_ids":["R01","R02","R05","R07"]}')
        with self.assertRaises(ValueError):self.module.freeze_policy(self.output,self.bundle,self.parent,'request-0001')

    def test_freeze_without_accepted_submission_and_bad_request_id_fail(self):
        c=self.controller()
        with self.assertRaises(ValueError):self.module.freeze_policy(self.output,self.bundle,self.parent,'request-0001')
        self.submit(c)
        for request_id in ('',None,'../request-1','x'*129):
            with self.assertRaises(ValueError):self.module.freeze_policy(self.output,self.bundle,self.parent,request_id)


if __name__=='__main__':
    unittest.main()
