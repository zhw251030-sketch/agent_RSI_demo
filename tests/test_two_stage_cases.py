"""Immutable development case loading and model-visible evidence boundaries."""
import ast
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
IDS = ['P-format-missing', 'P-prefix', 'S-cubic', 'S-square']


class TwoStageCasesTests(unittest.TestCase):
    def setUp(self):
        try:
            self.m = importlib.import_module('rsi_eval.two_stage_cases')
        except ModuleNotFoundError as exc:
            self.fail('Two-stage case loader is not implemented: ' + str(exc))

    def test_fixed_cases_preserve_exact_historical_records_and_sources(self):
        cases = self.m.load_cases(ROOT)
        self.assertEqual([c['case_id'] for c in cases], IDS)
        for case in cases:
            raw = (ROOT / case['source_path']).read_bytes()
            self.assertEqual(case['source'].encode(), raw)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), case['source_sha256'])
            records = json.loads((ROOT / case['provenance']['trajectory_path']).read_bytes())
            record = records[case['provenance']['record_index']]
            self.assertEqual(case['historical_record'], record)
            self.assertEqual(case['baseline_results'], record['results'])
            self.assertEqual(case['baseline_metrics'], record['metrics'])
            self.assertEqual(case['n_params'], record['n_params'])
        self.assertEqual(cases[1]['n_params'], 3)  # Preserve the old unused value.

    def test_task_scope_is_original_two_prompt_eight_development_and_train(self):
        for case in self.m.load_cases(ROOT):
            if case['family'] == 'planning':
                self.assertEqual(case['task_ids'], [f'spannerlearning/seed0/problem{i}' for i in range(10)])
                self.assertEqual(case['prompt_task_ids'], case['task_ids'][:2])
                self.assertEqual(case['development_task_ids'], case['task_ids'][2:])
                self.assertEqual([x['task_id'] for x in case['public_packet']['public_examples']], case['task_ids'][:2])
            else:
                self.assertEqual(case['task_ids'], ['oscillator1'])
                self.assertEqual(case['prompt_task_ids'], [])
                self.assertEqual(case['public_packet']['public_examples'], [])

    def test_symbolic_parent_and_term_are_bound_without_scores_in_public_packet(self):
        for case in self.m.load_cases(ROOT)[2:]:
            self.assertEqual((case['n_params'], case['parent_n_params'], case['remove_param_index']), (3, 2, 2))
            self.assertEqual(case['parent_source'].encode(), (ROOT / case['parent_path']).read_bytes())
            target = case['public_packet']['probe_target']
            self.assertEqual(target['parent_source_sha256'], case['parent_sha256'])
            self.assertEqual(target['parent_source'], case['parent_source'])
            self.assertNotIn('metrics', target)
            self.assertNotIn('0.09694020964575169', json.dumps(case['public_packet']))

    def test_model_packet_contains_only_current_observations_and_no_old_control(self):
        forbidden = {'historical_record', 'baseline_results', 'provenance', 'rationale',
                     'history', 'selection', 'audits', 'checks', 'frozen_history_checks',
                     'parent_metrics', 'forecast', 'request', 'response', 'trace'}
        def inspect(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for item in value.values(): inspect(item)
            elif isinstance(value, list):
                for item in value: inspect(item)
        for case in self.m.load_cases(ROOT):
            packet = case['public_packet']
            inspect(packet)
            text = packet['task_text']
            self.assertTrue(text.startswith('## Program interface\n') or text.startswith('## Task and program interface\n'))
            for marker in ('## Revision policy', 'frozen_history', 'claim_value_json', 'Submit it now', 'prediction_id'):
                self.assertNotIn(marker, text)
            self.assertEqual(packet['historical_metrics'], case['baseline_metrics'])
            self.assertEqual(packet, case['state_packet'])

    def test_knowledge_limits_disclose_shared_ancestors_and_development_reuse(self):
        cases = self.m.load_cases(ROOT)
        for case in cases:
            p = case['provenance']
            self.assertEqual(p['candidate_executions_during_load'], 0)
            self.assertEqual(p['model_calls'], 0)
            self.assertEqual(p['sealed_data_reads'], 0)
            self.assertIn('development', p['selection_scope'])
            self.assertIn('not independent', p['selection_scope'])
        self.assertIn('ancestor', cases[2]['provenance']['lineage'])
        self.assertIn('paired-repair', cases[3]['provenance']['lineage'])

    def test_no_selected_source_or_ast_is_one_of_the_previous_five_calibrations(self):
        from rsi_eval.probe_cases import load_cases
        calibrated = load_cases(ROOT)
        previous = calibrated['planning'] + calibrated['symbolic']
        hashes = {c['source_sha256'] for c in previous}
        trees = {ast.dump(ast.parse(c['source']), include_attributes=False) for c in previous}
        for case in self.m.load_cases(ROOT):
            self.assertNotIn(case['source_sha256'], hashes)
            self.assertNotIn(ast.dump(ast.parse(case['source']), include_attributes=False), trees)

    def test_symbolic_transitions_fit_unchanged_static_removal_contract_without_execution(self):
        from rsi_eval.symbolic_probe import build_term_removal
        for case in self.m.load_cases(ROOT)[2:]:
            result = build_term_removal(case['source'], n_params=case['n_params'],
                remove_param_index=case['remove_param_index'], source_sha256=case['source_sha256'],
                parent_source=case['parent_source'], parent_n_params=case['parent_n_params'],
                parent_sha256=case['parent_sha256'])
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(result['n_params_after'], 2)

    def _copy_inputs(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for rel in self.m.INPUT_FILES:
            dest = root / rel; dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, dest)
        return root

    def test_minimal_input_tree_loads_without_data_runtime_or_executor(self):
        root = self._copy_inputs()
        self.assertFalse((root / 'data').exists())
        self.assertFalse((root / 'vendor').exists())
        with patch.dict('sys.modules', {'rsi_eval.executor': None, 'rsi_eval.sandbox': None,
                                       'rsi_eval.pilot_agent': None}):
            self.assertEqual(self.m.load_cases(root), self.m.load_cases(ROOT))

    def test_only_pinned_files_are_read_and_no_files_are_written(self):
        real = Path.read_bytes; seen = set()
        def read(path):
            rel = path.relative_to(ROOT).as_posix(); seen.add(rel)
            self.assertIn(rel, self.m.INPUT_FILES)
            return real(path)
        with patch.object(Path, 'read_bytes', read), patch.object(Path, 'write_bytes', side_effect=AssertionError('write')):
            self.m.load_cases(ROOT)
        self.assertEqual(seen, set(self.m.INPUT_FILES))

    def test_tampering_source_parent_trajectory_diagnostic_or_task_packet_rejected(self):
        cases = self.m.load_cases(ROOT)
        paths = [cases[0]['source_path'], cases[2]['parent_path'],
                 cases[1]['provenance']['trajectory_path'], cases[3]['provenance']['diagnostics_path'],
                 self.m.PUBLIC_PACKETS['planning']['path'], self.m.PUBLIC_PACKETS['symbolic']['path']]
        for relative in paths:
            with self.subTest(relative=relative):
                root = self._copy_inputs(); path = root / relative
                path.write_bytes(path.read_bytes() + b'\n')
                with self.assertRaises(ValueError): self.m.load_cases(root)

    def test_missing_file_is_rejected(self):
        root = self._copy_inputs()
        (root / next(iter(self.m.INPUT_FILES))).unlink()
        with self.assertRaises(ValueError): self.m.load_cases(root)

    def test_all_four_archive_manifests_are_pinned_and_tampering_rejected(self):
        self.assertEqual(len(self.m.INPUT_FILES), 22)
        cases = self.m.load_cases(ROOT)
        manifests = {entry['path'] for case in cases for entry in case['provenance']['archive_manifests']}
        self.assertEqual(len(manifests), 4)
        for relative in manifests:
            with self.subTest(relative=relative):
                root = self._copy_inputs(); path = root / relative
                path.write_bytes(path.read_bytes() + b'\n')
                with self.assertRaises(ValueError): self.m.load_cases(root)

    def test_old_compact_trajectory_is_not_relabelled_as_byte_identical_raw_evidence(self):
        case = self.m.load_cases(ROOT)[2]
        provenance = case['provenance']
        mode = provenance['archive_source_modes'][provenance['trajectory_path']]
        self.assertEqual(mode['archive_mode'], 'derived_compact_view')
        self.assertEqual(mode['raw_path'], 'symbolic_checked/candidates.json')
        self.assertNotEqual(mode['raw_sha256'], self.m.INPUT_FILES[provenance['trajectory_path']])
        source_mode = provenance['archive_source_modes'][case['source_path']]
        self.assertEqual(source_mode['archive_mode'], 'byte_identical_copy')
        self.assertEqual(source_mode['raw_sha256'], case['source_sha256'])

    def test_symlinked_input_is_rejected(self):
        root = self._copy_inputs(); rel = self.m.load_cases(root)[0]['source_path']
        path = root / rel; raw = path.read_bytes(); other = root / 'replacement.py'; other.write_bytes(raw)
        path.unlink()
        try: path.symlink_to(other)
        except OSError as exc: self.skipTest(str(exc))
        with self.assertRaises(ValueError): self.m.load_cases(root)

    def test_public_task_section_rejects_missing_repeated_or_injected_boundaries(self):
        valid = 'old preface\n## Program interface\nAPI\n## Revision policy\nold controls'
        self.assertEqual(self.m._task_section(valid, 'planning'), '## Program interface\nAPI')
        for value in [valid.replace('## Revision policy', '## Other'), valid + '\n## Revision policy\nextra',
                      valid.replace('API', 'claim_value_json'), valid.replace('## Program interface', '## Wrong')]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError): self.m._task_section(value, 'planning')

    def test_fresh_load_and_aliases_are_independent_objects(self):
        first = self.m.load_cases(ROOT); expected = copy.deepcopy(first)
        first[0]['public_packet']['historical_metrics'].clear()
        first[0]['baseline_results'].clear()
        self.assertEqual(first[0]['state_packet'], expected[0]['state_packet'])
        self.assertEqual(first[0]['historical_record'], expected[0]['historical_record'])
        self.assertEqual(self.m.load_cases(ROOT), expected)


if __name__ == '__main__': unittest.main()
