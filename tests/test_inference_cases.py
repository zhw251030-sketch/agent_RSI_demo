"""Evidence requirements use immutable development transitions, not new execution."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from rsi_eval import inference_cases as cases

ROOT = Path(__file__).resolve().parents[1]


class InferenceCasesTests(unittest.TestCase):
    def copy_inputs(self, specs=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for spec in specs or cases.PINNED_CASES:
            for entry in spec['files'].values():
                path = root/entry['path']
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT/entry['path'], path)
        return root

    def changed_archive(self, index, kind, mutate):
        root = self.copy_inputs()
        specs = copy.deepcopy(cases.PINNED_CASES)
        entry = specs[index]['files'][kind]
        path = root/entry['path']
        data = json.loads(path.read_text(encoding='utf-8'))
        mutate(data)
        path.write_text(json.dumps(data), encoding='utf-8')
        entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        return root, specs

    def test_original_facts_remain_distinct_from_inferences(self):
        with patch('socket.socket', side_effect=AssertionError('No network')):
            bundle = cases.load_inference_bundle(ROOT)
        planning, symbolic = bundle['cases']
        self.assertEqual([x['case_id'] for x in bundle['cases']], ['D-P', 'D-S'])
        self.assertFalse(planning['ast_equal'])
        self.assertIn('-            adj[f[2]].add(f[1])', planning['source_diff'])
        self.assertEqual(planning['child_metrics']['total_successes'], 0)
        self.assertEqual(planning['diagnostics_before'][0]['plan_replay']['status'], 'precondition_failure')
        self.assertEqual(planning['diagnostics_after'][0]['plan_replay']['status'], 'goal_unsatisfied')
        self.assertEqual(symbolic['forecast']['metric_key'], 'mse')
        self.assertEqual(symbolic['forecast']['status'], 'contradicted')
        self.assertGreater(symbolic['forecast']['actual_delta'], 0)
        self.assertGreater(symbolic['parent_metrics']['nmse'], symbolic['child_metrics']['nmse'])
        for case in bundle['cases']:
            self.assertIsNone(case['edit_contract'])
            self.assertEqual(case['matched_interventions'], [])
            self.assertNotIn('parent_source', case)
            self.assertNotIn('child_source', case)
        self.assertLessEqual(len(json.dumps(bundle, ensure_ascii=False).encode('utf-8')), 49152)

    def test_loaders_have_no_data_or_credential_dependency(self):
        root = self.copy_inputs()
        self.assertEqual(cases.load_inference_bundle(root), cases.load_inference_bundle(ROOT))
        states_root = self.copy_inputs(cases.PINNED_STATES.values())
        self.assertEqual(cases.load_inference_states(states_root), cases.load_inference_states(ROOT))

    def test_new_states_exclude_information_descendant_b002(self):
        states = cases.load_inference_states(ROOT)
        self.assertEqual([x['state_id'] for x in states], ['P-A002', 'P-H002', 'S-poly5', 'S-odd4'])
        self.assertEqual(states[1]['record']['source_sha256'], 'deb8420baf4bacc6de52068de9844363bb60edf7e9bc6cf5d4753d14c853aca3')
        for state in states:
            self.assertEqual(set(state), {'state_id', 'family', 'source', 'n_params', 'record',
                'diagnostics', 'historical_common', 'historical_checks', 'provenance'})
            self.assertEqual(state['provenance']['candidate_executions_during_load'], 0)
        update_sources = {h for c in cases.load_inference_bundle(ROOT)['cases'] for h in c['source_sha256'].values()}
        self.assertFalse(update_sources & {s['record']['source_sha256'] for s in states})

    def test_each_update_file_is_byte_pinned(self):
        for spec in cases.PINNED_CASES:
            for entry in spec['files'].values():
                with self.subTest(path=entry['path']):
                    root = self.copy_inputs()
                    with (root/entry['path']).open('ab') as stream:
                        stream.write(b' ')
                    with self.assertRaisesRegex(ValueError, 'hash'):
                        cases.load_inference_bundle(root)

    def test_forecast_recomputed_from_original_declaration(self):
        root, specs = self.changed_archive(1, 'audits', lambda rows:
            rows[0]['compact_declaration'].update(prediction_min_delta=0.0000001))
        with patch.object(cases, 'PINNED_CASES', specs), self.assertRaisesRegex(ValueError, 'audit'):
            cases.load_inference_bundle(root)

    def test_false_claim_status_is_preserved_and_checked(self):
        bundle = cases.load_inference_bundle(ROOT)
        self.assertEqual(bundle['cases'][0]['provenance']['historical_claim_statuses'], ['unavailable'])
        root, specs = self.changed_archive(0, 'audits', lambda rows:
            rows[0]['claim_results'][0].update(status='supported'))
        with patch.object(cases, 'PINNED_CASES', specs), self.assertRaisesRegex(ValueError, 'audit'):
            cases.load_inference_bundle(root)

    def test_symbolic_wrong_split_or_task_is_rejected_after_repin(self):
        for field, value in [('task_id', 'oscillator2'), ('metric_split', 'test')]:
            def mutate(rows):
                if field == 'task_id':
                    rows[1]['results'][0]['task_id'] = value
                else:
                    rows[1][field] = value
            root, specs = self.changed_archive(1, 'trajectory', mutate)
            with patch.object(cases, 'PINNED_CASES', specs), self.assertRaises(ValueError):
                cases.load_inference_bundle(root)

    def test_source_metrics_and_diagnostics_are_cross_bound(self):
        for kind, mutate in [
            ('trajectory', lambda rows: rows[1]['metrics'].update(mse=0.5)),
            ('evidence', lambda rows: rows['symbolic-001'][0]['scalars'].update(mse=0.5)),
            ('diagnostics', lambda rows: rows['symbolic-001'][0].update(candidate_sha256='0'*64))]:
            root, specs = self.changed_archive(1, kind, mutate)
            with patch.object(cases, 'PINNED_CASES', specs), self.assertRaises(ValueError):
                cases.load_inference_bundle(root)

    def test_bundle_rejects_metric_dimension_substitution(self):
        bundle = cases.load_inference_bundle(ROOT)
        bundle['cases'][1]['forecast']['metric_key'] = 'nmse'
        with self.assertRaisesRegex(ValueError, 'forecast'):
            cases.validate_bundle(bundle)

    def test_bundle_rejects_fabricated_interventions_and_edit_contract(self):
        for name, value in [('edit_contract', {'fulfilled': False}), ('matched_interventions', [{'effect': 0}])]:
            bundle = cases.load_inference_bundle(ROOT)
            bundle['cases'][0][name] = value
            with self.assertRaises(ValueError):
                cases.validate_bundle(bundle)

    def test_bundle_rejects_unknown_extra_fields_and_duplicate_evidence(self):
        for mutate in [lambda c: c.update(parent_source='extra'),
                       lambda c: c['available_evidence'].append('D-P:metrics')]:
            bundle = cases.load_inference_bundle(ROOT)
            mutate(bundle['cases'][0])
            with self.assertRaises(ValueError):
                cases.validate_bundle(bundle)

    def test_diff_is_complete_bounded_and_not_implicitly_semantic(self):
        bundle = cases.load_inference_bundle(ROOT)
        self.assertIn('@@', bundle['cases'][0]['source_diff'])
        self.assertIn('- p3 * v * v', bundle['cases'][1]['source_diff'])
        bundle['cases'][0]['source_diff'] = 'x'*16385
        with self.assertRaises(ValueError):
            cases.validate_bundle(bundle)

    def test_outputs_are_independent_copies(self):
        original = cases.load_inference_bundle(ROOT)
        changed = cases.validate_bundle(original)
        changed['cases'][0]['child_metrics']['total_successes'] = 9
        self.assertEqual(original, cases.load_inference_bundle(ROOT))

    def test_ast_comparison_ignores_locations_not_program_content(self):
        self.assertTrue(cases.ast_equal('x=1\n', '\n\nx = 1\n'))
        self.assertFalse(cases.ast_equal('x=1\n', 'x=2\n'))


if __name__ == '__main__':
    unittest.main()
