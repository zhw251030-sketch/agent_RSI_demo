"""Pinned evidence replay inputs and the hidden/checked information boundary."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
IDS = ['P-format', 'P-empty', 'S-v3', 'S-x5']


class DecisionCasesTests(unittest.TestCase):
    def setUp(self):
        try:
            self.m = importlib.import_module('rsi_eval.decision_cases')
        except ModuleNotFoundError as exc:
            self.fail('Decision replay loader is not implemented: ' + str(exc))

    def _copy_inputs(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for relative in self.m.INPUT_FILES:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        return root

    def test_four_fixed_states_preserve_historical_sources_and_results(self):
        cases = self.m.load_cases(ROOT)
        self.assertEqual([c['case_id'] for c in cases], IDS)
        for case in cases:
            self.assertEqual(case['id'], case['case_id'])
            raw = (ROOT / case['source_path']).read_bytes()
            self.assertEqual(case['source'].encode(), raw)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), case['source_sha256'])
            records = json.loads((ROOT / case['provenance']['trajectory_path']).read_bytes())
            self.assertEqual(case['historical_record'], records[1])
            self.assertEqual(case['baseline_results'], records[1]['results'])
            self.assertEqual(case['baseline_metrics'], records[1]['metrics'])
            self.assertEqual(case['n_params'], records[1]['n_params'])
        self.assertEqual(cases[1]['n_params'], 3)

    def test_original_development_scope_and_existing_controller_contract(self):
        from rsi_eval.two_stage_core import _case
        for case in self.m.load_cases(ROOT):
            self.assertEqual(_case(case), case)
            if case['family'] == 'planning':
                self.assertEqual(case['task_ids'], [f'spannerlearning/seed0/problem{i}' for i in range(10)])
                self.assertEqual(case['prompt_task_ids'], case['task_ids'][:2])
                self.assertEqual(case['development_task_ids'], case['task_ids'][2:])
                self.assertEqual([r['task_id'] for r in case['public_packet']['public_examples']], case['task_ids'][:2])
            else:
                self.assertEqual(case['task_ids'], ['oscillator1'])
                self.assertEqual(case['prompt_task_ids'], [])
                self.assertEqual(case['public_packet']['public_examples'], [])

    def test_actual_archive_provides_positive_and_negative_feedback_in_each_family(self):
        cases = self.m.load_cases(ROOT)
        labels = [([x['verdict'] for x in c['archive_feedback']['observations']]
                   if c['family'] == 'planning' else c['archive_feedback']['verdict']) for c in cases]
        self.assertEqual(labels, [['supported'] * 2, ['contradicted'] * 2, 'supported', 'contradicted'])
        self.assertAlmostEqual(cases[2]['archive_feedback']['delta_nmse'], 0.0015132655690959645)
        self.assertAlmostEqual(cases[3]['archive_feedback']['delta_nmse'], 7.180197444667247e-7)
        for case in cases:
            self.assertEqual(case['archive_feedback']['case_id'], case['case_id'])
            self.assertEqual(case['archive_feedback']['source_sha256'], case['source_sha256'])

    def test_parent_program_remains_host_only_and_correct_term_is_selected(self):
        for case, expected in zip(self.m.load_cases(ROOT)[2:], [(6, 5, 5), (5, 4, 4)]):
            self.assertEqual((case['n_params'], case['parent_n_params'], case['remove_param_index']), expected)
            self.assertEqual(case['parent_source'].encode(), (ROOT / case['parent_path']).read_bytes())
            target = case['public_packet']['probe_target']
            self.assertEqual(target['target_id'], 'param' + str(expected[2]))
            self.assertEqual(target['parent_source_sha256'], case['parent_sha256'])
            self.assertNotIn('parent_source', target)
            self.assertNotIn('parent_metrics', target)

    def test_common_packet_does_not_include_old_registration_or_probe_answers(self):
        forbidden = {'registration', 'planned_edit', 'archive_feedback', 'probe_feedback', 'verdict',
                     'delta_nmse', 'sham_delta_nmse', 'next_edit_scope', 'parent_source', 'parent_metrics',
                     'historical_record', 'baseline_results', 'provenance', 'rationale', 'forecast',
                     'variants', 'canonical_source', 'removed_source', 'params', 'history'}
        def visit(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for item in value.values(): visit(item)
            elif isinstance(value, list):
                for item in value: visit(item)
        for case in self.m.load_cases(ROOT):
            packet = case['public_packet']; visit(packet)
            self.assertEqual(packet['historical_metrics'], case['baseline_metrics'])
            self.assertEqual(packet['historical_observations'], [])
            self.assertNotIn('## Revision policy', packet['task_text'])
            self.assertEqual(packet, case['state_packet'])
            self.assertNotIn('probe.json', json.dumps(packet))

    def test_feedback_has_no_program_plan_parameters_or_recommended_edit(self):
        forbidden = {'source', 'parent_source', 'canonical_source', 'removed_source', 'plan', 'params',
                     'parameters', 'next_edit_scope', 'normalized_plan', 'transformation', 'raw', 'normalized'}
        def visit(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for item in value.values(): visit(item)
            elif isinstance(value, list):
                for item in value: visit(item)
        for case in self.m.load_cases(ROOT):
            visit(case['archive_feedback'])
            self.assertLess(len(json.dumps(case['archive_feedback']).encode()), 6000)

    def test_source_comment_prior_information_is_preserved_and_disclosed(self):
        case = self.m.load_cases(ROOT)[2]
        self.assertIn('0.0938', case['public_packet']['source'])
        self.assertIn('source comments', case['public_packet']['scope_note'])
        self.assertIn('prior approximate parent', case['provenance']['information_limit'])

    def test_provenance_tracks_every_read_and_marks_replay_without_new_execution(self):
        real = Path.read_bytes; seen = set()
        def read(path):
            relative = path.relative_to(ROOT).as_posix()
            self.assertIn(relative, self.m.INPUT_FILES); seen.add(relative)
            return real(path)
        with patch.object(Path, 'read_bytes', read), patch.object(Path, 'write_bytes', side_effect=AssertionError('write')):
            cases = self.m.load_cases(ROOT)
        self.assertEqual(seen, set(self.m.INPUT_FILES))
        for case in cases:
            p = case['provenance']
            self.assertEqual(p['source_files'], self.m.INPUT_FILES)
            self.assertEqual(p['candidate_executions_during_load'], 0)
            self.assertEqual(p['model_calls'], 0)
            self.assertEqual(p['sealed_data_reads'], 0)
            self.assertIn('not independent', p['selection_scope'])
            self.assertIn('omitted', p['diagnostics_policy'])

    def test_minimal_archive_tree_needs_no_data_or_candidate_execution(self):
        root = self._copy_inputs()
        with patch('rsi_eval.two_stage_core.evaluate_candidate', side_effect=AssertionError('execute')):
            self.assertEqual(self.m.load_cases(root), self.m.load_cases(ROOT))
        self.assertFalse((root / 'data').exists())

    def test_each_feedback_file_tampering_is_rejected(self):
        for relative in self.m.FEEDBACK_FILES:
            with self.subTest(relative=relative):
                root = self._copy_inputs(); path = root / relative
                path.write_bytes(path.read_bytes() + b'\n')
                with self.assertRaises(ValueError): self.m.load_cases(root)

    def test_source_parent_records_manifest_and_task_tampering_is_rejected(self):
        cases = self.m.load_cases(ROOT)
        paths = [cases[0]['source_path'], cases[2]['parent_path'], cases[1]['provenance']['trajectory_path'],
                 self.m.FEEDBACK_MANIFEST_PATH, self.m.PUBLIC_PACKETS['symbolic']['path'],
                 self.m.PUBLIC_PACKETS['planning']['path'], self.m.SOURCE_MANIFEST_PATH]
        for relative in paths:
            with self.subTest(relative=relative):
                root = self._copy_inputs(); path = root / relative
                path.write_bytes(path.read_bytes() + b'\n')
                with self.assertRaises(ValueError): self.m.load_cases(root)

    def test_missing_feedback_is_rejected(self):
        root = self._copy_inputs()
        (root / next(iter(self.m.FEEDBACK_FILES))).unlink()
        with self.assertRaises(ValueError): self.m.load_cases(root)

    def test_symlinked_feedback_is_rejected(self):
        root = self._copy_inputs(); path = root / next(iter(self.m.FEEDBACK_FILES))
        other = root / 'replacement.json'; shutil.copyfile(path, other); path.unlink()
        try: path.symlink_to(other)
        except OSError: self.skipTest('Symbolic-link creation unavailable')
        with self.assertRaises(ValueError): self.m.load_cases(root)

    def test_alias_projection_does_not_rewrite_original_archive_case_identity(self):
        for case in self.m.load_cases(ROOT)[2:]:
            path = ROOT / case['provenance']['feedback_files'][0]
            before = path.read_bytes(); original = json.loads(before)
            self.assertEqual(original['case_id'], case['provenance']['archive_case_id'])
            self.assertNotEqual(original['case_id'], case['case_id'])
            self.assertEqual(path.read_bytes(), before)

    def test_returned_mutable_packets_are_independent(self):
        cases = self.m.load_cases(ROOT); before = copy.deepcopy(cases)
        cases[0]['public_packet']['historical_metrics']['total_successes'] = 99
        cases[2]['archive_feedback']['observations'].clear()
        self.assertEqual(cases[0]['state_packet'], before[0]['state_packet'])
        self.assertEqual(cases[0]['baseline_metrics'], before[0]['baseline_metrics'])
        self.assertEqual(self.m.load_cases(ROOT), before)


if __name__ == '__main__':
    unittest.main()
