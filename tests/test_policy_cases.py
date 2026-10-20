"""Archived update experience and evaluation states stay separate and immutable."""
import copy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
CONFIG = 'configs/pilots/policy-transfer-v0.1.json'


class PolicyCaseTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('rsi_eval.policy_cases'),
                             'The frozen policy case loader must exist')
        self.loader = importlib.import_module('rsi_eval.policy_cases')
        self.config = json.loads((PROJECT/CONFIG).read_text(encoding='utf-8'))

    def copy_inputs(self, role=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        names = [CONFIG] + [item['path'] for case in self.config['cases']
                           if role is None or case['role'] == role
                           for item in case['files'].values()]
        for name in names:
            target = root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROJECT/name, target)
        return root

    def altered_archive(self, case_id, kind, mutate):
        """Test semantic validation after deliberately repinning only this fixture."""
        root = self.copy_inputs()
        cases = copy.deepcopy(self.loader.PINNED_CASES)
        case = next(item for item in cases if item['case_id'] == case_id)
        entry = case['files'][kind]
        file = root/entry['path']
        data = json.loads(file.read_text(encoding='utf-8'))
        mutate(data)
        file.write_text(json.dumps(data), encoding='utf-8')
        entry['sha256'] = hashlib.sha256(file.read_bytes()).hexdigest()
        config = copy.deepcopy(self.config)
        config['cases'] = cases
        (root/CONFIG).write_text(json.dumps(config), encoding='utf-8')
        return root, cases

    def test_update_card_has_original_failed_forecasts_and_no_answers(self):
        with patch('socket.socket', side_effect=AssertionError('No model or network')):
            bundle = self.loader.load_update_bundle(PROJECT)
        self.assertEqual(set(bundle), {'version', 'cases'})
        self.assertEqual(bundle['version'], 'policy-update-cases-v0.1')
        self.assertEqual([case['case_id'] for case in bundle['cases']], ['U-P', 'U-S'])
        expected_fields = {'case_id', 'family', 'parent_metrics', 'child_metrics',
            'rationale', 'observations_before', 'observations_after', 'claim_results',
            'prediction_result'}
        for case in bundle['cases']:
            self.assertEqual(set(case), expected_fields)
            self.assertLessEqual(len(case['rationale']), 2000)
            self.assertEqual(case['claim_results'][0]['status'], 'supported')
            self.assertEqual(case['prediction_result']['status'], 'contradicted')
            for observation in case['observations_before'] + case['observations_after']:
                self.assertEqual(set(observation), {'task_id', 'scope',
                    'plan_replay' if case['family'] == 'planning' else 'residuals'})
        planning, symbolic = bundle['cases']
        self.assertEqual(planning['prediction_result']['metric_key'], 'total_successes')
        self.assertEqual(planning['prediction_result']['actual'], 0)
        self.assertEqual(planning['prediction_result']['expected'], 2)
        self.assertEqual(planning['observations_after'][0]['plan_replay']['plan_length'], 11)
        self.assertEqual(planning['observations_after'][0]['plan_replay']['executed_actions'], 0)
        self.assertEqual(symbolic['parent_metrics']['nmse'], 0.09639217003192727)
        self.assertEqual(symbolic['child_metrics']['nmse'], 0.09588857767292072)
        self.assertAlmostEqual(symbolic['prediction_result']['actual'], 0.0005035923590065439)
        self.assertEqual(symbolic['claim_results'][0]['metric_key'], 'bin.v.2.mean_residual')
        serialized = json.dumps(bundle)
        for forbidden in ['source_sha256', 'candidate_sha256', 'candidate_id', 'reference',
                          'trace', 'artifacts/', 'E-P', 'E-S', 'def get_plan', 'def equation',
                          '/home/', 'incumbent_source', 'planning-003', 'symbolic-002']:
            self.assertNotIn(forbidden, serialized)
        self.assertIsNone(re.search(r'\b[0-9a-f]{64}\b', serialized))

    def test_evaluation_loads_original_states_without_history_or_rescoring(self):
        with (patch('socket.socket', side_effect=AssertionError('No network')),
              patch('subprocess.run', side_effect=AssertionError('No candidate execution'))):
            states = self.loader.load_evaluation_states(PROJECT)
        self.assertEqual([state['state_id'] for state in states], ['E-P', 'E-S'])
        planning, symbolic = states
        self.assertEqual(planning['record']['candidate_id'], 'planning-003')
        self.assertEqual(planning['record']['metrics']['total_successes'], 0)
        self.assertEqual(planning['record']['source_sha256'],
                         '2f98dbb2b63144134a73cf1f9068f32df92b28779168b5859d9af537b2b0c897')
        self.assertEqual(planning['diagnostics'][0]['plan_replay']['missing_preconditions'],
                         [['link', 'gate', 'location4']])
        self.assertEqual(symbolic['record']['candidate_id'], 'symbolic-002')
        self.assertEqual(symbolic['record']['metrics']['nmse'], 0.09591726394116994)
        self.assertEqual(symbolic['n_params'], 3)
        for state in states:
            self.assertEqual(set(state), {'state_id', 'family', 'source', 'n_params', 'record',
                'diagnostics', 'historical_common', 'historical_checks', 'provenance'})
            self.assertEqual(state['historical_common'], {})
            self.assertEqual(state['historical_checks'], {})
            self.assertEqual(state['provenance']['candidate_executions_during_load'], 0)
            self.assertEqual(hashlib.sha256(state['source'].encode('utf-8')).hexdigest(),
                             state['record']['source_sha256'])

    def test_update_loader_does_not_read_evaluation_files_and_reverse(self):
        update_only = self.copy_inputs('update')
        self.assertEqual(len(self.loader.load_update_bundle(update_only)['cases']), 2)
        evaluation_only = self.copy_inputs('evaluation')
        self.assertEqual(len(self.loader.load_evaluation_states(evaluation_only)), 2)

    def test_loader_outputs_are_independent_copies(self):
        before_bundle = self.loader.load_update_bundle(PROJECT)
        before_states = self.loader.load_evaluation_states(PROJECT)
        bundle = self.loader.load_update_bundle(PROJECT)
        states = self.loader.load_evaluation_states(PROJECT)
        bundle['cases'][0]['child_metrics']['total_successes'] = 10
        bundle['cases'][1]['claim_results'][0]['actual'] = 99
        states[0]['record']['metrics']['total_successes'] = 10
        states[1]['diagnostics'][0]['residuals']['bias'] = 999
        self.assertEqual(self.loader.load_update_bundle(PROJECT), before_bundle)
        self.assertEqual(self.loader.load_evaluation_states(PROJECT), before_states)

    def test_each_pinned_archive_file_rejects_byte_tampering(self):
        for case in self.config['cases']:
            for kind, entry in case['files'].items():
                with self.subTest(case=case['case_id'], kind=kind):
                    root = self.copy_inputs()
                    with (root/entry['path']).open('ab') as stream:
                        stream.write(b' ')
                    load = (self.loader.load_update_bundle if case['role'] == 'update'
                            else self.loader.load_evaluation_states)
                    with self.assertRaisesRegex(ValueError, 'hash'):
                        load(root)

    def test_config_edit_cannot_replace_independently_pinned_case(self):
        root = self.copy_inputs()
        config = copy.deepcopy(self.config)
        config['cases'][0]['files']['source']['sha256'] = '0'*64
        (root/CONFIG).write_text(json.dumps(config), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'pinned'):
            self.loader.load_update_bundle(root)

    def test_evaluation_rejects_incomplete_or_reordered_execution_records(self):
        for mutate in [lambda rows: rows[3]['results'].pop(),
                       lambda rows: rows[3]['results'].reverse(),
                       lambda rows: rows[3]['results'][0].update(status='infrastructure_error')]:
            root, cases = self.altered_archive('E-P', 'trajectory', mutate)
            with patch.object(self.loader, 'PINNED_CASES', cases), self.assertRaises(ValueError):
                self.loader.load_evaluation_states(root)

    def test_evaluation_rejects_record_and_result_metric_disagreement(self):
        for case_id, mutate in [
            ('E-P', lambda rows: rows[3]['metrics'].update(total_successes=1)),
            ('E-S', lambda rows: rows[2]['results'][0]['metrics'].update(nmse=0.5))]:
            root, cases = self.altered_archive(case_id, 'trajectory', mutate)
            with patch.object(self.loader, 'PINNED_CASES', cases), self.assertRaisesRegex(ValueError, 'metric'):
                self.loader.load_evaluation_states(root)

    def test_diagnostic_binding_scope_and_record_plan_length_are_verified(self):
        mutations = [lambda data: data['planning-003'][0].update(candidate_sha256='0'*64),
                     lambda data: data['planning-003'][0].update(task_id='spannerlearning/seed0/problem99'),
                     lambda data: data['planning-003'][0]['plan_replay'].update(plan_length=999)]
        for mutate in mutations:
            root, cases = self.altered_archive('E-P', 'diagnostics', mutate)
            with patch.object(self.loader, 'PINNED_CASES', cases), self.assertRaises(ValueError):
                self.loader.load_evaluation_states(root)

    def test_symbolic_diagnostic_must_agree_with_recorded_mse(self):
        root, cases = self.altered_archive('E-S', 'diagnostics',
            lambda data: data['symbolic-002'][0]['residuals'].update(rmse=0.9))
        with patch.object(self.loader, 'PINNED_CASES', cases), self.assertRaisesRegex(ValueError, 'diagnostic'):
            self.loader.load_evaluation_states(root)

    def test_update_evidence_binding_and_scores_are_verified(self):
        for mutate in [lambda data: data['symbolic-001'][0]['binding'].update(candidate_id='symbolic-999'),
                       lambda data: data['symbolic-001'][0]['scalars'].update(nmse=0.5)]:
            root, cases = self.altered_archive('U-S', 'evidence', mutate)
            with patch.object(self.loader, 'PINNED_CASES', cases), self.assertRaisesRegex(ValueError, 'evidence'):
                self.loader.load_update_bundle(root)

    def test_update_outcomes_must_match_original_claim_and_forecast(self):
        root, cases = self.altered_archive('U-S', 'audits',
            lambda rows: rows[0]['prediction_result'].update(status='supported'))
        with patch.object(self.loader, 'PINNED_CASES', cases), self.assertRaisesRegex(ValueError, 'audit'):
            self.loader.load_update_bundle(root)

    def test_original_compact_declaration_must_match_saved_expansion(self):
        root, cases = self.altered_archive('U-S', 'audits',
            lambda rows: rows[0]['compact_declaration'].update(prediction_min_delta=0.0001))
        with patch.object(self.loader, 'PINNED_CASES', cases), self.assertRaisesRegex(ValueError, 'audit'):
            self.loader.load_update_bundle(root)

    def test_update_diagnostics_cannot_silently_add_source_or_evaluation_content(self):
        root, cases = self.altered_archive('U-P', 'diagnostics',
            lambda data: data['planning-001'][0]['plan_replay'].update(source='def get_plan(*args): pass'))
        with patch.object(self.loader, 'PINNED_CASES', cases), self.assertRaises(ValueError):
            self.loader.load_update_bundle(root)

    def test_oversized_original_rationale_is_rejected_not_silently_rewritten(self):
        root, cases = self.altered_archive('U-P', 'trajectory',
            lambda rows: rows[1].update(rationale='x'*2001))
        with patch.object(self.loader, 'PINNED_CASES', cases), self.assertRaisesRegex(ValueError, 'rationale'):
            self.loader.load_update_bundle(root)

    def test_config_pairs_all_three_arms_for_each_state_and_reverses_second_repeat(self):
        order = self.config['order']
        self.assertEqual(len(order), 12)
        for state in ['E-P', 'E-S']:
            for repeat in [1, 2]:
                group = [row for row in order if row['state_id'] == state and row['repeat'] == repeat]
                self.assertEqual({row['condition'] for row in group}, {'fixed', 'memory', 'updated'})
                self.assertEqual(len({row['pair_id'] for row in group}), 1)
        first = [(row['state_id'], row['condition']) for row in order[:6]]
        second = [(row['state_id'], row['condition']) for row in order[6:]]
        self.assertEqual(second, first[::-1])
        self.assertEqual(self.config['budgets']['max_requests'], 13)
        self.assertEqual(self.config['budgets']['max_requests_per_session'], 1)
        self.assertEqual(self.config['max_generated_candidates'], 1)
        self.assertFalse(self.config['baseline_reexecution'])
        self.assertFalse(self.config['automatic_recovery'])


if __name__ == '__main__':
    unittest.main()
